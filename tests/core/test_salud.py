"""SPEC-11 §6.9.3 · ``GET /health/db`` — AC-P12."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import database

pytestmark = pytest.mark.integracion

RUTA = "/health/db"


async def test_base_disponible(client, sessionmaker_, monkeypatch):  # AC-P12
    monkeypatch.setattr(database, "AsyncSessionLocal", sessionmaker_)
    r = await client.get(RUTA)  # sin Authorization: público como /health (P4.1)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_sin_base_503_sin_detalle(client, monkeypatch, caplog):  # AC-P12
    caida = create_async_engine(
        "postgresql+asyncpg://nadie:clave-secreta@127.0.0.1:1/inexistente", poolclass=NullPool
    )
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(caida))
    r = await client.get(RUTA)
    assert r.status_code == 503
    assert r.json() == {"status": "sin_base"}
    # Ni la respuesta ni el log llevan la URL ni el mensaje del error.
    assert "clave-secreta" not in r.text
    assert "clave-secreta" not in caplog.text
    await caida.dispose()


async def test_health_sigue_sin_consultar_la_base(client, monkeypatch):  # §6.9.3
    caida = create_async_engine("postgresql+asyncpg://x:y@127.0.0.1:1/z", poolclass=NullPool)
    monkeypatch.setattr(database, "AsyncSessionLocal", async_sessionmaker(caida))
    assert (await client.get("/health")).json() == {"status": "ok"}
    await caida.dispose()
