"""Configuración tipada leída de variables de entorno (SPEC-01 §6.2, NFR-03).

Los secretos viven **sólo** en el entorno / `.env`; nunca en código ni en
parámetros globales (RN-23).
"""

from datetime import datetime
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "prestamedios-api"

# Ambas sedes comparten zona horaria (SPEC-02 D-05, RN-28).
ZONA_HORARIA_LAB = ZoneInfo("America/Argentina/Ushuaia")


def ahora_lab() -> datetime:
    """Fecha y hora actuales en la zona del laboratorio."""
    return datetime.now(ZONA_HORARIA_LAB)


class Settings(BaseSettings):
    """Variables de entorno de la aplicación."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/prestamedios",
        alias="DATABASE_URL",
    )
    cors_origins: str = Field(default="http://localhost:8443", alias="CORS_ORIGINS")
    jwt_secret_key: str = Field(..., min_length=32, alias="JWT_SECRET_KEY")
    jwt_access_token_expire_minutes: int = Field(
        default=60, ge=1, le=1440, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # Archivos (SPEC-03 §6.2, RN-56, RN-58, RN-63).
    archivo_foto_max_mb: int = Field(default=2, ge=1, le=20, alias="ARCHIVO_FOTO_MAX_MB")
    archivo_pdf_max_mb: int = Field(default=10, ge=1, le=50, alias="ARCHIVO_PDF_MAX_MB")
    archivo_huerfano_horas: int = Field(
        default=24, ge=1, le=24 * 30, alias="ARCHIVO_HUERFANO_HORAS"
    )
    archivo_max_pendientes: int = Field(default=5, ge=1, le=50, alias="ARCHIVO_MAX_PENDIENTES")

    # Correo (SPEC-03 §5.1). Secretos sólo en `.env` (NFR-03).
    email_backend: Literal["smtp", "memoria"] = Field(default="smtp", alias="EMAIL_BACKEND")
    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, ge=1, le=65535, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD", repr=False)
    smtp_tls: Literal["starttls", "ssl", "ninguno"] = Field(default="starttls", alias="SMTP_TLS")
    email_from: str = Field(
        default="PrestaMeDios <no-responder@localhost>", alias="EMAIL_FROM"
    )
    frontend_url: str = Field(default="http://localhost:8443", alias="FRONTEND_URL")

    # Recuperación de contraseña (SPEC-03 §5.2, D-07): seguridad técnica, no GLO-03.
    recuperacion_vigencia_minutos: int = Field(
        default=30, ge=5, le=24 * 60, alias="RECUPERACION_VIGENCIA_MINUTOS"
    )
    recuperacion_max_por_email_hora: int = Field(
        default=3, ge=1, le=100, alias="RECUPERACION_MAX_POR_EMAIL_HORA"
    )
    recuperacion_max_por_ip_hora: int = Field(
        default=20, ge=1, le=1000, alias="RECUPERACION_MAX_POR_IP_HORA"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Instancia única de ``Settings``. Falla al arrancar si falta ``JWT_SECRET_KEY``."""
    return Settings()  # type: ignore[call-arg]
