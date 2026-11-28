"""SPEC-12 §4.1 · Respuestas de la API sin caché — AC-123, AC-124, AC-125 (RN-90).

Sin ``Cache-Control``, el navegador guarda las respuestas atadas sólo a la URL y, al
restaurar una pestaña duplicada, devuelve el ``/auth/me`` de otro usuario (spec §2.3).
"""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from tests.conftest import auth
from tests.files.conftest import ARCHIVOS, pdf_minimo, subir_aval

pytestmark = pytest.mark.integracion

NO_STORE = "no-store"


class TestApiSinCache:
    async def test_auth_me(self, client, crear_usuario):  # AC-123
        u = await crear_usuario(RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA)
        r = await client.get("/api/v1/auth/me", headers=auth(u))
        assert r.status_code == 200
        assert r.headers["cache-control"] == NO_STORE

    async def test_listado_de_inventory(self, client, crear_usuario):  # AC-123
        u = await crear_usuario(RolUsuario.ADMIN_LOCAL, SedeEnum.USHUAIA)
        r = await client.get("/api/v1/inventory/equipamiento", headers=auth(u))
        assert r.status_code == 200
        assert r.headers["cache-control"] == NO_STORE

    async def test_401_sin_token(self, client):  # AC-123
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401
        assert r.headers["cache-control"] == NO_STORE

    async def test_403_permiso_insuficiente(self, client, crear_usuario):  # AC-123
        u = await crear_usuario(RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA)
        r = await client.post("/api/v1/inventory/equipamiento", json={}, headers=auth(u))
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"
        assert r.headers["cache-control"] == NO_STORE

    async def test_422_de_validacion(self, client):  # AC-123
        r = await client.post("/api/v1/auth/login", json={})
        assert r.status_code == 422
        assert r.headers["cache-control"] == NO_STORE

    async def test_un_solo_encabezado(self, client, crear_usuario):  # AC-123
        u = await crear_usuario(RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA)
        r = await client.get("/api/v1/auth/me", headers=auth(u))
        assert r.headers.get_list("cache-control") == [NO_STORE]


class TestEncabezadoPropio:
    async def test_descarga_conserva_el_suyo(self, client, crear_usuario):  # AC-124
        u = await crear_usuario(RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA)
        subido = await subir_aval(client, u, pdf_minimo(), nombre="aval.pdf")
        assert subido.status_code == 201, subido.text
        r = await client.get(f"{ARCHIVOS}/{subido.json()['id']}/contenido", headers=auth(u))
        assert r.status_code == 200
        assert r.headers.get_list("cache-control") == ["private, no-store"]


class TestFueraDeLaApi:
    async def test_health(self, client):  # AC-125
        r = await client.get("/health")
        assert r.status_code == 200
        assert "cache-control" not in r.headers
