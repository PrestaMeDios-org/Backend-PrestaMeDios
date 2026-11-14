"""MOMENTÁNEO (SPEC-10 M-02, §4.7): portada elegible de los comunicados.

Quien puede editar un comunicado elige uno de cuatro temas de color o sube una foto;
sin portada, el frontend asigna el color automáticamente. **No tiene requisito en el
ERS** (NOV-02 no habla de imágenes): está aislado a propósito para poder sacarlo.

Para sacarlo: ``alembic downgrade`` de ``0020_notifications_portada`` (borra sólo la
tabla ``comunicados_portada``), borrar este archivo y ``tests/notifications/test_portada.py``,
y las líneas marcadas con ``MOMENTÁNEO (SPEC-10 M-02)`` en ``app/main.py`` y ``alembic/env.py``.
No modifica ``comunicados``, sus esquemas ni el módulo ``files``.
"""

import asyncio
import io
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.deps import get_current_user, require_roles
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
TIPOS = {"image/jpeg", "image/png", "image/webp"}


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
    await service._bloquear_para_editar(db, usuario, comunicado_id)
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
    summary="Portadas elegidas de varios comunicados (MOMENTÁNEO, SPEC-10 M-02)",
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
    visibles: list[int] = []
    for cid in pedidos:
        try:
            await service.obtener_comunicado(db, usuario, cid)
            visibles.append(cid)
        except AppError:
            continue
    if not visibles:
        return []
    filas = (
        await db.execute(
            select(
                ComunicadoPortada.comunicado_id,
                ComunicadoPortada.tema,
                ComunicadoPortada.actualizado_en,
                ComunicadoPortada.imagen.is_not(None).label("tiene_imagen"),
            ).where(ComunicadoPortada.comunicado_id.in_(visibles))
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
    summary="Elegir el tema de color de la portada (MOMENTÁNEO, SPEC-10 M-02)",
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
    summary="Subir una foto de portada (MOMENTÁNEO, SPEC-10 M-02)",
    responses=error_responses(401, 403, 404, 422),
)
async def subir_imagen(
    comunicado_id: int,
    request: Request,
    archivo: UploadFile = File(...),
    usuario: Usuario = Depends(_admins),
    db: AsyncSession = Depends(get_db),
) -> PortadaResponse:
    largo = request.headers.get("content-length")
    if largo and largo.isdigit() and int(largo) > MAX_BYTES + 64 * 1024:
        raise demasiado_grande(MAX_MB)
    jpeg = await _leer_imagen(archivo)
    return await _guardar(db, usuario, comunicado_id, tema=None, imagen=jpeg, tipo_mime="image/jpeg")


@router.delete(
    "/comunicados/{comunicado_id}/portada",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Volver a la portada automática (MOMENTÁNEO, SPEC-10 M-02)",
    responses=error_responses(401, 403, 404),
)
async def quitar_portada(
    comunicado_id: int,
    usuario: Usuario = Depends(_admins),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await service._bloquear_para_editar(db, usuario, comunicado_id)
    portada = await db.get(ComunicadoPortada, comunicado_id)
    if portada is not None:
        await db.delete(portada)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/comunicados/{comunicado_id}/portada/imagen",
    response_class=Response,
    summary="Foto de portada (MOMENTÁNEO, SPEC-10 M-02)",
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
