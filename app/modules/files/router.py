"""Endpoints REST de `files`, montados en ``/api/v1/files`` (SPEC-03 §6.3).

La foto de perfil no se sube por acá: va por ``PUT /auth/me/foto`` (un solo paso).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.enums import RolUsuario
from app.core.errors import error_responses
from app.database import get_db
from app.modules.files import service
from app.modules.files.models import Archivo
from app.modules.files.schemas import ArchivoResponse
from app.modules.users.models import Usuario

router = APIRouter()

_solicitantes = require_roles(RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE)


def content_length(request: Request) -> int | None:
    """``Content-Length`` de la request, si viene y es un número (RN-56)."""
    valor = request.headers.get("content-length")
    return int(valor) if valor is not None and valor.isdigit() else None


@router.post(
    "/archivos",
    response_model=ArchivoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir el PDF de aval de un pedido de alta gama",
    responses=error_responses(401, 403, 409, 422),
)
async def subir_archivo(
    archivo: UploadFile = File(..., description="PDF de la resolución del Consejo (CICSE/ICSE)."),
    proposito: str = Form(..., examples=["AVAL_PRESTAMO"]),
    largo: int | None = Depends(content_length),
    actor: Usuario = Depends(_solicitantes),
    db: AsyncSession = Depends(get_db),
) -> Archivo:
    """Sube el aval de PRE-05 sin vincular; su id viaja después en la orden (C4 de SPEC-05).

    El tipo se decide por los bytes (RN-55) y el tamaño se corta al leer (RN-56). Cada
    usuario tiene a lo sumo 5 archivos sin vincular (RN-58).
    """
    return await service.subir_archivo(db, actor, archivo, proposito, content_length=largo)


@router.get(
    "/archivos/{archivo_id}/contenido",
    summary="Descargar un archivo",
    response_class=Response,
    responses={
        200: {
            "description": "Contenido del archivo, con los encabezados de RN-61.",
            "content": {"application/pdf": {}, "image/jpeg": {}},
        },
        **error_responses(401, 404),
    },
)
async def descargar_archivo(
    archivo_id: UUID,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Fuera de lo que RN-60 permite responde ``404``, igual que si no existiera."""
    return await service.descargar(db, actor, archivo_id)
