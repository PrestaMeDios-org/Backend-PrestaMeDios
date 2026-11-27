"""Contrato HTTP de `loans` en la Fase 0 (SPEC-05 §14; AC-L52, AC-L53).

Los endpoints exigen sesión y rol: acá vive el único barrido de 401 del módulo (incluye
`/reglas` y la descarga del aval) y la matriz de 403 del spec §4. Las validaciones del
payload se prueban en ``test_schemas.py``. Crear orden se prueba en ``test_crear_orden.py``, la
bandeja en ``test_bandeja.py`` y el rechazo y la cancelación en
``test_rechazar_cancelar.py``.
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
    ("GET", "/ordenes/1/unidades-libres", None),
    ("GET", "/reglas", None),
    ("GET", "/ordenes/1/aval", None),
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
# El PATCH de E y D (AC-L29) lo cubre, además sin revelar si la orden existe,
# test_rechazar_cancelar::test_el_dueño_no_puede_aprobar_ni_rechazar.


@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), RUTAS)
async def test_sin_token_responde_401(client, metodo, ruta, cuerpo):  # AC-L52
    r = await client.request(metodo, f"{BASE}{ruta}", json=cuerpo)
    assert r.status_code == 401


@pytest.mark.parametrize(("rol", "metodo", "ruta", "cuerpo"), PROHIBIDAS)
async def test_rol_sin_permiso_responde_403(client, crear_usuario, rol, metodo, ruta, cuerpo):
    usuario = await crear_usuario(rol)  # AC-L13, AC-L17
    r = await client.request(metodo, f"{BASE}{ruta}", json=cuerpo, headers=auth(usuario))
    assert r.status_code == 403
    assert r.json()["code"] == "PERMISO_INSUFICIENTE"
