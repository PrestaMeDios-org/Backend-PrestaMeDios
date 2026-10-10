"""Dependencias de autenticación y autorización para todos los módulos (SPEC-01 §6.2, §12.1).

Uso típico en un router::

    @router.post("/...", dependencies=[Depends(require_roles(RolUsuario.ADMIN_LOCAL,
                                                             RolUsuario.SUPERADMIN))])

    async def endpoint(usuario: Usuario = Depends(get_current_user)): ...

La autorización usa SIEMPRE los datos vigentes en base de datos; ``rol`` y
``sede`` del token son sólo informativos para el frontend.
"""

from collections.abc import Awaitable, Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.security import decodificar_token, token_invalido
from app.database import get_db
from app.modules.users.models import Usuario

bearer_scheme = HTTPBearer(auto_error=False, description="Access token JWT (SPEC-01 §6.2).")

_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


async def _usuario_autenticado(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> Usuario:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "NO_AUTENTICADO", "Se requiere iniciar sesión.", headers=_WWW_AUTH)

    payload = decodificar_token(credentials.credentials)

    usuario = await db.get(Usuario, payload.sub)
    if usuario is None:
        raise token_invalido()
    if usuario.token_version != payload.tv or usuario.estado != EstadoCuenta.ACTIVO:
        raise AppError(
            401,
            "TOKEN_REVOCADO",
            "La sesión fue cerrada por un cambio en tu cuenta.",
            headers=_WWW_AUTH,
        )
    return usuario


async def get_current_user_permitiendo_cambio(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Usuario autenticado aunque tenga pendiente el cambio obligatorio de contraseña.

    Sólo para ``GET /auth/me`` y ``POST /auth/me/password`` (SPEC-02 RN-33).
    """
    return await _usuario_autenticado(credentials, db)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Usuario:
    """Resuelve el usuario autenticado y activo a partir del header ``Authorization``.

    Bloquea a quien deba cambiar su contraseña (SPEC-02 RN-33): así ningún
    endpoint protegido puede olvidar esa regla.
    """
    usuario = await _usuario_autenticado(credentials, db)
    if usuario.debe_cambiar_password:
        raise AppError(
            403,
            "CAMBIO_PASSWORD_REQUERIDO",
            "Tenés que cambiar tu contraseña antes de continuar.",
        )
    return usuario


def require_roles(*roles: RolUsuario) -> Callable[..., Awaitable[Usuario]]:
    """Dependencia que exige que el usuario autenticado tenga alguno de ``roles``."""
    permitidos = frozenset(roles)

    async def _verificar(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.rol not in permitidos:
            raise permiso_insuficiente()
        return usuario

    return _verificar


def permiso_insuficiente() -> AppError:
    return AppError(403, "PERMISO_INSUFICIENTE", "No tenés permisos para realizar esta acción.")


def resolver_alcance_sede(usuario: Usuario, sede_solicitada: SedeEnum | None) -> list[SedeEnum]:
    """Sedes sobre las que ``usuario`` puede operar en esta consulta (RN-10, GLO-01).

    - ``SUPERADMIN``: la sede solicitada o, si no indica, ambas.
    - Resto de los roles: siempre su propia sede; pedir otra explícitamente
      responde ``403 SEDE_FUERA_DE_ALCANCE``.
    """
    if usuario.rol == RolUsuario.SUPERADMIN:
        return [sede_solicitada] if sede_solicitada is not None else list(SedeEnum)

    assert usuario.sede is not None  # garantizado por CHECK ck_usuarios_sede_segun_rol
    if sede_solicitada is not None and sede_solicitada != usuario.sede:
        raise AppError(
            403, "SEDE_FUERA_DE_ALCANCE", "No tenés jurisdicción sobre la sede solicitada."
        )
    return [usuario.sede]


def sede_para_alta(usuario: Usuario, sede_indicada: SedeEnum | None) -> SedeEnum:
    """Sede de un recurso nuevo (PRE-19, SPEC-02 §2, RN-31).

    - ``ADMIN_LOCAL``: su sede; indicar otra responde ``403 SEDE_FUERA_DE_ALCANCE``.
    - ``SUPERADMIN``: obligatoria (``422 SEDE_REQUERIDA``).
    """
    if usuario.rol == RolUsuario.SUPERADMIN:
        if sede_indicada is None:
            raise AppError(422, "SEDE_REQUERIDA", "Indicá la sede del recurso.")
        return sede_indicada
    assert usuario.sede is not None
    if sede_indicada is not None and sede_indicada != usuario.sede:
        raise AppError(
            403, "SEDE_FUERA_DE_ALCANCE", "No tenés jurisdicción sobre la sede solicitada."
        )
    return usuario.sede


def puede_ver_sede(usuario: Usuario, sede: SedeEnum | None) -> bool:
    """¿El recurso de ``sede`` está dentro de la jurisdicción de ``usuario``?"""
    return usuario.rol == RolUsuario.SUPERADMIN or (sede is not None and sede == usuario.sede)
