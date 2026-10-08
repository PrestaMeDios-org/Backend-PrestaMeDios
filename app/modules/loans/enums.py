"""Enums de dominio del módulo `loans`.

Viven en su propio archivo para que ``models.py`` (persistencia) y
``schemas.py`` (contrato HTTP) dependan de ellos sin depender entre sí.
"""

from enum import StrEnum


class EstadoOrdenEnum(StrEnum):
    """Estado de una orden de pedido dentro del flujo de validación."""

    PENDIENTE = "pendiente"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    CANCELADA = "cancelada"


class EstadoDetalleEnum(StrEnum):
    """Ciclo de vida de una línea de la orden y su efecto sobre la unidad.

    Ocupan la unidad física (entran en la Exclusion Constraint):
    ``RESERVADO`` y ``ENTREGADO``. El resto la libera, y el valor
    conserva el motivo para el historial.
    """

    PENDIENTE = "pendiente"
    RESERVADO = "reservado"
    ENTREGADO = "entregado"
    DEVUELTO = "devuelto"
    RECHAZADO = "rechazado"
    NO_RETIRADO = "no_retirado"
    CANCELADO = "cancelado"


ESTADOS_DETALLE_QUE_OCUPAN = (
    EstadoDetalleEnum.RESERVADO,
    EstadoDetalleEnum.ENTREGADO,
)