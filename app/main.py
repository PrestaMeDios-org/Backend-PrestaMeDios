"""Punto de entrada de la PrestaMeDios API.

Monolito Modular por Dominio: cada módulo bajo ``app.modules`` expone su
propio router, que se registra aquí de forma explícita.
"""

from fastapi import FastAPI

from app.modules.inventory.router import router as inventory_router
from app.modules.spaces.router import router as spaces_router

app = FastAPI(
    title="PrestaMeDios API - Catálogo e Inventario",
    version="0.1.0",
)

# Registro explícito de routers por módulo de dominio.
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


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check básico para monitoreo y orquestadores."""
    return {"status": "ok"}
