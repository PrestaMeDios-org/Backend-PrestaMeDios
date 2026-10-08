"""Punto de entrada de la PrestaMeDios API.

Monolito Modular por Dominio: cada módulo bajo ``app.modules`` expone su
propio router, que se registra aquí de forma explícita.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.errors import AppError, app_error_handler
from app.core.settings import get_settings
from app.modules.config.router import router as config_router
from app.modules.inventory.router import router as inventory_router
from app.modules.spaces.router import router as spaces_router
from app.modules.loans.router import router as loans_router
from app.modules.users.router import auth_router, users_router

# Falla al arrancar si falta configuración obligatoria (p. ej. JWT_SECRET_KEY).
settings = get_settings()

app = FastAPI(
    title="PrestaMeDios API",
    description=(
        "API del Laboratorio de Medios Audiovisuales (ICSE — UNTDF): identidad y permisos, "
        "catálogo e inventario, reservas de espacios y configuración global."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check básico para monitoreo y orquestadores."""
    return {"status": "ok"}
