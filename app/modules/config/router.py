"""Endpoints REST del Panel de Parámetros Globales (GLO-03, SPEC-01 §6.12–6.14).

Montado en ``/api/v1/config``.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.enums import RolUsuario
from app.core.errors import error_responses
from app.database import get_db
from app.modules.config import service
from app.modules.config.models import ParametroGlobal, ParametroGlobalHistorial
from app.modules.config.schemas import ParametroHistorialItem, ParametroResponse, ParametroUpdate
from app.modules.users.models import Usuario

router = APIRouter()


@router.get(
    "/parametros",
    response_model=list[ParametroResponse],
    summary="Listar parámetros globales",
    responses=error_responses(401),
    dependencies=[Depends(get_current_user)],
)
async def listar_parametros(db: AsyncSession = Depends(get_db)) -> list[ParametroGlobal]:
    """Cualquier usuario activo puede leerlos: el frontend los usa para acotar calendarios (GLO-03)."""
    return await service.listar(db)


@router.get(
    "/parametros/{clave}",
    response_model=ParametroResponse,
    summary="Obtener un parámetro global",
    responses=error_responses(401, 404),
    dependencies=[Depends(get_current_user)],
)
async def obtener_parametro(clave: str, db: AsyncSession = Depends(get_db)) -> ParametroGlobal:
    return await service.obtener(db, clave)


@router.put(
    "/parametros/{clave}",
    response_model=ParametroResponse,
    summary="Modificar un parámetro global (sólo Superadministrador)",
    responses=error_responses(401, 403, 404, 409),
)
async def actualizar_parametro(
    clave: str,
    payload: ParametroUpdate,
    actor: Usuario = Depends(require_roles(RolUsuario.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ParametroGlobal:
    """Bloqueo optimista por ``version``; rige para operaciones nuevas (RN-21, D-05)."""
    return await service.actualizar(db, actor, clave, payload)


@router.get(
    "/parametros/{clave}/historial",
    response_model=list[ParametroHistorialItem],
    summary="Historial de modificaciones de un parámetro",
    responses=error_responses(401, 403, 404),
    dependencies=[Depends(require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN))],
)
async def historial_parametro(
    clave: str,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[ParametroGlobalHistorial]:
    return await service.historial(db, clave, limit)
