"""Servicio del módulo `loans` (SPEC-05, Fase 1: Solicitar).

Las reglas de negocio viven acá y los endpoints delegan en estas funciones.

- Las reglas operativas (franja, anticipación, plazos) se leen de `config` con
  ``obtener_parametro``; no se codifican (Constitución P8, RN-L28).
- Las fechas se comparan en la zona horaria del laboratorio (RN-L29).
- Todo error de negocio es un ``AppError`` (``{detail, code}``).
- ``get_db`` no hace ``commit``: lo hace el servicio cuando escribe.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB
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


# ── Validaciones puras (sin base de datos) ───────────────────────────────────


def _a_hora_lab(instante: datetime) -> datetime:
    """Convierte un instante con zona a la zona del laboratorio (RN-L29)."""
    return instante.astimezone(ZONA_HORARIA_LAB)


def _validar_franja(retiro: datetime, devolucion: datetime, apertura: time, cierre: time) -> None:
    """RN-L04: la hora local de retiro y de devolución está dentro de la franja (inclusive)."""
    etiquetas = {"retiro": "retiro", "devolucion": "devolución"}
    for campo, instante in (("retiro", retiro), ("devolucion", devolucion)):
        hora = _a_hora_lab(instante).time()
        if not apertura <= hora <= cierre:
            raise AppError(
                422,
                "FRANJA_FUERA_DE_HORARIO",
                f"La hora de {etiquetas[campo]} debe estar entre las "
                f"{apertura:%H:%M} y las {cierre:%H:%M}.",
                campo=campo,
            )


def _validar_anticipacion(retiro: datetime, ahora: datetime, horas: int) -> None:
    """RN-L05: el retiro se pide con al menos ``horas`` de anticipación."""
    if retiro < ahora + timedelta(hours=horas):
        raise AppError(
            422,
            "ANTICIPACION_INSUFICIENTE",
            f"El retiro debe pedirse con al menos {horas} horas de anticipación.",
            anticipacion_min_horas=horas,
        )


def _dias_corridos(retiro: datetime, devolucion: datetime) -> int:
    """RN-L06: días corridos contando el día de retiro y el de devolución (D-L04)."""
    return (_a_hora_lab(devolucion).date() - _a_hora_lab(retiro).date()).days + 1


def _limite_dias(
    es_notebook: bool, max_general: int, max_notebook: int, max_item: int | None
) -> int:
    """RN-L06 (D-L03): el menor entre el parámetro del tipo y el máximo del ítem."""
    por_tipo = max_notebook if es_notebook else max_general
    return por_tipo if max_item is None else min(por_tipo, max_item)


def _validar_plazo(
    retiro: datetime, devolucion: datetime, limite: int, equipamiento_id: int
) -> None:
    """RN-L06: el rango no supera el límite de la línea."""
    if _dias_corridos(retiro, devolucion) > limite:
        raise AppError(
            422,
            "LIMITE_DIAS_EXCEDIDO",
            f"El plazo máximo para este equipo es de {limite} días.",
            equipamiento_id=equipamiento_id,
            max_dias=limite,
        )
