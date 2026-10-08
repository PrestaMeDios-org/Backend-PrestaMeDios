"""Hash de contraseñas (Argon2id) y tokens JWT (SPEC-01 §6.2, RN-03, RN-06, NFR-01).

Nunca registrar en logs contraseñas, hashes ni tokens (NFR-02).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import JWT_ALGORITHM, JWT_ISSUER, get_settings

_password_hash = PasswordHash((Argon2Hasher(),))

JWT_LEEWAY_SECONDS = 30
_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


# ── Contraseñas ──────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Devuelve el hash Argon2id (formato PHC) de ``password``."""
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Verifica en tiempo constante. Devuelve ``(valida, nuevo_hash | None)``.

    ``nuevo_hash`` se informa cuando el hash usa parámetros obsoletos y debe
    regenerarse de forma transparente (NFR-01).
    """
    try:
        return _password_hash.verify_and_update(password, password_hash)
    except Exception:  # hash corrupto o de formato desconocido
        return False, None


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


def verify_dummy(password: str) -> None:
    """Iguala el tiempo de respuesta cuando el email no existe (RN-06)."""
    verify_password(password, _dummy_hash())


# ── JWT ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TokenPayload:
    sub: int
    tv: int


def crear_access_token(
    *, usuario_id: int, rol: RolUsuario, sede: SedeEnum | None, token_version: int
) -> tuple[str, int]:
    """Emite un access token. Devuelve ``(token, expires_in_segundos)``."""
    settings = get_settings()
    ahora = datetime.now(UTC)
    expires_in = settings.jwt_access_token_expire_minutes * 60
    claims = {
        "sub": str(usuario_id),
        "rol": rol.value,
        "sede": sede.value if sede is not None else None,
        "tv": token_version,
        "iss": JWT_ISSUER,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(seconds=expires_in)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=JWT_ALGORITHM)
    return token, expires_in


def decodificar_token(token: str) -> TokenPayload:
    """Valida firma, algoritmo, emisor y expiración (§6.2, pasos 2–3)."""
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            leeway=JWT_LEEWAY_SECONDS,
            options={"require": ["sub", "tv", "iss", "iat", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            401, "TOKEN_EXPIRADO", "La sesión expiró. Iniciá sesión nuevamente.", headers=_WWW_AUTH
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise token_invalido() from exc

    try:
        return TokenPayload(sub=int(claims["sub"]), tv=int(claims["tv"]))
    except (TypeError, ValueError) as exc:
        raise token_invalido() from exc


def token_invalido() -> AppError:
    return AppError(
        401, "TOKEN_INVALIDO", "La sesión no es válida. Iniciá sesión nuevamente.", headers=_WWW_AUTH
    )
