"""Consulta del solicitante: `GET /ordenes/mias` y `GET /ordenes/{id}` (SPEC-05 §6.1)."""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.modules.loans.enums import EstadoOrdenEnum
from app.modules.loans.models import OrdenPedido
from tests.conftest import auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"


async def _orden(db, usuario, estado=EstadoOrdenEnum.PENDIENTE) -> OrdenPedido:
    """Inserta una orden sin líneas: alcanza para probar propiedad, filtros y paginación."""
    orden = OrdenPedido(
        solicitante_id=usuario._cache_auth["id"],  # type: ignore[attr-defined]
        sede=SedeEnum.USHUAIA,
        estado=estado,
    )
    db.add(orden)
    await db.commit()
    return orden


# ── GET /ordenes/mias ────────────────────────────────────────────────────────


async def test_mias_devuelve_solo_las_propias(client, db, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    beto = await crear_usuario(RolUsuario.ESTUDIANTE)
    propias = [await _orden(db, ana), await _orden(db, ana)]
    await _orden(db, beto)

    r = await client.get(f"{BASE}/ordenes/mias", headers=auth(ana))

    assert r.status_code == 200
    assert {o["id"] for o in r.json()} == {o.id for o in propias}


async def test_mias_tambien_la_ve_un_docente(client, db, crear_usuario):  # AC-L16
    docente = await crear_usuario(RolUsuario.DOCENTE)
    orden = await _orden(db, docente)
    r = await client.get(f"{BASE}/ordenes/mias", headers=auth(docente))
    assert [o["id"] for o in r.json()] == [orden.id]


async def test_mias_sin_ordenes_devuelve_lista_vacia(client, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    r = await client.get(f"{BASE}/ordenes/mias", headers=auth(ana))
    assert r.status_code == 200
    assert r.json() == []


async def test_mias_filtra_por_estado(client, db, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    await _orden(db, ana, EstadoOrdenEnum.PENDIENTE)
    cancelada = await _orden(db, ana, EstadoOrdenEnum.CANCELADA)

    r = await client.get(f"{BASE}/ordenes/mias", params={"estado": "cancelada"}, headers=auth(ana))

    assert [o["id"] for o in r.json()] == [cancelada.id]


async def test_mias_ordena_de_la_mas_nueva_a_la_mas_vieja(client, db, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    ids = [(await _orden(db, ana)).id for _ in range(3)]

    r = await client.get(f"{BASE}/ordenes/mias", headers=auth(ana))

    assert [o["id"] for o in r.json()] == sorted(ids, reverse=True)


async def test_mias_pagina_con_limit_y_offset(client, db, crear_usuario):  # AC-L18
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    ids = sorted([(await _orden(db, ana)).id for _ in range(3)], reverse=True)

    primera = await client.get(f"{BASE}/ordenes/mias", params={"limit": 2}, headers=auth(ana))
    resto = await client.get(
        f"{BASE}/ordenes/mias", params={"limit": 2, "offset": 2}, headers=auth(ana)
    )

    assert [o["id"] for o in primera.json()] == ids[:2]
    assert [o["id"] for o in resto.json()] == ids[2:]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
async def test_mias_rechaza_paginacion_invalida(client, crear_usuario, params):  # AC-L18
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    r = await client.get(f"{BASE}/ordenes/mias", params=params, headers=auth(ana))
    assert r.status_code == 422


# ── GET /ordenes/{id} ────────────────────────────────────────────────────────


async def test_detalle_de_una_orden_propia(client, db, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    orden = await _orden(db, ana)

    r = await client.get(f"{BASE}/ordenes/{orden.id}", headers=auth(ana))

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["id"] == orden.id
    assert cuerpo["solicitante_id"] == ana._cache_auth["id"]  # type: ignore[attr-defined]
    assert cuerpo["sede"] == "Ushuaia"
    assert cuerpo["estado"] == "pendiente"
    assert cuerpo["detalles"] == []
    assert cuerpo["demorado"] is False
    assert cuerpo["resuelto_en"] is None
    assert cuerpo["solicitante"] is None  # el dueño no recibe su propio resumen (T2.2)


async def test_detalle_de_una_orden_ajena_responde_404(client, db, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    beto = await crear_usuario(RolUsuario.ESTUDIANTE)
    orden_de_beto = await _orden(db, beto)

    r = await client.get(f"{BASE}/ordenes/{orden_de_beto.id}", headers=auth(ana))

    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"


async def test_detalle_de_una_orden_inexistente_responde_404(client, crear_usuario):  # AC-L16
    ana = await crear_usuario(RolUsuario.ESTUDIANTE)
    r = await client.get(f"{BASE}/ordenes/999999", headers=auth(ana))
    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"
