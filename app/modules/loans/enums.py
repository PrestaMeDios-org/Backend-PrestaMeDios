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


class SituacionOrdenEnum(StrEnum):
    """Situación derivada de la orden (RN-L31, D-L19). No se guarda.

    Separa, dentro de un mismo estado (por ejemplo ``aprobada``), las órdenes
    que siguen en curso de las que ya terminaron.
    """

    EN_CURSO = "en_curso"
    FINALIZADA = "finalizada"


# Una orden sigue en curso mientras alguna línea esté en uno de estos estados.
ESTADOS_DETALLE_EN_CURSO = (
    EstadoDetalleEnum.PENDIENTE,
    EstadoDetalleEnum.RESERVADO,
    EstadoDetalleEnum.ENTREGADO,
)
