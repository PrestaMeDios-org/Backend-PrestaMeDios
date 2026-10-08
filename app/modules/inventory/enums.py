"""Enums de dominio del módulo `inventory`.

Viven en su propio archivo para que ``models.py`` (persistencia) y
``schemas.py`` (contrato HTTP) dependan de ellos sin depender entre sí.
"""

from enum import StrEnum

# Re-export: la definición canónica de sede vive en `app.core.enums` (SPEC-01, D-01).
from app.core.enums import SedeEnum  # noqa: F401


class EstadoUnidadEnum(StrEnum):
    """Ciclo de vida de una unidad física dentro del inventario."""

    DISPONIBLE = "disponible"
    PRESTADO = "prestado"
    MANTENIMIENTO = "mantenimiento"
    BAJA = "baja"
