"""Dependencias de FastAPI del módulo `loans`.

PLACEHOLDER: el dominio `users` todavía no existe en el repo. Cuando esté,
`get_usuario_actual` debe delegar en su dependencia de sesión (vía
``Depends``, sin importar sus modelos SQL) y ``UsuarioActual`` se reemplaza
por el contrato que defina ese dominio.
"""

from enum import StrEnum

from pydantic import BaseModel


class RolEnum(StrEnum):
    ESTUDIANTE = "estudiante"
    DOCENTE = "docente"
    ADMINISTRADOR = "administrador"
    SUPERADMINISTRADOR = "superadministrador"


class UsuarioActual(BaseModel):
    """Datos de la sesión que `loans` necesita: quién, con qué rol y en qué sede."""

    id: int
    rol: RolEnum
    sede: str


async def get_usuario_actual() -> UsuarioActual:
    raise NotImplementedError("Pendiente: integrar con el dominio `users`.")