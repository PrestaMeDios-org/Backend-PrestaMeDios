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
    BloqueoEspacioResponse,
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
) -> list[ReservaEspacio]:
    """Estudiantes y docentes ven sólo las propias (RN-30)."""
    return await service.listar_reservas(
        db, actor, id_espacio=id_espacio, fecha=fecha, estado=estado,
        id_usuario=id_usuario, sede=sede,
    )


@router.patch(
    "/reservas/{id_reserva}/estado",
    response_model=ReservaEspacioResponse,
    summary="Aprobar, rechazar, cancelar, registrar uso o finalizar una reserva",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def actualizar_estado_reserva(
    id_reserva: int,
    payload: ReservaEspacioUpdateStatus,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReservaEspacio:
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
    return await service.listar_bloqueos(db, actor, id_espacio=id_espacio, fecha=fecha)


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
