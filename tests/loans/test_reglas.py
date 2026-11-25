"""`GET /api/v1/loans/reglas` (SPEC-05 §6.1; AC-L01, AC-L63).

El horario es el de la sede (`config.datos_de_sede`, ADR-022 a, H2 de SPEC-09); la
anticipación y los plazos son comunes a las dos sedes.
"""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from tests.conftest import auth

pytestmark = pytest.mark.integracion

URL = "/api/v1/loans/reglas"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE

SEMILLA = {
    "sede": "Ushuaia",
    "horario_apertura": "09:00:00",
    "horario_cierre": "16:00:00",
    "anticipacion_min_horas": 24,
    "max_dias_general": 4,
    "max_dias_notebook": 15,
    "tolerancia_retiro_horas": 2,
}


async def test_reglas_devuelve_los_parametros_sembrados(client, crear_usuario):  # AC-L01
    usuario = await crear_usuario(E, USH)
    r = await client.get(URL, headers=auth(usuario))
    assert r.status_code == 200
    assert r.json() == SEMILLA


@pytest.mark.parametrize("rol", [E, D, A])
@pytest.mark.parametrize("sede", [USH, RG])
async def test_cada_rol_ve_las_reglas_de_su_sede(client, crear_usuario, rol, sede):  # AC-L63
    usuario = await crear_usuario(rol, sede)
    r = await client.get(URL, headers=auth(usuario))
    assert r.status_code == 200
    assert r.json()["sede"] == sede.value


async def test_cada_sede_tiene_su_propio_horario(client, crear_usuario, set_parametro):
    # AC-L63, ADR-022 a: cambiar el horario de Río Grande no toca el de Ushuaia
    await set_parametro("horario.rio_grande.apertura", "10:00")
    await set_parametro("horario.rio_grande.cierre", "17:00")
    de_ushuaia = (await client.get(URL, headers=auth(await crear_usuario(E, USH)))).json()
    de_rio_grande = (await client.get(URL, headers=auth(await crear_usuario(E, RG)))).json()
    horario = lambda r: (r["horario_apertura"], r["horario_cierre"])  # noqa: E731
    assert horario(de_ushuaia) == ("09:00:00", "16:00:00")
    assert horario(de_rio_grande) == ("10:00:00", "17:00:00")


async def test_ya_no_se_lee_el_horario_global(client, crear_usuario, set_parametro):
    # RN-81 de SPEC-09: las claves globales quedan obsoletas y no afectan a loans (H2)
    await set_parametro("horario.apertura", "07:00")
    r = await client.get(URL, headers=auth(await crear_usuario(E, USH)))
    assert r.json()["horario_apertura"] == "09:00:00"


async def test_reglas_refleja_los_cambios_de_los_parametros(
    client, crear_usuario, set_parametro
):  # AC-L01
    await set_parametro("prestamo.general.max_dias", 5)
    await set_parametro("horario.ushuaia.apertura", "08:00")
    cuerpo = (await client.get(URL, headers=auth(await crear_usuario(D, USH)))).json()
    assert cuerpo["max_dias_general"] == 5
    assert cuerpo["horario_apertura"] == "08:00:00"


@pytest.mark.parametrize("sede", [USH, RG])
async def test_el_superadmin_elige_la_sede(client, crear_usuario, sede):  # AC-L63, EC-57
    superadmin = await crear_usuario(S)
    r = await client.get(URL, params={"sede": sede.value}, headers=auth(superadmin))
    assert r.status_code == 200
    assert r.json()["sede"] == sede.value


async def test_el_superadmin_sin_sede_recibe_422(client, crear_usuario):  # EC-57
    r = await client.get(URL, headers=auth(await crear_usuario(S)))
    assert r.status_code == 422
    assert r.json()["code"] == "SEDE_REQUERIDA"


@pytest.mark.parametrize("rol", [E, A])
async def test_pedir_otra_sede_responde_403(client, crear_usuario, rol):  # como en core
    usuario = await crear_usuario(rol, USH)
    otra = await client.get(URL, params={"sede": RG.value}, headers=auth(usuario))
    propia = await client.get(URL, params={"sede": USH.value}, headers=auth(usuario))
    assert otra.status_code == 403
    assert otra.json()["code"] == "SEDE_FUERA_DE_ALCANCE"
    assert propia.status_code == 200


async def test_reglas_exige_sesion(client):  # AC-L52
    r = await client.get(URL)
    assert r.status_code == 401
