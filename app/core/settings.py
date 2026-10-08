"""Configuración tipada leída de variables de entorno (SPEC-01 §6.2, NFR-03).

Los secretos viven **sólo** en el entorno / `.env`; nunca en código ni en
parámetros globales (RN-23).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "prestamedios-api"


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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Instancia única de ``Settings``. Falla al arrancar si falta ``JWT_SECRET_KEY``."""
    return Settings()  # type: ignore[call-arg]
