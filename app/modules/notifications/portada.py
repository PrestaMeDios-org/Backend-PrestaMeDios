"""Portada elegible de los comunicados (NOV-02, SPEC-06 §15, ADR-028).

Quien puede editar un comunicado elige uno de cuatro temas de color o sube una foto;
sin portada, el frontend asigna el color automáticamente. Nació como MOMENTÁNEA en
SPEC-10 (M-02, §4.7) y el Perfil 5 la adoptó tal cual el 2026-11-27: el contrato es el
de SPEC-10 §4.7. Tabla propia ``comunicados_portada`` (migración ``0020``); no modifica
``comunicados``, sus esquemas ni el módulo ``files``.
"""

import asyncio
import io
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.deps import get_current_user, require_roles, resolver_alcance_sede
from app.core.enums import RolUsuario
from app.core.errors import AppError, error_responses
from app.core.settings import ahora_lab
from app.database import Base, get_db
from app.modules.files.service import (
    ArchivoContenido,
    demasiado_grande,
    detectar_tipo,
    imagen_invalida,
    respuesta_descarga,
    tipo_no_permitido,
)
from app.modules.notifications import service
from app.modules.notifications.models import Comunicado
from app.modules.users.models import Usuario

TEMAS = ("rojo", "amarillo", "azul", "verde")
Tema = Literal["rojo", "amarillo", "azul", "verde"]

MAX_MB = 5
MAX_BYTES = MAX_MB * 1024 * 1024
LADO_MAX = 1600
MAX_PIXELES = 25_000_000
MAX_IDS = 50
MAX_ID = 2**31 - 1  # `comunicados.id` es `integer`: un id mayor no existe y PostgreSQL lo rechaza
TIPOS = {"image/jpeg", "image/png", "image/webp"}


# ── Reglas de `notifications` (Perfil 5) ─────────────────────────────────────
# Reusa las funciones públicas de `notifications.service` para aplicar exactamente las
# mismas reglas de lectura (RN-N3) y edición (RN-N5) que los comunicados (SPEC-10 U4).
_filtro_lectura = service.filtro_lectura
_bloquear_para_editar = service.bloquear_para_editar


# ── Modelo ───────────────────────────────────────────────────────────────────


class ComunicadoPortada(Base):
    """Una fila por comunicado con portada elegida; sin fila, automática."""

    __tablename__ = "comunicados_portada"
    __table_args__ = (
        CheckConstraint(
            "tema IS NULL OR tema IN ('rojo', 'amarillo', 'azul', 'verde')", name="tema_valido"
        ),
        CheckConstraint("(tema IS NULL) <> (imagen IS NULL)", name="tema_o_imagen"),
    )

    comunicado_id: Mapped[int] = mapped_column(
        ForeignKey("comunicados.id", ondelete="CASCADE"), primary_key=True
    )
    tema: Mapped[str | None] = mapped_column(String(10))
    imagen: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    tipo_mime: Mapped[str | None] = mapped_column(String(20))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Esquemas ─────────────────────────────────────────────────────────────────


class PortadaTemaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tema: Tema = Field(..., examples=["azul"])


class PortadaResponse(BaseModel):
    comunicado_id: int = Field(..., examples=[3])
    tema: Tema | None = Field(default=None, examples=["azul"])
    tiene_imagen: bool = Field(..., examples=[False])
    actualizado_en: datetime = Field(..., examples=["2026-11-12T22:00:00-03:00"])


def _respuesta(p: ComunicadoPortada, tiene_imagen: bool) -> PortadaResponse:
    return PortadaResponse(
        comunicado_id=p.comunicado_id,
        tema=p.tema,  # type: ignore[arg-type]
        tiene_imagen=tiene_imagen,
        actualizado_en=p.actualizado_en,
    )


# ── Imagen ───────────────────────────────────────────────────────────────────


def _procesar_sync(datos: bytes) -> bytes:
    """Re-codifica como JPEG de hasta 1600 px por lado, sin metadatos (como D-11 de SPEC-03)."""
    try:
        with Image.open(io.BytesIO(datos)) as original:
            ancho, alto = original.size
            if ancho * alto > MAX_PIXELES:
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
            imagen.thumbnail((LADO_MAX, LADO_MAX))
            salida = io.BytesIO()
            imagen.save(salida, format="JPEG", quality=85, optimize=True)
    except AppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise imagen_invalida() from None
    return salida.getvalue()


async def _leer_imagen(archivo: UploadFile) -> bytes:
    datos = await archivo.read(MAX_BYTES + 1)
    if len(datos) > MAX_BYTES:
        raise demasiado_grande(MAX_MB)
    if detectar_tipo(datos) not in TIPOS:
        raise tipo_no_permitido()
    return await asyncio.to_thread(_procesar_sync, datos)


# ── Servicio ─────────────────────────────────────────────────────────────────


async def _guardar(db: AsyncSession, usuario: Usuario, comunicado_id: int, **valores) -> PortadaResponse:
    # Mismo permiso que editar el comunicado (RN-N5): bloquea la fila o responde 404.
    await _bloquear_para_editar(db, usuario, comunicado_id)
    portada = await db.get(ComunicadoPortada, comunicado_id)
    if portada is None:
        portada = ComunicadoPortada(comunicado_id=comunicado_id)
        db.add(portada)
    for campo, valor in valores.items():
        setattr(portada, campo, valor)
    portada.actualizado_en = ahora_lab()
    await db.commit()
    await db.refresh(portada)
    return _respuesta(portada, valores.get("imagen") is not None)


