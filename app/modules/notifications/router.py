"""Endpoints REST del módulo `notifications` (SPEC-06 §5).

- Todos exigen sesión (P4.1).
- Comunicados (NOV-02): lectura para todos los roles según su alcance de sede
  (RN-N3); publicación, edición y archivo sólo para administradores (RN-N2, RN-N5).
- Notificaciones personales (NOV-04): cada usuario ve y marca sólo las propias (RN-N6).
  No hay `POST /notificaciones`: se crean desde el código de servicio (§6).
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
    LeerTodasResponse,
    NotificacionesPage,
    NotificacionResponse,
    ResumenNotificaciones,
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


# ── Notificaciones personales (NOV-04) ───────────────────────────────────────


@router.get(
    "/notificaciones",
    response_model=NotificacionesPage,
    summary="Listar mis notificaciones",
    description=(
        "Sólo las del usuario de la sesión. Primero las críticas sin leer; después el resto, "
        "de la más nueva a la más vieja."
    ),
    responses=error_responses(401, 422),
)
async def listar_notificaciones(
    solo_no_leidas: bool = Query(False, description="Sólo las que no se leyeron."),
    limit: int = _LIMIT,
    offset: int = _OFFSET,
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificacionesPage:
    items, total = await service.listar_notificaciones(
        db, usuario, solo_no_leidas=solo_no_leidas, limit=limit, offset=offset
    )
    return NotificacionesPage(items=[service.notificacion_a_respuesta(n) for n in items], total=total)


@router.get(
    "/notificaciones/resumen",
    response_model=ResumenNotificaciones,
    summary="Cantidad de notificaciones sin leer",
    description="Lo consulta la campanita cada 60 segundos (D-N04).",
    responses=error_responses(401),
)
async def resumen_notificaciones(
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResumenNotificaciones:
    no_leidas, criticas = await service.resumen_notificaciones(db, usuario)
    return ResumenNotificaciones(no_leidas=no_leidas, criticas_no_leidas=criticas)


@router.patch(
    "/notificaciones/{notificacion_id}/leida",
    response_model=NotificacionResponse,
    summary="Marcar una notificación como leída",
    description="Idempotente: si ya estaba leída, conserva la fecha de la primera lectura.",
    responses=error_responses(401, 404, 422),
)
async def marcar_leida(
    notificacion_id: int,
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificacionResponse:
    notificacion = await service.marcar_leida(db, usuario, notificacion_id)
    await db.commit()
    return service.notificacion_a_respuesta(notificacion)


@router.post(
    "/notificaciones/leer-todas",
    response_model=LeerTodasResponse,
    summary="Marcar todas como leídas",
    description="Marca las de severidad NORMAL. Las críticas se marcan de a una (RN-N9).",
    responses=error_responses(401),
)
async def leer_todas(
    usuario: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeerTodasResponse:
    marcadas = await service.leer_todas(db, usuario)
    await db.commit()
    return LeerTodasResponse(marcadas=marcadas)
