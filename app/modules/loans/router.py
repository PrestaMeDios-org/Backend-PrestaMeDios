"""Endpoints REST del módulo `loans` (Solicitudes y Reservas; SPEC-05 §6).

Todos exigen sesión (Constitución P4.1). Solo firmas: el contrato OpenAPI queda
listo antes de la lógica (API-First); las reglas vivirán en ``service.py``.

Los errores de negocio se lanzan con ``AppError`` (``{detail, code}``) y se
documentan con ``error_responses(...)``. Dónde aparece cada código (§6.3):
  - ``POST /ordenes``: 404 ``EQUIPAMIENTO_NO_ENCONTRADO``; 422 de negocio
    (``LIMITE_DIAS_EXCEDIDO``, ``FRANJA_FUERA_DE_HORARIO``, etc.).
  - ``PATCH /ordenes/{id}/estado``: 409 ``TRANSICION_INVALIDA`` y
    ``UNIDAD_NO_DISPONIBLE`` (la base rechazó un solapamiento, SQLSTATE 23P01).
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError, error_responses
from app.database import get_db
from app.modules.loans.enums import EstadoOrdenEnum
from app.modules.loans.schemas import (
    OrdenPedidoCreate,
    OrdenPedidoEstadoUpdate,
    OrdenPedidoResponse,
)
from app.modules.users.models import Usuario

router = APIRouter()

_solo_solicitantes = require_roles(RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE)
_solo_admins = require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)


def _pendiente() -> AppError:
    return AppError(
        501,
        "NO_IMPLEMENTADO",
        "Endpoint definido por contrato; lógica pendiente.",
    )


# ── Solicitante (estudiante / docente) ───────────────────────────────────────


@router.post(
    "/ordenes",
    response_model=OrdenPedidoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar equipamiento (orden de pedido)",
    responses=error_responses(401, 403, 404, 422),
)
async def crear_orden(
    payload: OrdenPedidoCreate,
    actor: Usuario = Depends(_solo_solicitantes),
    db: AsyncSession = Depends(get_db),
) -> OrdenPedidoResponse:
    """Queda ``pendiente``; solicitante y sede salen de la sesión (PRE-03, 06, 07, 09)."""
    raise _pendiente()


@router.get(
    "/ordenes/mias",
    response_model=list[OrdenPedidoResponse],
    summary="Listar mis órdenes",
    responses=error_responses(401, 403),
)
async def listar_mis_ordenes(
    estado: EstadoOrdenEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Usuario = Depends(_solo_solicitantes),
    db: AsyncSession = Depends(get_db),
) -> list[OrdenPedidoResponse]:
    """Estudiantes y docentes ven solo las propias (P6)."""
    raise _pendiente()


# ── Bandeja administrativa ───────────────────────────────────────────────────


@router.get(
    "/ordenes",
    response_model=list[OrdenPedidoResponse],
    summary="Bandeja de validaciones de la jurisdicción",
    responses=error_responses(401, 403),
)
async def listar_bandeja(
    estado: EstadoOrdenEnum | None = Query(default=EstadoOrdenEnum.PENDIENTE),
    sede: SedeEnum | None = Query(default=None, description="Solo SUPERADMIN."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> list[OrdenPedidoResponse]:
    """El admin local ve solo su sede; el superadmin ve ambas o la filtrada (PRE-15)."""
    raise _pendiente()


@router.get(
    "/ordenes/{orden_id}",
    response_model=OrdenPedidoResponse,
    summary="Detalle de una orden",
    responses=error_responses(401, 404),
)
async def obtener_orden(
    orden_id: int,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrdenPedidoResponse:
    """El alcance (dueño, sede, docente de la asignatura) lo resuelve el servicio."""
    raise _pendiente()


@router.patch(
    "/ordenes/{orden_id}/estado",
    response_model=OrdenPedidoResponse,
    summary="Aprobar, rechazar o cancelar una orden",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def cambiar_estado_orden(
    orden_id: int,
    payload: OrdenPedidoEstadoUpdate,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrdenPedidoResponse:
    """Aprobar o rechazar es administrativo (PRE-10, PRE-18); el solicitante solo cancela la suya.

    Al aprobar se asigna una unidad por línea y se puede ajustar el horario. El
    administrador cancela únicamente órdenes ``aprobada`` de su sede, con motivo
    (libera las unidades, PRE-17). El permiso depende del rol y del estado actual,
    por eso lo decide el servicio.
    """
    raise _pendiente()