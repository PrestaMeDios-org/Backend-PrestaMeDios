"""Endpoints REST del módulo `spaces` (Subsistema 3: Reserva de Espacios; SPEC-02 §3.2).

Todos exigen sesión (RN-24). Las reglas viven en ``service.py``.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import error_responses
from app.database import get_db
from app.modules.spaces import service
from app.modules.spaces.models import BloqueoEspacio, Espacio, ReservaEspacio
from app.modules.spaces.schemas import (
    BloqueoEspacioCreate,
    BloqueoEspacioGeneralCreate,
    BloqueoEspacioResponse,
    BloqueoEspacioUpdateStatus,
    DisponibilidadResponse,
    EspacioCreate,
    EspacioResponse,
    EstadoReserva,
    ReservaEspacioCreate,
    ReservaEspacioResponse,
    ReservaEspacioUpdateStatus,
)
from app.modules.users.models import Usuario

router = APIRouter()

_solo_admins = require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)


# ── Espacios ─────────────────────────────────────────────────────────────────


@router.get(
    "/espacios",
    response_model=list[EspacioResponse],
    summary="Listar espacios de la sede",
    responses=error_responses(401, 403),
)
async def listar_espacios(
    sede: SedeEnum | None = Query(default=None),
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Espacio]:
    """Sólo la sede del usuario; el Superadministrador ve ambas o la filtrada (GLO-01)."""
    return await service.listar_espacios(db, actor, sede)


@router.post(
    "/espacios",
    response_model=EspacioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de espacio reservable",
    responses=error_responses(401, 403, 422),
)
async def crear_espacio(
    payload: EspacioCreate,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> Espacio:
    """La sede se asigna automáticamente para administradores locales (PRE-19)."""
    return await service.crear_espacio(db, actor, payload)


# ── Reservas ─────────────────────────────────────────────────────────────────


@router.post(
    "/reservas",
    response_model=ReservaEspacioResponse,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar una reserva",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def crear_reserva(
    payload: ReservaEspacioCreate,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservaEspacio:
    """Queda en ``Pendiente``; el solicitante es el usuario autenticado (RES-02, RN-25)."""
    return await service.crear_reserva(db, actor, payload)


@router.get(
    "/reservas",
    response_model=list[ReservaEspacioResponse],
    response_model_exclude_unset=True,
    summary="Listar reservas (propias o de la jurisdicción)",
    responses=error_responses(401, 403),
)
async def listar_reservas(
    id_espacio: int | None = Query(default=None),
    fecha: date | None = Query(default=None),
    estado: EstadoReserva | None = Query(default=None),
    id_usuario: int | None = Query(default=None, description="Sólo administradores."),
    sede: SedeEnum | None = Query(default=None, description="Sólo administradores."),
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReservaEspacioResponse]:
    """Estudiantes y docentes ven sólo las propias (RES-03, RN-30). Para un administrador
    con jurisdicción se suman nombre y apellido del solicitante (SPEC-08 AC-S14, P6)."""
    return await service.listar_reservas(
        db, actor, id_espacio=id_espacio, fecha=fecha, estado=estado,
        id_usuario=id_usuario, sede=sede,
    )


@router.patch(
    "/reservas/{id_reserva}/estado",
    response_model=ReservaEspacioResponse,
    response_model_exclude_unset=True,
    summary="Aprobar, rechazar, cancelar, registrar uso o finalizar una reserva",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def actualizar_estado_reserva(
    id_reserva: int,
    payload: ReservaEspacioUpdateStatus,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservaEspacioResponse:
    """El dueño puede cancelar (RES-03); el resto de las transiciones son administrativas (RES-05)."""
    return await service.cambiar_estado_reserva(db, actor, id_reserva, payload)


# ── Bloqueos (RES-04 / GLO-04) ───────────────────────────────────────────────


@router.post(
    "/bloqueos",
    response_model=BloqueoEspacioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bloquear un espacio",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def crear_bloqueo(
    payload: BloqueoEspacioCreate,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> BloqueoEspacio:
    return await service.crear_bloqueo(db, actor, payload)


@router.post(
    "/bloqueos/general",
    response_model=list[BloqueoEspacioResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Bloquear espacios de ambas sedes",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def crear_bloqueo_general(
    payload: BloqueoEspacioGeneralCreate,
    actor: Usuario = Depends(require_roles(RolUsuario.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[BloqueoEspacio]:
    """Sólo el Superadministrador: una fila por espacio de ambas sedes, con el mismo
    ``id_grupo``; si un espacio no se puede bloquear, no se crea ninguna (GLO-04, AC-S15)."""
    return await service.crear_bloqueo_general(db, actor, payload)


@router.get(
    "/bloqueos",
    response_model=list[BloqueoEspacioResponse],
    summary="Listar bloqueos",
    responses=error_responses(401),
)
async def listar_bloqueos(
    id_espacio: int | None = Query(default=None),
    fecha: date | None = Query(default=None),
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BloqueoEspacio]:
    """Activos y revertidos, con su ``estado`` (SPEC-08 RN-S14)."""
    return await service.listar_bloqueos(db, actor, id_espacio=id_espacio, fecha=fecha)


@router.patch(
    "/bloqueos/{id_bloqueo}/estado",
    response_model=BloqueoEspacioResponse | list[BloqueoEspacioResponse],
    summary="Deshacer un bloqueo",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def revertir_bloqueo(
    id_bloqueo: int,
    payload: BloqueoEspacioUpdateStatus,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> BloqueoEspacio | list[BloqueoEspacio]:
    """Deshace un bloqueo sin borrarlo: queda ``Revertido`` con quién y cuándo (GLO-04,
    SPEC-08 AC-S16). Un ADMIN_LOCAL revierte sólo bloqueos individuales de su sede; una
    fila de un bloqueo general la revierte sólo el SUPERADMIN, y se revierte el grupo
    entero (la respuesta es la lista de filas). Las reservas existentes no cambian."""
    return await service.revertir_bloqueo(db, actor, id_bloqueo, payload)


# ── Disponibilidad (RES-01) ──────────────────────────────────────────────────


@router.get(
    "/disponibilidad",
    response_model=DisponibilidadResponse,
    summary="Disponibilidad de espacios en una fecha",
    responses=error_responses(401, 403),
)
async def consultar_disponibilidad(
    fecha: date = Query(...),
    sede: SedeEnum | None = Query(default=None),
    id_espacio: int | None = Query(default=None),
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DisponibilidadResponse:
    """Franjas ocupadas sin identidad de solicitantes, bloqueos, horario e intervalos libres."""
    return await service.disponibilidad(db, actor, fecha=fecha, sede=sede, id_espacio=id_espacio)
