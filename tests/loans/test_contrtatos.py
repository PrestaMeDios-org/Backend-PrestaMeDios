"""Contrato HTTP de `loans` (SPEC-05 §14; AC-L52, AC-L53).

Los endpoints exigen sesión y rol, y responden 501 ``NO_IMPLEMENTADO`` hasta
que exista ``service.py``. Estos tests se reemplazan por los de cada criterio a
medida que se implementa la lógica de las fases siguientes.
"""

import pytest

from app.core.enums import RolUsuario
from tests.conftest import auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"

ORDEN = {
    "retiro": "2026-12-01T10:00:00-03:00",
    "devolucion": "2026-12-03T15:00:00-03:00",
    "items": [{"equipamiento_id": 1}],
    "acepta_normativa": True,
}
RECHAZO = {"estado": "rechazada", "motivo": "Sin stock"}

E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN

# (método, ruta, cuerpo)
RUTAS = [
    ("POST", "/ordenes", ORDEN),
    ("GET", "/ordenes/mias", None),
    ("GET", "/ordenes", None),
    ("GET", "/ordenes/1", None),
    ("PATCH", "/ordenes/1/estado", RECHAZO),
]

# (rol, método, ruta, cuerpo) con permiso: llegan al placeholder
PERMITIDAS = [
    (E, "POST", "/ordenes", ORDEN),
    (D, "POST", "/ordenes", ORDEN),
    (E, "GET", "/ordenes/mias", None),
    (D, "GET", "/ordenes/mias", None),
    (A, "GET", "/ordenes", None),
    (S, "GET", "/ordenes", None),
    (E, "GET", "/ordenes/1", None),
    (A, "PATCH", "/ordenes/1/estado", RECHAZO),
]

# (rol, método, ruta, cuerpo) sin permiso según la matriz del spec §4
PROHIBIDAS = [
    (A, "POST", "/ordenes", ORDEN),
    (S, "POST", "/ordenes", ORDEN),
    (A, "GET", "/ordenes/mias", None),
    (S, "GET", "/ordenes/mias", None),
    (E, "GET", "/ordenes", None),
    (D, "GET", "/ordenes", None),
]


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS)
async def test_sin_token_responde_401(client, metodo, ruta, cuerpo):  # AC-L52
    r = await client.request(metodo, f"{BASE}{ruta}", json=cuerpo)
    assert r.status_code == 401


@pytest.mark.parametrize(("rol", "metodo", "ruta", "cuerpo"), PROHIBIDAS)
async def test_rol_sin_permiso_responde_403(client, crear_usuario, rol, metodo, ruta, cuerpo):
    usuario = await crear_usuario(rol)  # AC-L13, AC-L17
    r = await client.request(metodo, f"{BASE}{ruta}", json=cuerpo, headers=auth(usuario))
    assert r.status_code == 403


@pytest.mark.parametrize(("rol", "metodo", "ruta", "cuerpo"), PERMITIDAS)
async def test_con_permiso_responde_501_no_implementado(
    client, crear_usuario, rol, metodo, ruta, cuerpo
):  # AC-L52, AC-L53
    usuario = await crear_usuario(rol)
    r = await client.request(metodo, f"{BASE}{ruta}", json=cuerpo, headers=auth(usuario))
    assert r.status_code == 501
    assert r.json()["code"] == "NO_IMPLEMENTADO"


@pytest.mark.parametrize(
    ("rol", "metodo", "ruta", "cuerpo"),
    [
        (E, "POST", "/ordenes", {**ORDEN, "acepta_normativa": False}),  # AC-L06
        (E, "POST", "/ordenes", {**ORDEN, "sede": "Ushuaia"}),  # AC-L04
        (E, "POST", "/ordenes", {**ORDEN, "items": []}),
        (A, "PATCH", "/ordenes/1/estado", {"estado": "pendiente"}),
        (A, "PATCH", "/ordenes/1/estado", {"estado": "aprobada"}),  # AC-L22
    ],
)
async def test_payload_invalido_responde_422(client, crear_usuario, rol, metodo, ruta, cuerpo):
    usuario = await crear_usuario(rol)
    r = await client.request(metodo, f"{BASE}{ruta}", json=cuerpo, headers=auth(usuario))
    assert r.status_code == 422


async def test_mias_no_se_confunde_con_el_detalle(client, crear_usuario):
    """``/ordenes/mias`` se declara antes de ``/ordenes/{orden_id}``."""
    usuario = await crear_usuario(E)
    r = await client.get(f"{BASE}/ordenes/mias", headers=auth(usuario))
    assert r.status_code == 501  # y no 422 por intentar convertir "mias" a entero


async def test_openapi_publica_las_rutas_del_spec(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert set(paths[f"{BASE}/ordenes"]) == {"get", "post"}
    assert set(paths[f"{BASE}/ordenes/mias"]) == {"get"}
    assert set(paths[f"{BASE}/ordenes/{{orden_id}}"]) == {"get"}
    assert set(paths[f"{BASE}/ordenes/{{orden_id}}/estado"]) == {"patch"}
    assert f"{BASE}/ordenes/{{orden_id}}/resolucion" not in paths
    assert f"{BASE}/ordenes/{{orden_id}}/cancelacion" not in paths