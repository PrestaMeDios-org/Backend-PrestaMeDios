"""SPEC-04 §5.5 — Historial de usuarios por unidad (PRE-12, P5, P6) - INV-34."""

from datetime import datetime, time

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.core.settings import ZONA_HORARIA_LAB
from app.modules.loans.enums import EstadoDetalleEnum as D
from tests.conftest import auth, dia

pytestmark = pytest.mark.integracion

B = "/api/v1/inventory"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE

CAMPOS = {
    "orden_id",
    "detalle_id",
    "solicitante",
    "estado",
    "retiro_pactado",
    "devolucion_pactada",
    "entregado_en",
    "devuelto_en",
    "observacion_devolucion",
}


def _url(unidad_id: int) -> str:
    return f"{B}/unidades/{unidad_id}/historial"


def _retiro(offset: int) -> datetime:
    return datetime.combine(dia(offset), time(10), tzinfo=ZONA_HORARIA_LAB)


async def _unidad_con_historial(crear_equipo, crear_linea, crear_usuario):
    """Una unidad de Ushuaia con cuatro líneas en distintos estados y fechas."""
    eq = await crear_equipo(unidades=((USH,),))
    unidad = eq.unidades[0]
    ana = await crear_usuario(R.ESTUDIANTE, USH, nombre="Ana", apellido="Pérez")
    lineas = [
        (D.DEVUELTO, -20),
        (D.CANCELADO, -10),
        (D.PENDIENTE, 5),
        (D.RESERVADO, 15),
    ]
    for estado, offset in lineas:
        await crear_linea(eq, unidad, estado, retiro=_retiro(offset), solicitante=ana)
    return eq, unidad, ana


async def test_admin_local_ve_el_historial_ordenado(  # INV-34
    client, crear_equipo, crear_linea, crear_usuario
):
    _, unidad, ana = await _unidad_con_historial(crear_equipo, crear_linea, crear_usuario)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    r = await client.get(_url(unidad.id), headers=auth(admin))

    assert r.status_code == 200
    filas = r.json()
    assert [f["estado"] for f in filas] == ["reservado", "pendiente", "cancelado", "devuelto"]
    retiros = [f["retiro_pactado"] for f in filas]
    assert retiros == sorted(retiros, reverse=True)
    for fila in filas:
        assert set(fila) == CAMPOS
        assert fila["solicitante"] == {
            "id": ana._cache_auth["id"],
            "nombre": "Ana",
            "apellido": "Pérez",
        }
        # Hasta la migración 0012 de `loans` (Fase 3 de SPEC-05).
        assert fila["entregado_en"] is None
        assert fila["devuelto_en"] is None
        assert fila["observacion_devolucion"] is None


async def test_la_respuesta_no_expone_datos_personales(  # INV-34 (P6)
    client, crear_equipo, crear_linea, crear_usuario
):
    _, unidad, ana = await _unidad_con_historial(crear_equipo, crear_linea, crear_usuario)
    admin = await crear_usuario(R.SUPERADMIN, None)

    r = await client.get(_url(unidad.id), headers=auth(admin))

    assert r.status_code == 200 and len(r.json()) == 4
    texto = r.text.lower()
    for clave in ("dni", "email", "telefono"):
        assert clave not in texto
    assert ana.email.lower() not in texto


async def test_limit_y_offset_paginan_sin_repetir(  # INV-34
    client, crear_equipo, crear_linea, crear_usuario
):
    _, unidad, _ = await _unidad_con_historial(crear_equipo, crear_linea, crear_usuario)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    todas = (await client.get(_url(unidad.id), headers=auth(admin))).json()
    p1 = await client.get(_url(unidad.id), params={"limit": 2}, headers=auth(admin))
    p2 = await client.get(_url(unidad.id), params={"limit": 2, "offset": 2}, headers=auth(admin))
    p3 = await client.get(_url(unidad.id), params={"limit": 2, "offset": 4}, headers=auth(admin))

    ids = [f["detalle_id"] for f in p1.json() + p2.json()]
    assert ids == [f["detalle_id"] for f in todas]
    assert len(set(ids)) == 4
    assert p3.status_code == 200 and p3.json() == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
async def test_paginacion_fuera_de_rango_es_422(  # INV-34
    client, crear_equipo, crear_usuario, params
):
    eq = await crear_equipo(unidades=((USH,),))
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    r = await client.get(_url(eq.unidades[0].id), params=params, headers=auth(admin))

    assert r.status_code == 422


async def test_unidad_sin_lineas_devuelve_lista_vacia(  # INV-34
    client, crear_equipo, crear_usuario
):
    eq = await crear_equipo(unidades=((USH,),))
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    r = await client.get(_url(eq.unidades[0].id), headers=auth(admin))

    assert r.status_code == 200 and r.json() == []


async def test_otra_sede_o_inexistente_es_404(  # INV-34 (P5)
    client, crear_equipo, crear_linea, crear_usuario
):
    _, unidad, _ = await _unidad_con_historial(crear_equipo, crear_linea, crear_usuario)
    admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG)

    for unidad_id in (unidad.id, 999_999):
        r = await client.get(_url(unidad_id), headers=auth(admin_rg))
        assert r.status_code == 404
        assert r.json()["code"] == "UNIDAD_NO_ENCONTRADA"


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
async def test_estudiante_y_docente_reciben_403(  # INV-34
    client, crear_equipo, crear_usuario, rol
):
    eq = await crear_equipo(unidades=((USH,),))
    usuario = await crear_usuario(rol, USH)

    r = await client.get(_url(eq.unidades[0].id), headers=auth(usuario))

    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


async def test_sin_sesion_es_401(client, crear_equipo):  # INV-34
    eq = await crear_equipo(unidades=((USH,),))

    r = await client.get(_url(eq.unidades[0].id))

    assert r.status_code == 401
