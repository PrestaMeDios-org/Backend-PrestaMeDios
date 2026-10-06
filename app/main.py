"""Punto de entrada de la PrestaMeDios API.

Monolito Modular por Dominio: cada módulo bajo ``app.modules`` expone su
propio router, que se registra aquí de forma explícita.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.modules.inventory.router import router as inventory_router

app = FastAPI(
    title="PrestaMeDios API - Catálogo e Inventario",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:8443").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro explícito de routers por módulo de dominio.
app.include_router(
    inventory_router,
    prefix="/api/v1/inventory",
    tags=["Catálogo e Inventario"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check básico para monitoreo y orquestadores."""
    return {"status": "ok"}
