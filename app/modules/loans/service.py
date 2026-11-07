"""Servicio del módulo `loans` (SPEC-05, Fase 1: Solicitar).

Las reglas de negocio viven acá y los endpoints delegan en estas funciones.

- Las reglas operativas (franja, anticipación, plazos) se leen de `config` con
  ``obtener_parametro``; no se codifican (Constitución P8, RN-L28).
- Las fechas se comparan en la zona horaria del laboratorio (RN-L29).
- Todo error de negocio es un ``AppError`` (``{detail, code}``).
- ``get_db`` no hace ``commit``: lo hace el servicio cuando escribe.
"""

from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.config.service import obtener_parametro
from app.modules.loans.enums import EstadoOrdenEnum
from app.modules.loans.models import OrdenPedido
from app.modules.loans.schemas import ReglasResponse
from app.modules.users.models import Usuario

# ── Lectura de parámetros ────────────────────────────────────────────────────


async def _entero(db: AsyncSession, clave: str) -> int:
    valor = await obtener_parametro(db, clave)
    assert isinstance(valor, int) and not isinstance(valor, bool), f"{clave} no es entero"
    return valor


async def _hora(db: AsyncSession, clave: str) -> time:
    valor = await obtener_parametro(db, clave)
    assert isinstance(valor, time), f"{clave} no es una hora"
    return valor


async def reglas(db: AsyncSession) -> ReglasResponse:
    """Reglas operativas vigentes, para que el formulario las conozca (D-L07)."""
    return ReglasResponse(
        horario_apertura=await _hora(db, "horario.apertura"),
        horario_cierre=await _hora(db, "horario.cierre"),
        anticipacion_min_horas=await _entero(db, "solicitud.anticipacion_min_horas"),
        max_dias_general=await _entero(db, "prestamo.general.max_dias"),
        max_dias_notebook=await _entero(db, "prestamo.notebook.max_dias"),
        tolerancia_retiro_horas=await _entero(db, "prestamo.tolerancia_retiro_horas"),
    )


# ── Consulta del solicitante ─────────────────────────────────────────────────


def orden_no_encontrada() -> AppError:
    return AppError(404, "ORDEN_NO_ENCONTRADA", "Orden no encontrada.")


async def listar_mis_ordenes(
    db: AsyncSession,
    actor: Usuario,
    estado: EstadoOrdenEnum | None,
    limit: int,
    offset: int,
) -> list[OrdenPedido]:
    """Órdenes del usuario autenticado, de la más nueva a la más vieja (P6)."""
    stmt = select(OrdenPedido).where(OrdenPedido.solicitante_id == actor.id)
    if estado is not None:
        stmt = stmt.where(OrdenPedido.estado == estado)
    stmt = (
        stmt.order_by(OrdenPedido.fecha_solicitud.desc(), OrdenPedido.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await db.scalars(stmt)).all())


async def obtener_orden(db: AsyncSession, actor: Usuario, orden_id: int) -> OrdenPedido:
    """Detalle de una orden. En la Fase 1 solo la ve su dueño; para el resto, 404 (P6)."""
    stmt = select(OrdenPedido).where(
        OrdenPedido.id == orden_id, OrdenPedido.solicitante_id == actor.id
    )
    orden = await db.scalar(stmt)
    if orden is None:
        raise orden_no_encontrada()
    return orden
