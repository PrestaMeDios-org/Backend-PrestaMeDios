"""Endpoints REST del módulo `notifications` (SPEC-06 §5).

- Todos exigen sesión (P4.1).
- Comunicados (NOV-02): lectura para todos los roles según su alcance de sede
  (RN-N3); publicación, edición y archivo sólo para administradores (RN-N2, RN-N5).
- Notificaciones personales (NOV-04): se agregan en la Fase B.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import error_responses
from app.database import get_db
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    ComunicadoCreate,
    ComunicadoEstadoUpdate,
    ComunicadoResponse,
    ComunicadosPage,
    ComunicadoUpdate,
)
from app.modules.users.models import Usuario

router = APIRouter()

_solo_admins = require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)

_LIMIT = Query(20, ge=1, le=100, description="Cantidad máxima de resultados.")
_OFFSET = Query(0, ge=0, description="Resultados a saltear.")


async def _una(db: AsyncSession, comunicado) -> ComunicadoResponse:
    return (await service.a_respuestas(db, [comunicado]))[0]


# ── Comunicados (NOV-02) ─────────────────────────────────────────────────────


@router.get(
    "/comunicados",
    response_model=ComunicadosPage,
    summary="Listar comunicados",
    description=(
        "Comunicados de la sede del usuario más los globales, del más nuevo al más viejo. "
        "Estudiantes y docentes ven sólo los vigentes. Sólo el `SUPERADMIN` puede filtrar "
        "por `sede`; `incluir_archivados` se ignora para quien no es administrador."
    ),
    responses=error_responses(401, 403, 422),
)
async def listar_comunicados(
    sede: SedeEnum | None = Query(None, description="Sólo `SUPERADMIN`."),
    incluir_archivados: bool = Query(False, description="Sólo administradores."),
    limit: int = _LIMIT,
    offset: int = _OFFSET,
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ComunicadosPage:
    comunicados, total = await service.listar_comunicados(
        db,
        usuario,
        sede=sede,
        incluir_archivados=incluir_archivados,
        limit=limit,
        offset=offset,
    )
    return ComunicadosPage(items=await service.a_respuestas(db, comunicados), total=total)


@router.get(
    "/comunicados/{comunicado_id}",
    response_model=ComunicadoResponse,
    summary="Ver un comunicado",
    responses=error_responses(401, 404),
)
async def obtener_comunicado(
    comunicado_id: int,
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ComunicadoResponse:
    return await _una(db, await service.obtener_comunicado(db, usuario, comunicado_id))


@router.post(
    "/comunicados",
    response_model=ComunicadoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publicar un comunicado",
    description=(
        "Un `ADMIN_LOCAL` publica en su sede. Un `SUPERADMIN` indica una `sede` o "
        "`es_global: true` (nunca las dos)."
    ),
    responses=error_responses(401, 403, 422),
)
async def crear_comunicado(
    payload: ComunicadoCreate,
    usuario: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> ComunicadoResponse:
    comunicado = service.crear_comunicado(db, usuario, payload)
    await db.commit()
    return await _una(db, comunicado)


@router.patch(
    "/comunicados/{comunicado_id}",
    response_model=ComunicadoResponse,
    summary="Editar un comunicado",
    description="Edita `titulo`, `contenido` y `vence_en`. `vence_en: null` quita el vencimiento.",
    responses=error_responses(401, 403, 404, 422),
)
async def editar_comunicado(
    comunicado_id: int,
    payload: ComunicadoUpdate,
    usuario: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> ComunicadoResponse:
    comunicado = await service.editar_comunicado(db, usuario, comunicado_id, payload)
    await db.commit()
    return await _una(db, comunicado)


@router.patch(
    "/comunicados/{comunicado_id}/estado",
    response_model=ComunicadoResponse,
    summary="Archivar o reactivar un comunicado",
    responses=error_responses(401, 403, 404, 422),
)
async def cambiar_estado_comunicado(
    comunicado_id: int,
    payload: ComunicadoEstadoUpdate,
    usuario: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> ComunicadoResponse:
    comunicado = await service.cambiar_estado_comunicado(
        db, usuario, comunicado_id, payload.estado
    )
    await db.commit()
    return await _una(db, comunicado)
