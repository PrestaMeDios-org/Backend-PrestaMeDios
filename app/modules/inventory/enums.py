"""Enums de dominio del módulo `inventory`.

Viven en su propio archivo para que ``models.py`` (persistencia) y
``schemas.py`` (contrato HTTP) dependan de ellos sin depender entre sí.
"""

from enum import StrEnum


class SedeEnum(StrEnum):
    """Sedes físicas donde se aloja el equipamiento."""

    USHUAIA = "Ushuaia"
    RIO_GRANDE = "Río Grande"


class EstadoUnidadEnum(StrEnum):
    """Ciclo de vida de una unidad física dentro del inventario."""

    DISPONIBLE = "disponible"
    PRESTADO = "prestado"
    MANTENIMIENTO = "mantenimiento"
    BAJA = "baja"
