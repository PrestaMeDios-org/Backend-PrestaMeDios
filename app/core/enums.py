"""Enums transversales del dominio (SPEC-01 §3.1, decisión D-01).

``SedeEnum`` es la representación canónica de sede para todos los módulos.
"Ambas sedes" NO es un valor: se representa con ``sede = None`` y es
exclusivo del rol ``SUPERADMIN`` (GLO-01).
"""

from enum import Enum, StrEnum


def enum_values(enum_cls: type[Enum]) -> list[str]:
    """Persiste los *valores* de dominio del enum en lugar de los nombres de miembro."""
    return [member.value for member in enum_cls]


class SedeEnum(StrEnum):
    """Sedes físicas del Laboratorio de Medios Audiovisuales."""

    USHUAIA = "Ushuaia"
    RIO_GRANDE = "Río Grande"


class RolUsuario(StrEnum):
    """Roles del sistema (ADR-001). El rol "Administrador ICSE" no existe."""

    SUPERADMIN = "SUPERADMIN"
    ADMIN_LOCAL = "ADMIN_LOCAL"
    DOCENTE = "DOCENTE"
    ESTUDIANTE = "ESTUDIANTE"


ROLES_ADMIN: frozenset[RolUsuario] = frozenset({RolUsuario.SUPERADMIN, RolUsuario.ADMIN_LOCAL})


class EstadoCuenta(StrEnum):
    """Ciclo de vida de una cuenta de usuario (SPEC-01 §3.2)."""

    PENDIENTE_APROBACION = "PENDIENTE_APROBACION"
    ACTIVO = "ACTIVO"
    RECHAZADO = "RECHAZADO"
    SUSPENDIDO = "SUSPENDIDO"
    INACTIVO = "INACTIVO"


class TipoParametro(StrEnum):
    """Tipos admitidos en el Panel de Parámetros Globales (GLO-03)."""

    ENTERO = "ENTERO"
    DECIMAL = "DECIMAL"
    BOOLEANO = "BOOLEANO"
    TEXTO = "TEXTO"
    HORA = "HORA"
