"""SPEC-11 §6.9.2 · IP real del cliente detrás del proxy — AC-P14 (parte automática).

El límite por IP de la recuperación de contraseña (SPEC-03 RN-54) tiene que contar
por la IP del usuario que manda nginx en ``X-Forwarded-For``, y sólo si el pedido
llega desde un proxy de confianza (``FORWARDED_ALLOW_IPS``, por defecto 127.0.0.1).
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select

from app.core.settings import get_settings
from app.database import get_db
from app.main import app
from app.modules.users.models import IntentoRecuperacion

pytestmark = pytest.mark.integracion

SOLICITAR = "/api/v1/auth/recuperacion"
PROXY = "127.0.0.1"  # de confianza por defecto
AJENO = "203.0.113.5"  # no está en FORWARDED_ALLOW_IPS


@pytest.fixture
def cliente_desde(db, sessionmaker_):
    """Cliente HTTP cuya conexión llega desde la IP indicada."""
    abiertos: list[httpx.AsyncClient] = []

    async def _get_db() -> AsyncIterator:
        async with sessionmaker_() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db

    def _crear(ip: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, client=(ip, 40000))
        c = httpx.AsyncClient(transport=transport, base_url="http://test")
        abiertos.append(c)
        return c

    yield _crear
    app.dependency_overrides.clear()


async def _ips(db) -> list[str]:
    db.expire_all()
    return [i.ip for i in (await db.scalars(select(IntentoRecuperacion).order_by(IntentoRecuperacion.id)))]


async def test_desde_el_proxy_cuenta_por_la_ip_del_usuario(cliente_desde, db, monkeypatch):  # AC-P14
    monkeypatch.setattr(get_settings(), "recuperacion_max_por_ip_hora", 1)
    async with cliente_desde(PROXY) as c:
        for i, usuario in enumerate(("198.51.100.1", "198.51.100.2", "198.51.100.3")):
            r = await c.post(SOLICITAR, json={"email": f"u{i}@untdf.edu.ar"}, headers={"X-Forwarded-For": usuario})
            assert r.status_code == 202  # cada usuario tiene su propio cupo
        r = await c.post(SOLICITAR, json={"email": "otro@untdf.edu.ar"}, headers={"X-Forwarded-For": "198.51.100.1"})
        assert r.status_code == 429  # el mismo usuario ya usó el suyo
    assert await _ips(db) == ["198.51.100.1", "198.51.100.2", "198.51.100.3"]


async def test_cabecera_de_un_origen_no_confiable_se_ignora(cliente_desde, db, monkeypatch):  # AC-P14, EC-P03
    monkeypatch.setattr(get_settings(), "recuperacion_max_por_ip_hora", 1)
    async with cliente_desde(AJENO) as c:
        r1 = await c.post(SOLICITAR, json={"email": "a@untdf.edu.ar"}, headers={"X-Forwarded-For": "198.51.100.7"})
        r2 = await c.post(SOLICITAR, json={"email": "b@untdf.edu.ar"}, headers={"X-Forwarded-For": "198.51.100.8"})
    assert r1.status_code == 202
    assert r2.status_code == 429  # falsear la cabecera no da cupo nuevo
    assert await _ips(db) == [AJENO]


async def test_sin_proxy_nada_cambia(cliente_desde, db):  # RN-54 sin proxy
    async with cliente_desde(PROXY) as c:
        assert (await c.post(SOLICITAR, json={"email": "a@untdf.edu.ar"})).status_code == 202
    assert await _ips(db) == [PROXY]