# ── Rutas ────────────────────────────────────────────────────────────────────

router = APIRouter()
_admins = require_roles(RolUsuario.SUPERADMIN, RolUsuario.ADMIN_LOCAL)


@router.get(
    "/comunicados/portadas",
    response_model=list[PortadaResponse],
    summary="Portadas elegidas de varios comunicados",
    responses=error_responses(401, 422),
)
async def listar_portadas(
    ids: str = Query(..., description="Ids separados por coma (máx. 50)", examples=["3,4,5"]),
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PortadaResponse]:
    """Sólo de los comunicados que ``usuario`` puede leer; sin portada, se omiten."""
    try:
        pedidos = sorted({int(x) for x in ids.split(",") if x.strip()})
    except ValueError:
        raise AppError(422, "IDS_INVALIDOS", "Los ids tienen que ser números separados por coma.") from None
    if not pedidos or len(pedidos) > MAX_IDS:
        raise AppError(422, "IDS_INVALIDOS", f"Entre 1 y {MAX_IDS} ids.")
    if pedidos[0] < 1 or pedidos[-1] > MAX_ID:
        raise AppError(422, "IDS_INVALIDOS", f"Los ids tienen que estar entre 1 y {MAX_ID}.")
    # Una sola consulta: las mismas reglas de lectura que `obtener_comunicado` (RN-N3).
    sedes = resolver_alcance_sede(usuario, None)
    filas = (
        await db.execute(
            select(
                ComunicadoPortada.comunicado_id,
                ComunicadoPortada.tema,
                ComunicadoPortada.actualizado_en,
                ComunicadoPortada.imagen.is_not(None).label("tiene_imagen"),
            )
            .join(Comunicado, Comunicado.id == ComunicadoPortada.comunicado_id)
            .where(
                ComunicadoPortada.comunicado_id.in_(pedidos),
                *_filtro_lectura(usuario, sedes, incluir_archivados=True, ahora=ahora_lab()),
            )
        )
    ).all()
    return [
        PortadaResponse(
            comunicado_id=f.comunicado_id, tema=f.tema, tiene_imagen=f.tiene_imagen, actualizado_en=f.actualizado_en
        )
        for f in filas
    ]


@router.put(
    "/comunicados/{comunicado_id}/portada",
    response_model=PortadaResponse,
    summary="Elegir el tema de color de la portada",
    responses=error_responses(401, 403, 404, 422),
)
async def elegir_tema(
    comunicado_id: int,
    datos: PortadaTemaUpdate,
    usuario: Usuario = Depends(_admins),
    db: AsyncSession = Depends(get_db),
) -> PortadaResponse:
    return await _guardar(db, usuario, comunicado_id, tema=datos.tema, imagen=None, tipo_mime=None)


@router.put(
    "/comunicados/{comunicado_id}/portada/imagen",
    response_model=PortadaResponse,
    summary="Subir una foto de portada",
    responses=error_responses(401, 403, 404, 422),
)
async def subir_imagen(
    comunicado_id: int,
    archivo: UploadFile = File(...),
    usuario: Usuario = Depends(_admins),
    db: AsyncSession = Depends(get_db),
) -> PortadaResponse:
    # El límite de 5 MB lo aplica `_leer_imagen`: cuando esto corre, FastAPI ya recibió el cuerpo.
    jpeg = await _leer_imagen(archivo)
    return await _guardar(db, usuario, comunicado_id, tema=None, imagen=jpeg, tipo_mime="image/jpeg")


@router.delete(
    "/comunicados/{comunicado_id}/portada",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Volver a la portada automática",
    responses=error_responses(401, 403, 404),
)
async def quitar_portada(
    comunicado_id: int,
    usuario: Usuario = Depends(_admins),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _bloquear_para_editar(db, usuario, comunicado_id)
    portada = await db.get(ComunicadoPortada, comunicado_id)
    if portada is not None:
        await db.delete(portada)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/comunicados/{comunicado_id}/portada/imagen",
    response_class=Response,
    summary="Foto de portada",
    responses=error_responses(401, 404),
)
async def ver_imagen(
    comunicado_id: int,
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    comunicado: Comunicado = await service.obtener_comunicado(db, usuario, comunicado_id)
    fila = (
        await db.execute(
            select(ComunicadoPortada.imagen, ComunicadoPortada.tipo_mime).where(
                ComunicadoPortada.comunicado_id == comunicado.id
            )
        )
    ).first()
    if fila is None or fila.imagen is None:
        raise AppError(404, "PORTADA_NO_ENCONTRADA", "El comunicado no tiene foto de portada.")
    return respuesta_descarga(
        ArchivoContenido(
            id=None,  # type: ignore[arg-type]
            tipo_mime=fila.tipo_mime or "image/jpeg",
            nombre_original=f"portada-{comunicado.id}.jpg",
            datos=fila.imagen,
        )
    )
