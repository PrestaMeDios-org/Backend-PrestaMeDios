"""Punto de entrada de la PrestaMeDios API.

Monolito Modular por Dominio: cada módulo bajo ``app.modules`` expone su
propio router, que se registra aquí de forma explícita.
"""

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app import database

from app.core.errors import AppError, app_error_handler
from app.core.settings import get_settings
from app.modules.config.router import router as config_router
from app.modules.files.router import router as files_router
from app.modules.inventory.router import router as inventory_router
from app.modules.loans.router import router as loans_router
from app.modules.notifications.router import router as notifications_router
from app.modules.notifications.portada import router as portada_router  # MOMENTÁNEO (SPEC-10 M-02)
from app.modules.spaces.router import router as spaces_router
from app.modules.users.router import auth_router, users_router

# Falla al arrancar si falta configuración obligatoria (p. ej. JWT_SECRET_KEY).
settings = get_settings()
logger = logging.getLogger(__name__)

# En producción no se publica la documentación interactiva (SPEC-11 D-08, AC-P10).
_DOCUMENTACION = (
    {"docs_url": None, "redoc_url": None, "openapi_url": None}
    if settings.entorno == "produccion"
    else {}
)

app = FastAPI(
    title="PrestaMeDios API",
    description=(
        "API del Laboratorio de Medios Audiovisuales (ICSE — UNTDF): identidad y permisos, "
        "catálogo e inventario, préstamos y solicitudes de equipamiento,"
        "reservas de espacios y configuración global."
    ),
    version="0.2.0",
    **_DOCUMENTACION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# IP real del usuario detrás de nginx (SPEC-11 §6.9.2, RN-54): sólo se cree a
# X-Forwarded-For si el pedido llega desde un proxy de FORWARDED_ALLOW_IPS. Va en la
# app y no en la línea de comandos de uvicorn para que valga igual en los tests.
# Se agrega último para que sea el más externo.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.forwarded_allow_ips)
app.add_exception_handler(AppError, app_error_handler)

app.include_router(
    auth_router,
    prefix="/api/v1/auth",
    tags=["Autenticación"],
)

app.include_router(
    users_router,
    prefix="/api/v1/users",
    tags=["Usuarios"],
)

app.include_router(
    config_router,
    prefix="/api/v1/config",
    tags=["Configuración Global"],
)

app.include_router(
    files_router,
    prefix="/api/v1/files",
    tags=["Archivos"],
)

app.include_router(
    inventory_router,
    prefix="/api/v1/inventory",
    tags=["Catálogo e Inventario"],
)


app.include_router(
    spaces_router,
    prefix="/api/v1/spaces",
    tags=["Espacios e Infraestructura"],
)

app.include_router(
    loans_router,
    prefix="/api/v1/loans",
    tags=["Préstamos y Solicitudes"],
)

# MOMENTÁNEO (SPEC-10 M-02): antes que `notifications_router`, para que
# `/comunicados/portadas` no lo tome `/comunicados/{comunicado_id}`.
app.include_router(
    portada_router,
    prefix="/api/v1/notifications",
    tags=["Comunicaciones y notificaciones"],
)

app.include_router(
    notifications_router,
    prefix="/api/v1/notifications",
    tags=["Comunicaciones y notificaciones"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check básico para monitoreo y orquestadores."""
    return {"status": "ok"}


@app.get(
    "/health/db",
    tags=["health"],
    responses={503: {"description": "La base no responde", "content": {"application/json": {"example": {"status": "sin_base"}}}}},
)
async def health_db() -> JSONResponse:
    """Chequea que la base responda (SPEC-11 §6.9.3, AC-P12). Público, como ``/health``.

    Lo consulta el monitoreo externo (D-15). Nunca devuelve ni registra el detalle del
    error: puede traer la URL de la base.
    """
    try:
        async with asyncio.timeout(2):
            async with database.AsyncSessionLocal() as sesion:
                await sesion.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — cualquier fallo es "sin base"
        logger.warning("La base no responde al health check (%s).", type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "sin_base"})
    return JSONResponse(content={"status": "ok"})
