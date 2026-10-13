"""Endpoints REST del módulo `loans` (Solicitudes y Reservas).

Solo firmas: el contrato OpenAPI queda listo antes de la lógica (API-First).
La lógica irá en ``services.py`` y estos handlers delegarán en ella.

"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.loans.dependencies import UsuarioActual, get_usuario_actual
from app.modules.loans.enums import EstadoOrdenEnum
from app.modules.loans.schemas import (
    ErrorConflictoReserva,
    ErrorLimiteDias,
    OrdenPedidoCancelacion,
    OrdenPedidoCreate,
    OrdenPedidoResolucion,
    OrdenPedidoResponse,
)

router = APIRouter()

_NO_ENCONTRADA = {status.HTTP_404_NOT_FOUND: {"description": "Orden no encontrada."}}
_SIN_PERMISO = {
    status.HTTP_403_FORBIDDEN: {"description": "El rol o la sede del usuario no permite la acción."}
}


def _pendiente() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Endpoint definido por contrato; lógica pendiente.",
    )


# ---------------------------------------------------------------------------
# Solicitante (estudiante / docente)
# ---------------------------------------------------------------------------
@router.post(
    "/ordenes",
    response_model=OrdenPedidoResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorLimiteDias,
            "description": "Rango fuera del límite del ítem, o faltan asignatura / PDF.",
        },
    },
)
async def crear_orden(
    payload: OrdenPedidoCreate,
    db: AsyncSession = Depends(get_db),
    usuario: UsuarioActual = Depends(get_usuario_actual),
) -> OrdenPedidoResponse:
    """Genera la orden unificada en estado ``pendiente`` (PRE-03, PRE-06, PRE-07)."""
    raise _pendiente()


@router.get("/ordenes/mias", response_model=list[OrdenPedidoResponse])
async def listar_mis_ordenes(
    estado: EstadoOrdenEnum | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    usuario: UsuarioActual = Depends(get_usuario_actual),
) -> list[OrdenPedidoResponse]:
    """Órdenes del usuario autenticado."""
    raise _pendiente()


@router.patch(
    "/ordenes/{orden_id}/cancelacion",
    response_model=OrdenPedidoResponse,
    responses={**_NO_ENCONTRADA, **_SIN_PERMISO},
)
async def cancelar_orden(
    orden_id: int,
    payload: OrdenPedidoCancelacion,
    db: AsyncSession = Depends(get_db),
    usuario: UsuarioActual = Depends(get_usuario_actual),
) -> OrdenPedidoResponse:
    """Cancela una orden.

    - Solicitante: solo la propia y solo si está ``pendiente``.
    - Administrador: solo de su sede y solo si está ``aprobada`` (libera la unidad).
    """
    raise _pendiente()


# ---------------------------------------------------------------------------
# Bandeja administrativa
# ---------------------------------------------------------------------------
@router.get("/ordenes", response_model=list[OrdenPedidoResponse], responses=_SIN_PERMISO)
async def listar_bandeja(
    estado: EstadoOrdenEnum | None = Query(default=EstadoOrdenEnum.PENDIENTE),
    db: AsyncSession = Depends(get_db),
    usuario: UsuarioActual = Depends(get_usuario_actual),
) -> list[OrdenPedidoResponse]:
    """Bandeja de validaciones (PRE-15).

    Filtra por la sede del administrador; el superadministrador ve todas.
    """
    raise _pendiente()


@router.get(
    "/ordenes/{orden_id}",
    response_model=OrdenPedidoResponse,
    responses={**_NO_ENCONTRADA, **_SIN_PERMISO},
)
async def obtener_orden(
    orden_id: int,
    db: AsyncSession = Depends(get_db),
    usuario: UsuarioActual = Depends(get_usuario_actual),
) -> OrdenPedidoResponse:
    raise _pendiente()


@router.patch(
    "/ordenes/{orden_id}/resolucion",
    response_model=OrdenPedidoResponse,
    responses={
        **_NO_ENCONTRADA,
        **_SIN_PERMISO,
        status.HTTP_409_CONFLICT: {
            "model": ErrorConflictoReserva,
            "description": "La unidad asignada se solapa con otra reserva activa.",
        },
    },
)
async def resolver_orden(
    orden_id: int,
    payload: OrdenPedidoResolucion,
    db: AsyncSession = Depends(get_db),
    usuario: UsuarioActual = Depends(get_usuario_actual),
) -> OrdenPedidoResponse:
    """Aprueba (asignando una unidad por línea) o rechaza una orden pendiente (PRE-18)."""
    raise _pendiente()