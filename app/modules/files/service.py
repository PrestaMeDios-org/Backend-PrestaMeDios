"""Reglas de negocio del módulo `files` (SPEC-03 §6, Fase B2).

El archivo empieza con las funciones internas del Perfil 1 (las usan este módulo y
`users` para la foto de perfil) y termina con la **API pública** para otros módulos
(§6.5, P3.3 con la enmienda 1.1.1): ``vincular_archivo``, ``abrir_archivo``,
``respuesta_descarga`` y ``ArchivoContenido``.
"""

import asyncio
import hashlib
import io
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RolUsuario
from app.core.errors import AppError
from app.core.settings import get_settings
from app.modules.files.enums import PropositoArchivo
from app.modules.files.models import Archivo, ArchivoDatos
from app.modules.users.models import Usuario

MB = 1024 * 1024
# Lo que el multipart agrega alrededor del archivo (límites, encabezados, otros campos).
MARGEN_MULTIPART = 64 * 1024

FOTO_LADO_MAX = 512
FOTO_CALIDAD = 85
# Tope de píxeles antes de decodificar, contra imágenes "bomba" (plan §6.2).
FOTO_MAX_PIXELES = 25_000_000

JPEG, PNG, WEBP, PDF = "image/jpeg", "image/png", "image/webp", "application/pdf"

TIPOS_POR_PROPOSITO: dict[PropositoArchivo, frozenset[str]] = {
    PropositoArchivo.FOTO_PERFIL: frozenset({JPEG, PNG, WEBP}),
    PropositoArchivo.AVAL_PRESTAMO: frozenset({PDF}),
}


# ── Errores (catálogo §8) ────────────────────────────────────────────────────


def tipo_no_permitido() -> AppError:
    return AppError(422, "TIPO_ARCHIVO_NO_PERMITIDO", "El tipo de archivo no está permitido.")


def demasiado_grande(max_mb: int) -> AppError:
    return AppError(
        422,
        "ARCHIVO_DEMASIADO_GRANDE",
        f"El archivo supera el tamaño máximo de {max_mb} MB.",
        max_mb=max_mb,
    )


def proposito_invalido() -> AppError:
    return AppError(422, "PROPOSITO_INVALIDO", "Ese tipo de archivo no se puede subir desde acá.")


def imagen_invalida() -> AppError:
    return AppError(422, "IMAGEN_INVALIDA", "No se pudo leer la imagen.")


def demasiados_pendientes() -> AppError:
    return AppError(
        409,
        "DEMASIADOS_ARCHIVOS_PENDIENTES",
        "Tenés demasiados archivos sin usar. Esperá o enviá la solicitud.",
    )


def archivo_no_encontrado() -> AppError:
    return AppError(404, "ARCHIVO_NO_ENCONTRADO", "Archivo no encontrado.")


def archivo_invalido() -> AppError:
    return AppError(
        422, "ARCHIVO_INVALIDO", "El archivo indicado no es válido para esta operación."
    )


# ── Lectura, tipo y nombre (RN-55…RN-57) ─────────────────────────────────────


def max_mb(proposito: PropositoArchivo) -> int:
    settings = get_settings()
    if proposito == PropositoArchivo.FOTO_PERFIL:
        return settings.archivo_foto_max_mb
    return settings.archivo_pdf_max_mb


async def leer_con_limite(
    archivo: UploadFile, proposito: PropositoArchivo, *, content_length: int | None
) -> bytes:
    """RN-56: corta la lectura al pasar el máximo; nunca carga el resto en memoria.

    ``content_length`` es el de la request: si ya supera el máximo más el margen del
    multipart, se rechaza sin leer nada.
    """
    limite_mb = max_mb(proposito)
    maximo = limite_mb * MB
    if content_length is not None and content_length > maximo + MARGEN_MULTIPART:
        raise demasiado_grande(limite_mb)
    datos = await archivo.read(maximo + 1)
    if len(datos) > maximo:
        raise demasiado_grande(limite_mb)
    return datos


