"""SPEC-04 RN-I13 — Plazo de préstamo al cambiar `es_notebook` (C18) - INV-29."""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/inventory"
USH = SedeEnum.USHUAIA


@pytest.fixture
async def admin(crear_usuario, set_parametro):
    await set_parametro("prestamo.general.max_dias", 3)
    await set_parametro("prestamo.notebook.max_dias", 12)
    return await crear_usuario(RolUsuario.ADMIN_LOCAL, USH)


async def _editar(client, admin, equipo, cambios):
    r = await client.patch(f"{B}/equipamiento/{equipo.id}", json=cambios, headers=auth(admin))
    assert r.status_code == 200
    return r.json()


async def test_cambiar_a_notebook_recalcula_el_plazo(client, admin, crear_equipo):  # INV-29
    equipo = await crear_equipo(unidades=((USH,),), max_dias_prestamo=7)
    cuerpo = await _editar(client, admin, equipo, {"es_notebook": True})
    assert cuerpo["es_notebook"] is True and cuerpo["max_dias_prestamo"] == 12


async def test_cambiar_de_notebook_a_general_recalcula_el_plazo(client, admin, crear_equipo):  # INV-29
    equipo = await crear_equipo(unidades=((USH,),), es_notebook=True, max_dias_prestamo=9)
    cuerpo = await _editar(client, admin, equipo, {"es_notebook": False})
    assert cuerpo["es_notebook"] is False and cuerpo["max_dias_prestamo"] == 3


async def test_el_plazo_enviado_gana(client, admin, crear_equipo):  # INV-29
    equipo = await crear_equipo(unidades=((USH,),), max_dias_prestamo=7)
    cuerpo = await _editar(client, admin, equipo, {"es_notebook": True, "max_dias_prestamo": 5})
    assert cuerpo["max_dias_prestamo"] == 5


async def test_sin_cambiar_el_tipo_el_plazo_no_se_toca(client, admin, crear_equipo):  # INV-29
    equipo = await crear_equipo(unidades=((USH,),), max_dias_prestamo=7)
    mismo_tipo = await _editar(client, admin, equipo, {"es_notebook": False})
    otro_campo = await _editar(client, admin, equipo, {"nombre": "Otro nombre"})
    assert mismo_tipo["max_dias_prestamo"] == 7 and otro_campo["max_dias_prestamo"] == 7
