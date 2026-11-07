"""`GET /api/v1/loans/reglas` (SPEC-05 §6.1; AC-L01)."""

import pytest

from app.core.enums import RolUsuario
from tests.conftest import auth

pytestmark = pytest.mark.integracion

URL = "/api/v1/loans/reglas"

SEMILLA = {
    "horario_apertura": "09:00:00",
    "horario_cierre": "16:00:00",
    "anticipacion_min_horas": 24,
    "max_dias_general": 4,
    "max_dias_notebook": 15,
    "tolerancia_retiro_horas": 2,
}


async def test_reglas_devuelve_los_parametros_sembrados(client, crear_usuario):  # AC-L01
    usuario = await crear_usuario(RolUsuario.ESTUDIANTE)
    r = await client.get(URL, headers=auth(usuario))
    assert r.status_code == 200
    assert r.json() == SEMILLA


@pytest.mark.parametrize("rol", list(RolUsuario))
async def test_reglas_las_ve_cualquier_rol(client, crear_usuario, rol):  # AC-L01
    usuario = await crear_usuario(rol)
    r = await client.get(URL, headers=auth(usuario))
    assert r.status_code == 200


async def test_reglas_refleja_los_cambios_de_los_parametros(
    client, crear_usuario, set_parametro
):  # AC-L01
    await set_parametro("prestamo.general.max_dias", 5)
    await set_parametro("horario.apertura", "08:00")
    usuario = await crear_usuario(RolUsuario.DOCENTE)
    cuerpo = (await client.get(URL, headers=auth(usuario))).json()
    assert cuerpo["max_dias_general"] == 5
    assert cuerpo["horario_apertura"] == "08:00:00"


async def test_reglas_exige_sesion(client):  # AC-L52
    r = await client.get(URL)
    assert r.status_code == 401