def detectar_tipo(datos: bytes) -> str | None:
    """RN-55: el tipo sale de la firma de los primeros bytes, no de la extensión."""
    if datos.startswith(b"\xff\xd8\xff"):
        return JPEG
    if datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if len(datos) >= 12 and datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return WEBP
    if datos.startswith(b"%PDF-"):
        return PDF
    return None


def validar_tipo(datos: bytes, proposito: PropositoArchivo) -> str:
    tipo = detectar_tipo(datos)
    if tipo is None or tipo not in TIPOS_POR_PROPOSITO[proposito]:
        raise tipo_no_permitido()
    return tipo


def sanear_nombre(nombre: str | None, *, por_defecto: str = "archivo") -> str:
    """RN-57: sin rutas ni caracteres de control, hasta 255 caracteres."""
    base = (nombre or "").replace("\\", "/").rsplit("/", 1)[-1]
    limpio = "".join(c for c in base if not unicodedata.category(c).startswith("C")).strip()
    limpio = limpio.lstrip(".").strip()
    return (limpio or por_defecto)[:255]


def _con_extension(nombre: str, extension: str) -> str:
    raiz = nombre.rsplit(".", 1)[0] if "." in nombre else nombre
    return f"{raiz[: 255 - len(extension)]}{extension}"


# ── Foto (D-11) ──────────────────────────────────────────────────────────────


def _procesar_foto_sync(datos: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(datos)) as original:
            ancho, alto = original.size
            if ancho * alto > FOTO_MAX_PIXELES:
                raise imagen_invalida()
            original.load()
            imagen = ImageOps.exif_transpose(original)
            if imagen.mode in ("RGBA", "LA", "P"):
                imagen = imagen.convert("RGBA")
                fondo = Image.new("RGB", imagen.size, (255, 255, 255))
                fondo.paste(imagen, mask=imagen.getchannel("A"))
                imagen = fondo
            else:
                imagen = imagen.convert("RGB")
            imagen.thumbnail((FOTO_LADO_MAX, FOTO_LADO_MAX))
            salida = io.BytesIO()
            # Sin `exif=` ni `icc_profile=`: el JPEG nuevo no lleva metadatos.
            imagen.save(salida, format="JPEG", quality=FOTO_CALIDAD, optimize=True)
    except AppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise imagen_invalida() from None
    return salida.getvalue()


async def procesar_foto(datos: bytes) -> bytes:
    """D-11: decodifica y vuelve a codificar como JPEG de hasta 512 px, sin EXIF.

    Neutraliza archivos políglotas y quita la ubicación. Corre fuera del event loop.
    """
    return await asyncio.to_thread(_procesar_foto_sync, datos)


async def preparar_foto(
    archivo: UploadFile, *, content_length: int | None
) -> tuple[bytes, str]:
    """Lee, valida y procesa una foto subida. Devuelve ``(jpeg, nombre)``."""
    datos = await leer_con_limite(
        archivo, PropositoArchivo.FOTO_PERFIL, content_length=content_length
    )
    validar_tipo(datos, PropositoArchivo.FOTO_PERFIL)
    jpeg = await procesar_foto(datos)
    nombre = _con_extension(sanear_nombre(archivo.filename, por_defecto="foto"), ".jpg")
    return jpeg, nombre


# ── Alta, baja y limpieza ────────────────────────────────────────────────────


async def _bloquear_propietario(db: AsyncSession, propietario_id: int) -> None:
    """Serializa las altas de un mismo usuario para que la cuota no se pase (RN-58)."""
    await db.execute(select(Usuario.id).where(Usuario.id == propietario_id).with_for_update())


async def contar_pendientes(db: AsyncSession, propietario_id: int) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Archivo)
            .where(Archivo.propietario_id == propietario_id, Archivo.vinculado_en.is_(None))
        )
        or 0
    )


