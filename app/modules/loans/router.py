"""Endpoints REST del módulo `loans` (Solicitudes y Reservas; SPEC-05 §6).

Todos exigen sesión (Constitución P4.1). Solo firmas: el contrato OpenAPI queda
listo antes de la lógica (API-First); las reglas vivirán en ``service.py``.

Los errores de negocio se lanzan con ``AppError`` (``{detail, code}``) y se
documentan con ``error_responses(...)``. Dónde aparece cada código (§6.3):
  - ``POST /ordenes``: 404 ``EQUIPAMIENTO_NO_ENCONTRADO``; 409
    ``EQUIPAMIENTO_NO_DISPONIBLE`` (sin unidades libres en el período); 422 de
    negocio (``LIMITE_DIAS_EXCEDIDO``, ``FRANJA_FUERA_DE_HORARIO``, etc.).
  - ``PATCH /ordenes/{id}/estado``: 409 ``TRANSICION_INVALIDA`` y
    ``UNIDAD_NO_DISPONIBLE`` (la base rechazó un solapamiento, SQLSTATE 23P01).
"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import error_responses
from app.database import get_db
from app.modules.files.service import respuesta_descarga
from app.modules.loans import service
from app.modules.loans.enums import EstadoOrdenEnum
from app.modules.loans.models import OrdenPedido
from app.modules.loans.schemas import (
    LineaUnidadesLibresResponse,
    OrdenPedidoCreate,
    OrdenPedidoEstadoUpdate,
    OrdenPedidoResponse,
    ReglasResponse,
)
from app.modules.users.models import Usuario

router = APIRouter()

_solo_solicitantes = require_roles(RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE)
_solo_admins = require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)


# ── Reglas operativas ────────────────────────────────────────────────────────


@router.get(
    "/reglas",
    response_model=ReglasResponse,
    summary="Reglas operativas vigentes",
    responses=error_responses(401),
)
async def consultar_reglas(
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReglasResponse:
    """Horario, anticipación y plazos vigentes, para armar el formulario (PRE-06, PRE-07)."""
    return await service.reglas(db)


# ── Solicitante (estudiante / docente) ───────────────────────────────────────


@router.post(
    "/ordenes",
    response_model=OrdenPedidoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar equipamiento (orden de pedido)",
    responses=error_responses(401, 403, 404, 409, 422),
)
async def crear_orden(
    payload: OrdenPedidoCreate,
    actor: Usuario = Depends(_solo_solicitantes),
    db: AsyncSession = Depends(get_db),
) -> OrdenPedido:
    """Queda ``pendiente``; solicitante y sede salen de la sesión (PRE-03, 06, 07, 09).

    Las renovaciones responden ``501``: todavía no se implementan.
    """
    return await service.crear_orden(db, actor, payload)


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
) -> list[OrdenPedido]:
    """Estudiantes y docentes ven solo las propias (P6)."""
    return await service.listar_mis_ordenes(db, actor, estado, limit, offset)


# ── Bandeja administrativa ───────────────────────────────────────────────────


@router.get(
    "/ordenes",
    response_model=list[OrdenPedidoResponse],
    summary="Bandeja de validaciones de la jurisdicción",
    responses=error_responses(401, 403),
)
async def listar_bandeja(
    estado: EstadoOrdenEnum = Query(default=EstadoOrdenEnum.PENDIENTE),
    sede: SedeEnum | None = Query(
        default=None,
        description="Solo SUPERADMIN. Un ADMIN_LOCAL que pide otra sede recibe 403.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> list[OrdenPedidoResponse]:
    """El admin local ve solo su sede; el superadmin ve ambas o la filtrada (PRE-15).

    Por defecto, las pendientes, de la más vieja a la más nueva, con nombre y apellido
    del solicitante (P6).
    """
    return await service.listar_bandeja(db, actor, estado, sede, limit, offset)


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
    """Lo ven el dueño y los administradores con jurisdicción sobre la sede de la orden.

    Para los administradores incluye nombre y apellido del solicitante (P6). Fuera de
    alcance responde 404, nunca 403. El docente de la asignatura llega en la Fase 4.
    """
    return await service.obtener_orden(db, actor, orden_id)


@router.get(
    "/ordenes/{orden_id}/unidades-libres",
    response_model=list[LineaUnidadesLibresResponse],
    summary="Unidades libres por línea, para asignar al aprobar",
    responses=error_responses(401, 403, 404),
)
async def unidades_libres_de_orden(
    orden_id: int,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> list[LineaUnidadesLibresResponse]:
    """Por cada línea, las unidades del modelo en la sede de la orden que están
    ``disponible`` y sin otra reserva que se solape con su período (PRE-10, RN-L12).

    Devuelve solo ids; el código de inventario sale del stock de ``inventory``. Fuera
    de la jurisdicción del administrador responde 404.
    """
    return await service.unidades_libres_de_orden(db, actor, orden_id)


@router.get(
    "/ordenes/{orden_id}/aval",
    response_class=Response,
    summary="Descargar el PDF de aval de la orden",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "El PDF de aval."},
        **error_responses(401, 404),
    },
)
async def descargar_aval(
    orden_id: int,
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """El aval de alta gama (PRE-05), para el solicitante y los administradores con
    jurisdicción, que lo revisan antes de aprobar (RN-60 de SPEC-03).

    Cualquier otro caso, incluido el docente de la asignatura, responde 404; también
    una orden sin aval. Se sirve con los encabezados comunes de ``files`` (RN-61).
    """
    contenido = await service.descargar_aval(db, actor, orden_id)
    return respuesta_descarga(contenido)


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
    return await service.cambiar_estado_orden(db, actor, orden_id, payload)
