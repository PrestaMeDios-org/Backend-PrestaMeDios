"""Errores de negocio homogéneos (SPEC-01 §6.1, §6.15).

Formato de respuesta: ``{"detail": "<mensaje>", "code": "<CODIGO>", ...extra}``.
``detail`` se mantiene como ``str`` para compatibilidad con el frontend
(que lee ``body.detail``). Los errores de validación conservan el formato
estándar de FastAPI (422).
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class AppError(Exception):
    """Error de negocio con código HTTP, código máquina y mensaje legible."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.headers = headers
        self.extra = extra


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    content: dict[str, Any] = {"detail": exc.detail, "code": exc.code}
    content.update({k: _jsonable(v) for k, v in exc.extra.items()})
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class ErrorNegocio(BaseModel):
    """Esquema OpenAPI de un error de negocio."""

    detail: str = Field(..., examples=["No tenés permisos para realizar esta acción."])
    code: str = Field(..., examples=["PERMISO_INSUFICIENTE"])


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Declaración de respuestas de error para ``responses=`` en los routers (NFR-09)."""
    descripciones = {
        401: "No autenticado o sesión inválida.",
        403: "Sin permiso o cuenta no habilitada.",
        404: "Recurso inexistente o fuera de alcance.",
        409: "Conflicto de estado, unicidad o concurrencia.",
        422: "Datos inválidos.",
    }
    return {c: {"model": ErrorNegocio, "description": descripciones[c]} for c in codes}