async def guardar_archivo(
    db: AsyncSession,
    *,
    propietario: Usuario,
    proposito: PropositoArchivo,
    datos: bytes,
    tipo_mime: str,
    nombre: str,
    vinculado: bool,
) -> Archivo:
    """Inserta metadatos y contenido con ``flush``, sin ``commit``.

    Si el archivo queda sin vincular, controla la cuota (RN-58) con la fila del
    propietario bloqueada.
    """
    if not vinculado:
        await _bloquear_propietario(db, propietario.id)
        if await contar_pendientes(db, propietario.id) >= get_settings().archivo_max_pendientes:
            raise demasiados_pendientes()

    archivo = Archivo(
        id=uuid.uuid4(),
        propietario_id=propietario.id,
        proposito=proposito,
        sede=propietario.sede,
        tipo_mime=tipo_mime,
        tamano_bytes=len(datos),
        sha256=hashlib.sha256(datos).hexdigest(),
        nombre_original=nombre,
        vinculado_en=datetime.now(UTC) if vinculado else None,
    )
    db.add(archivo)
    await db.flush()
    db.add(ArchivoDatos(archivo_id=archivo.id, datos=datos))
    await db.flush()
    return archivo


async def subir_archivo(
    db: AsyncSession,
    actor: Usuario,
    archivo: UploadFile,
    proposito: str,
    *,
    content_length: int | None,
) -> Archivo:
    """``POST /files/archivos``: sólo el aval de préstamo, que queda sin vincular (§6.3)."""
    if proposito != PropositoArchivo.AVAL_PRESTAMO:
        raise proposito_invalido()
    destino = PropositoArchivo.AVAL_PRESTAMO
    datos = await leer_con_limite(archivo, destino, content_length=content_length)
    tipo = validar_tipo(datos, destino)
    try:
        nuevo = await guardar_archivo(
            db,
            propietario=actor,
            proposito=destino,
            datos=datos,
            tipo_mime=tipo,
            nombre=sanear_nombre(archivo.filename, por_defecto="aval.pdf"),
            vinculado=False,
        )
    except AppError:
        await db.rollback()
        raise
    await db.commit()
    return nuevo


async def borrar_archivo(db: AsyncSession, archivo_id: uuid.UUID) -> None:
    """Borra metadatos y contenido (``CASCADE``), sin ``commit``. Interna: RN-62."""
    await db.execute(delete(Archivo).where(Archivo.id == archivo_id))


async def limpiar_huerfanos(db: AsyncSession, *, horas: int | None = None) -> int:
    """RN-63: borra los no vinculados creados hace más de ``horas``. Idempotente.

    Devuelve cuántos borró. Hace ``commit``: es una tarea de mantenimiento.
    """
    horas = horas if horas is not None else get_settings().archivo_huerfano_horas
    limite = datetime.now(UTC) - timedelta(hours=horas)
    resultado = await db.execute(
        delete(Archivo).where(Archivo.vinculado_en.is_(None), Archivo.created_at < limite)
    )
    await db.commit()
    return resultado.rowcount or 0


# ── Descarga (RN-60, RN-61) ──────────────────────────────────────────────────


def puede_descargar(actor: Usuario, archivo: Archivo, sede_actual_propietario) -> bool:
    """RN-60. Quien no puede recibe ``404``, nunca ``403`` (RN-11 de SPEC-01).

    - ``SUPERADMIN``: todo. El propietario: lo suyo.
    - ``ADMIN_LOCAL``: la foto si tiene jurisdicción sobre la sede **actual** del
      propietario; el aval si la tiene sobre ``archivos.sede`` (EC-44).
    - Nadie más, tampoco el docente de la asignatura (D-18, EC-48).
    """
    if actor.rol == RolUsuario.SUPERADMIN or actor.id == archivo.propietario_id:
        return True
    if actor.rol != RolUsuario.ADMIN_LOCAL or actor.sede is None:
        return False
    if archivo.proposito == PropositoArchivo.FOTO_PERFIL:
        return sede_actual_propietario == actor.sede
    return archivo.sede == actor.sede


