"""SPEC-04 · Lectura del catálogo (PRE-01, PRE-02) — INV-02…INV-08."""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum as E
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/inventory"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


@pytest.fixture
async def catalogo(crear_equipo):
    camara = await crear_equipo(
        "CAM-1", "Cámara Sony", unidades=((USH, E.DISPONIBLE, 2), (RG, E.DISPONIBLE, 5))
    )
    tripode = await crear_equipo(
        "TRI-1", "Trípode", categoria="soporte", marca="Manfrotto", unidades=((RG,),)
    )
    return {"camara": camara.id, "tripode": tripode.id}


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
async def test_alcance_de_sede_en_lectura(client, catalogo, crear_usuario, rol):  # INV-02
    u = await crear_usuario(rol, USH)
    items = (await client.get(f"{B}/equipamiento", headers=auth(u))).json()
    assert [i["codigo"] for i in items] == ["CAM-1"]
    r = await client.get(f"{B}/equipamiento", params={"sede": "Río Grande"}, headers=auth(u))
    assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"


async def test_superadmin_ambas_sedes_o_una(client, catalogo, crear_usuario):  # INV-03
    sa = await crear_usuario(R.SUPERADMIN)
    todos = (await client.get(f"{B}/equipamiento", headers=auth(sa))).json()
    assert {i["codigo"] for i in todos} == {"CAM-1", "TRI-1"}
    ush = (await client.get(f"{B}/equipamiento", params={"sede": "Ushuaia"}, headers=auth(sa))).json()
    assert [i["codigo"] for i in ush] == ["CAM-1"]
    assert [u["sede"] for u in ush[0]["unidades"]] == ["Ushuaia"]


async def test_filtros_y_busqueda(client, catalogo, crear_equipo, crear_usuario):  # INV-04
    await crear_equipo("MIC_1", "Micrófono 100%", categoria="audio", marca="Rode", unidades=((RG,),))
    sa = await crear_usuario(R.SUPERADMIN)
    h = auth(sa)

    async def codigos(**params):
        r = await client.get(f"{B}/equipamiento", params=params, headers=h)
        assert r.status_code == 200
        return {i["codigo"] for i in r.json()}

    assert await codigos(categoria="soporte") == {"TRI-1"}
    assert await codigos(q="sony") == {"CAM-1"}  # marca
    assert await codigos(q="tri-1") == {"TRI-1"}  # código
    assert await codigos(q="trípode") == {"TRI-1"}  # nombre
    assert await codigos(q="%") == {"MIC_1"}  # comodín literal
    assert await codigos(q="_") == {"MIC_1"}
    assert await codigos(q="no-existe") == set()
    assert await codigos(categoria="audio", q="sony") == set()


async def test_vista_reducida_para_estudiante_y_docente(
    client, catalogo, crear_usuario
):  # INV-05
    for rol in (R.ESTUDIANTE, R.DOCENTE):
        u = await crear_usuario(rol, USH)
        item = (await client.get(f"{B}/equipamiento", headers=auth(u))).json()[0]
        assert not {"unidades", "numero_serie", "codigo_inventario"} & item.keys()
        assert item["locker"] == 2
        assert item["cantidad_total"] == 1 and item["cantidad_disponible"] == 1
        detalle = (await client.get(f"{B}/equipamiento/{catalogo['camara']}", headers=auth(u))).json()
        assert "unidades" not in detalle and detalle["locker"] == 2
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    item = (await client.get(f"{B}/equipamiento", headers=auth(admin))).json()[0]
    assert item["unidades"][0]["numero_serie"] == "CAM-1-SN1"


async def test_locker_nulo_si_las_unidades_difieren(client, crear_equipo, crear_usuario):  # INV-05
    await crear_equipo("CAM-2", "Cámara 2", unidades=((USH, E.DISPONIBLE, 1), (USH, E.DISPONIBLE, 3)))
    est = await crear_usuario(R.ESTUDIANTE, USH)
    item = (await client.get(f"{B}/equipamiento", headers=auth(est))).json()[0]
    assert item["locker"] is None


async def test_items_inactivos(client, catalogo, crear_usuario):  # INV-06
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.patch(
        f"{B}/equipamiento/{catalogo['camara']}/estado", json={"activo": False}, headers=auth(sa)
    )
    assert r.status_code == 200
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    est = await crear_usuario(R.ESTUDIANTE, USH)
    assert (await client.get(f"{B}/equipamiento", headers=auth(est))).json() == []
    r = await client.get(f"{B}/equipamiento", params={"incluir_inactivos": "true"}, headers=auth(est))
    assert r.json() == []  # el parámetro se ignora para no administradores
    r = await client.get(f"{B}/equipamiento/{catalogo['camara']}", headers=auth(est))
    assert r.status_code == 404
    assert (await client.get(f"{B}/equipamiento", headers=auth(admin))).json() == []
    r = await client.get(f"{B}/equipamiento", params={"incluir_inactivos": "true"}, headers=auth(admin))
    assert [i["codigo"] for i in r.json()] == ["CAM-1"] and r.json()[0]["activo"] is False
    r = await client.get(f"{B}/equipamiento/{catalogo['camara']}", headers=auth(admin))
    assert r.status_code == 200


async def test_detalle_fuera_de_la_sede(client, catalogo, crear_usuario):  # INV-07
    est = await crear_usuario(R.ESTUDIANTE, USH)
    r = await client.get(f"{B}/equipamiento/{catalogo['tripode']}", headers=auth(est))
    assert r.status_code == 404 and r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"


async def test_campos_calculados(client, crear_equipo, crear_usuario):  # INV-08
    await crear_equipo(
        "MIX", "Mixto",
        unidades=((USH, E.DISPONIBLE), (USH, E.MANTENIMIENTO), (USH, E.PRESTADO), (USH, E.BAJA)),
    )
    await crear_equipo("MNT", "Taller", unidades=((USH, E.MANTENIMIENTO), (USH, E.BAJA)))
    await crear_equipo("OFF", "Descartado", unidades=((USH, E.BAJA),))
    est = await crear_usuario(R.ESTUDIANTE, USH)
    items = {i["codigo"]: i for i in (await client.get(f"{B}/equipamiento", headers=auth(est))).json()}
    assert (items["MIX"]["cantidad_total"], items["MIX"]["cantidad_disponible"]) == (3, 1)
    assert items["MIX"]["en_mantenimiento"] is False
    assert (items["MNT"]["cantidad_total"], items["MNT"]["en_mantenimiento"]) == (1, True)
    assert (items["OFF"]["cantidad_total"], items["OFF"]["en_mantenimiento"]) == (0, False)
