"""Enums del módulo `files` (SPEC-03 §6.2).

Valores en MAYÚSCULAS, como los de `core` (DT-19).
"""

from enum import StrEnum


class PropositoArchivo(StrEnum):
    """Para qué se sube un archivo: decide tipos, tamaño y quién lo descarga (RN-60)."""

    FOTO_PERFIL = "FOTO_PERFIL"  # USR-03
    AVAL_PRESTAMO = "AVAL_PRESTAMO"  # PRE-05: resolución del Consejo (CICSE/ICSE)