async def descargar(db: AsyncSession, actor: Usuario, archivo_id: uuid.UUID) -> Response:
    """``GET /files/archivos/{id}/contenido`` con el control de RN-60."""
    archivo = await db.get(Archivo, archivo_id)
    if archivo is None:
        raise archivo_no_encontrado()
    sede_propietario = await db.scalar(
        select(Usuario.sede).where(Usuario.id == archivo.propietario_id)
    )
    if not puede_descargar(actor, archivo, sede_propietario):
        raise archivo_no_encontrado()
    contenido = await abrir_archivo(db, archivo_id)
    if contenido is None:  # borrado entre las dos lecturas
        raise archivo_no_encontrado()
    return respuesta_descarga(contenido)


# ── API pública para otros módulos (SPEC-03 §6.5, P3.3) ──────────────────────
#
# Lo que está debajo de esta línea es contrato: `loans` lo importa para el aval
# (C4 de SPEC-05). El resto de este archivo es interno del Perfil 1.


@dataclass(frozen=True, slots=True)
class ArchivoContenido:
    """Contenido de un archivo listo para servir (§6.5)."""

    id: uuid.UUID
    tipo_mime: str
    nombre_original: str
    datos: bytes


async def vincular_archivo(
    db: AsyncSession,
    archivo_id: uuid.UUID,
    *,
    propietario_id: int,
    proposito: PropositoArchivo,
) -> None:
    """Marca vinculado un archivo subido por ``propietario_id`` (PRE-05, C4 de SPEC-05).

    Función pública (P3.3, enmienda 1.1.1). Bloquea la fila (``FOR UPDATE``). Si el
    archivo no existe, es de otro propietario, tiene otro propósito o ya está
    vinculado, responde ``422 ARCHIVO_INVALIDO``: un solo código para no revelar cuál
    (D-19). No hace ``commit``, ``rollback`` ni ``flush``: `loans` la llama en la misma
    transacción que crea la orden.
    """
    archivo = await db.scalar(
        select(Archivo)
        .where(Archivo.id == archivo_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        archivo is None
        or archivo.propietario_id != propietario_id
        or archivo.proposito != proposito
        or archivo.vinculado_en is not None
    ):
        raise archivo_invalido()
    archivo.vinculado_en = datetime.now(UTC)


async def abrir_archivo(db: AsyncSession, archivo_id: uuid.UUID) -> ArchivoContenido | None:
    """Contenido de un archivo, o ``None`` si no existe (§6.5).

    Función pública (P3.3). **Sin control de acceso**: lo hace quien llama, y debe
    respetar RN-60 (el docente de la asignatura no descarga el aval, D-18).
    """
    fila = (
        await db.execute(
            select(Archivo.id, Archivo.tipo_mime, Archivo.nombre_original, ArchivoDatos.datos)
            .join(ArchivoDatos, ArchivoDatos.archivo_id == Archivo.id)
            .where(Archivo.id == archivo_id)
        )
    ).first()
    if fila is None:
        return None
    return ArchivoContenido(
        id=fila.id, tipo_mime=fila.tipo_mime, nombre_original=fila.nombre_original, datos=fila.datos
    )


def _content_disposition(tipo: str, nombre: str) -> str:
    """``attachment`` para PDF e ``inline`` para fotos, con el nombre en RFC 5987."""
    modo = "attachment" if tipo == PDF else "inline"
    ascii_ = "".join(c if 32 <= ord(c) < 127 and c not in '"\\;' else "_" for c in nombre)
    return f"{modo}; filename=\"{ascii_ or 'archivo'}\"; filename*=UTF-8''{quote(nombre, safe='')}"


def respuesta_descarga(contenido: ArchivoContenido) -> Response:
    """Respuesta con los encabezados de RN-61, para que todos los módulos sirvan igual.

    Función pública (P3.3).
    """
    return Response(
        content=contenido.datos,
        media_type=contenido.tipo_mime,
        headers={
            "Content-Disposition": _content_disposition(
                contenido.tipo_mime, contenido.nombre_original
            ),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )
