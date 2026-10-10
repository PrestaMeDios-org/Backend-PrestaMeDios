"""Contratos API (API-First) del módulo `users` (SPEC-01 §6.4–6.11).

- Entradas estrictas: ``extra="forbid"`` y trim (protección contra *mass assignment*).
- Salidas: ``from_attributes=True`` para serializar modelos ORM.
- ``password_hash`` nunca forma parte de ninguna respuesta (NFR-02).
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum

_INPUT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)

# `[0-9]` en lugar de `\d`: el motor de regex de Pydantic es Unicode-aware.
NombrePersona = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=r"^\p{L}[\p{L}' \-]*$", examples=["Lucía"]),
]
Dni = Annotated[str, Field(pattern=r"^[0-9]{7,8}$", examples=["40123456"])]
Telefono = Annotated[str, Field(pattern=r"^\+?[0-9 \-]{6,20}$", examples=["+54 2901 555123"])]
Password = Annotated[str, Field(min_length=8, max_length=128, examples=["Camara2026!"])]
Motivo = Annotated[str, Field(min_length=3, max_length=500)]


def _normalizar_email(valor: object) -> object:
    """RN-04: trim + minúsculas antes de validar unicidad, persistir o autenticar."""
    return valor.strip().lower() if isinstance(valor, str) else valor


def validar_politica_password(password: str, email: str | None) -> None:
    """RN-03: 8–128 caracteres, al menos una letra y un dígito, distinta del email."""
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise ValueError("La contraseña debe contener al menos una letra y un número.")
    if email is not None and password.strip().lower() == email.lower():
        raise ValueError("La contraseña no puede ser igual al email.")


class _DatosCuentaBase(BaseModel):
    model_config = _INPUT_CONFIG

    email: EmailStr = Field(..., max_length=254, examples=["lucia.perez@untdf.edu.ar"])
    password: Password
    nombre: NombrePersona
    apellido: NombrePersona
    dni: Dni
    telefono: Telefono | None = None

    _norm_email = field_validator("email", mode="before")(_normalizar_email)

    @model_validator(mode="after")
    def _politica_password(self) -> "_DatosCuentaBase":
        validar_politica_password(self.password, self.email)
        return self


class RegistroRequest(_DatosCuentaBase):
    """Autorregistro (UC-01). Sólo ``ESTUDIANTE`` o ``DOCENTE`` (RN-01) y sede obligatoria."""

    rol: Literal[RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE] = Field(..., examples=["ESTUDIANTE"])
    sede: SedeEnum = Field(..., examples=["Ushuaia"])


class UsuarioAdminCreate(_DatosCuentaBase):
    """Alta directa por ``SUPERADMIN`` (UC-06). ``sede=null`` ⇔ "Ambas sedes" ⇔ ``SUPERADMIN``."""

    rol: RolUsuario = Field(..., examples=["ADMIN_LOCAL"])
    sede: SedeEnum | None = Field(default=None, examples=["Río Grande"])

    @model_validator(mode="after")
    def _alcance_segun_rol(self) -> "UsuarioAdminCreate":
        if self.rol == RolUsuario.SUPERADMIN and self.sede is not None:
            raise ValueError("Un SUPERADMIN tiene alcance sobre ambas sedes: `sede` debe ser null.")
        if self.rol != RolUsuario.SUPERADMIN and self.sede is None:
            raise ValueError("`sede` es obligatoria para roles distintos de SUPERADMIN.")
        return self


class LoginRequest(BaseModel):
    """Credenciales de inicio de sesión (UC-03). Sin política de complejidad (§6.6)."""

    model_config = _INPUT_CONFIG

    email: EmailStr = Field(..., max_length=254, examples=["lucia.perez@untdf.edu.ar"])
    password: str = Field(..., min_length=1, max_length=128, examples=["Camara2026!"])

    _norm_email = field_validator("email", mode="before")(_normalizar_email)


class UsuarioResumen(BaseModel):
    """Ítem del directorio (UC-05)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., examples=[42])
    email: str = Field(..., examples=["lucia.perez@untdf.edu.ar"])
    nombre: str = Field(..., examples=["Lucía"])
    apellido: str = Field(..., examples=["Pérez"])
    dni: str = Field(..., examples=["40123456"])
    rol: RolUsuario = Field(..., examples=["ESTUDIANTE"])
    sede: SedeEnum | None = Field(..., examples=["Ushuaia"])
    estado: EstadoCuenta = Field(..., examples=["PENDIENTE_APROBACION"])
    created_at: datetime = Field(..., examples=["2026-10-07T13:45:00Z"])


class UsuarioPublico(UsuarioResumen):
    """Perfil propio (``/auth/register``, ``/auth/login``, ``/auth/me``)."""

    telefono: str | None = Field(default=None, examples=["+54 2901 555123"])
    debe_cambiar_password: bool = Field(default=False, examples=[False])


class UsuarioDetalle(UsuarioPublico):
    """Vista administrativa de una cuenta."""

    motivo_estado: str | None = Field(default=None, examples=[None])
    suspendido_hasta: datetime | None = Field(default=None, examples=[None])
    ultimo_login_en: datetime | None = Field(default=None, examples=["2026-10-07T14:00:00Z"])
    aprobado_por_id: int | None = Field(default=None, examples=[1])
    aprobado_en: datetime | None = Field(default=None, examples=["2026-10-07T13:50:00Z"])
    updated_at: datetime = Field(..., examples=["2026-10-07T13:50:00Z"])


class PaginaUsuarios(BaseModel):
    """Envolvente paginada del directorio (D-09)."""

    items: list[UsuarioResumen]
    total: int = Field(..., examples=[1])
    limit: int = Field(..., examples=[20])
    offset: int = Field(..., examples=[0])


class TokenResponse(BaseModel):
    """Respuesta de login exitoso (§6.6)."""

    access_token: str = Field(..., examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., examples=[3600])
    usuario: UsuarioPublico


EstadoDestino = Literal[
    EstadoCuenta.ACTIVO, EstadoCuenta.RECHAZADO, EstadoCuenta.SUSPENDIDO, EstadoCuenta.INACTIVO
]
_ESTADOS_CON_MOTIVO = {EstadoCuenta.RECHAZADO, EstadoCuenta.SUSPENDIDO, EstadoCuenta.INACTIVO}


class CambioEstadoRequest(BaseModel):
    """Transición administrativa de estado (UC-02, UC-07; §3.2)."""

    model_config = _INPUT_CONFIG

    nuevo_estado: EstadoDestino = Field(..., examples=["SUSPENDIDO"])
    motivo: Motivo | None = Field(
        default=None, examples=["Devolución con 3 días de demora (Res. CICSE 056/2023)."]
    )
    suspendido_hasta: AwareDatetime | None = Field(default=None, examples=["2026-10-20T03:00:00Z"])

    @model_validator(mode="after")
    def _reglas(self) -> "CambioEstadoRequest":
        if self.nuevo_estado in _ESTADOS_CON_MOTIVO and not self.motivo:
            raise ValueError(f"`motivo` es obligatorio para pasar a {self.nuevo_estado.value} (RN-14).")
        if self.suspendido_hasta is not None:
            if self.nuevo_estado != EstadoCuenta.SUSPENDIDO:
                raise ValueError("`suspendido_hasta` sólo se admite con nuevo_estado SUSPENDIDO.")
            if self.suspendido_hasta <= datetime.now(UTC):
                raise ValueError("`suspendido_hasta` debe ser una fecha futura.")
        return self


# ── SPEC-02 · Gestión de cuenta ──────────────────────────────────────────────


class PerfilUpdate(BaseModel):
    """Edición de datos de contacto propios (UC-10, USR-03).

    Sólo ``telefono`` y ``email``; el resto de los datos están protegidos.
    Cambiar el email exige ``password_actual`` (RN-32).
    """

    model_config = _INPUT_CONFIG

    telefono: Telefono | None = Field(default=None, examples=["+54 2901 555123"])
    email: EmailStr | None = Field(default=None, max_length=254, examples=["lucia@gmail.com"])
    password_actual: str | None = Field(default=None, min_length=1, max_length=128)

    _norm_email = field_validator("email", mode="before")(_normalizar_email)

    @model_validator(mode="after")
    def _reglas(self) -> "PerfilUpdate":
        enviados = self.model_fields_set - {"password_actual"}
        if not enviados:
            raise ValueError("Indicá al menos un dato a modificar (telefono o email).")
        if "password_actual" in self.model_fields_set and "email" not in self.model_fields_set:
            raise ValueError("`password_actual` sólo se usa para cambiar el email.")
        if "email" in self.model_fields_set and self.email is None:
            raise ValueError("El email no puede quedar vacío.")
        return self


class CambioPasswordRequest(BaseModel):
    """Cambio de contraseña propia (UC-11)."""

    model_config = _INPUT_CONFIG

    password_actual: str = Field(..., min_length=1, max_length=128)
    password_nueva: Password

    @model_validator(mode="after")
    def _reglas(self) -> "CambioPasswordRequest":
        validar_politica_password(self.password_nueva, None)
        if self.password_nueva == self.password_actual:
            raise ValueError("La contraseña nueva debe ser distinta de la actual.")
        return self


class UsuarioAdminUpdate(BaseModel):
    """Edición administrativa de un perfil (UC-12, USR-04). Al menos un campo."""

    model_config = _INPUT_CONFIG

    nombre: NombrePersona | None = None
    apellido: NombrePersona | None = None
    dni: Dni | None = None
    telefono: Telefono | None = None
    email: EmailStr | None = Field(default=None, max_length=254)
    rol: RolUsuario | None = None
    sede: SedeEnum | None = None
    password_nueva: Password | None = None

    _norm_email = field_validator("email", mode="before")(_normalizar_email)

    @model_validator(mode="after")
    def _reglas(self) -> "UsuarioAdminUpdate":
        if not self.model_fields_set:
            raise ValueError("Indicá al menos un dato a modificar.")
        no_anulables = {"nombre", "apellido", "dni", "email", "rol", "password_nueva"}
        for campo in no_anulables & self.model_fields_set:
            if getattr(self, campo) is None:
                raise ValueError(f"`{campo}` no puede ser null.")
        if self.password_nueva is not None:
            validar_politica_password(self.password_nueva, self.email)
        return self
