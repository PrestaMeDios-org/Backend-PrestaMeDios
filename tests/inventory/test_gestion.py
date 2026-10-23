"""SPEC-04 · Altas, edición, baja lógica y estados (PRE-12, PRE-14, PRE-19) — INV-09…INV-21."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.enums import RolUsuario, SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum as E
from app.modules.inventory.models import UnidadFisica
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/inventory"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE

EQUIPO = {"codigo": "CAM-001", "nombre": "Cámara", "marca": "Sony", "modelo": "A7", "categoria_id": "cameras"}


async def _unidad_id(db, codigo_inventario: str) -> int:
    from sqlalchemy import select

    return await db.scalar(
        select(UnidadFisica.id).where(UnidadFisica.codigo_inventario == codigo_inventario)
    )


async def _estado(db, unidad_id: int) -> E:
    await db.rollback()
    return await db.scalar(
        text("SELECT estado FROM unidades_fisicas WHERE id = :i"), {"i": unidad_id}
    )


# ── Altas (PRE-19) ───────────────────────────────────────────────────────────

_ESCRITURAS = [
    ("post", "/categorias", {"id": "x", "nombre": "X"}),
    ("post", "/equipamiento", {"codigo": "A", "nombre": "A", "marca": "A", "modelo": "A", "categoria_id": "x"}),
    ("post", "/equipamiento/1/unidades", {"numero_serie": "a", "codigo_inventario": "a"}),
    ("patch", "/equipamiento/1", {"nombre": "Z"}),
    ("patch", "/equipamiento/1/estado", {"activo": False}),
    ("patch", "/unidades/1", {"locker": 1}),
    ("patch", "/unidades/1/estado", {"estado": "mantenimiento"}),
]


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
@pytest.mark.parametrize(("metodo", "ruta", "cuerpo"), _ESCRITURAS)
async def test_no_admins_no_escriben(client, db, crear_usuario, rol, metodo, ruta, cuerpo):  # INV-11
    u = await crear_usuario(rol, USH)
    r = await getattr(client, metodo)(f"{B}{ruta}", json=cuerpo, headers=auth(u))
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


async def test_altas_concurrentes_con_la_misma_serie(client, crear_equipo, crear_usuario):  # INV-12
    eq = await crear_equipo("CAM-1", unidades=())
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    cuerpo = {"numero_serie": "SN-DUP", "codigo_inventario": "INV-A"}
    respuestas = await asyncio.gather(
        client.post(f"{B}/equipamiento/{eq.id}/unidades", json=cuerpo, headers=auth(admin)),
        client.post(
            f"{B}/equipamiento/{eq.id}/unidades",
            json={**cuerpo, "codigo_inventario": "INV-B"},
            headers=auth(admin),
        ),
    )
    assert sorted(r.status_code for r in respuestas) == [201, 409]
    assert next(r for r in respuestas if r.status_code == 409).json()["code"] == "INVENTARIO_DUPLICADO"


async def test_codigo_de_equipamiento_duplicado(client, crear_equipo, crear_usuario):  # INV-12
    await crear_equipo("CAM-001")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.post(f"{B}/equipamiento", json=EQUIPO, headers=auth(admin))
    assert r.status_code == 409 and r.json()["code"] == "INVENTARIO_DUPLICADO"


async def test_plazo_de_notebooks_desde_config(
    client, db, crear_equipo, crear_usuario, set_parametro
):  # INV-13
    await crear_equipo("BASE")  # crea la categoría "cameras"
    await set_parametro("prestamo.general.max_dias", 3)
    await set_parametro("prestamo.notebook.max_dias", 12)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.post(f"{B}/equipamiento", json={**EQUIPO, "es_notebook": True}, headers=auth(admin))
    assert r.status_code == 201 and r.json()["max_dias_prestamo"] == 12 and r.json()["es_notebook"]
    r = await client.post(f"{B}/equipamiento", json={**EQUIPO, "codigo": "CAM-2"}, headers=auth(admin))
    assert r.json()["max_dias_prestamo"] == 3 and r.json()["es_notebook"] is False
    r = await client.post(
        f"{B}/equipamiento",
        json={**EQUIPO, "codigo": "NB-2", "es_notebook": True, "max_dias_prestamo": 9},
        headers=auth(admin),
    )
    assert r.json()["max_dias_prestamo"] == 9


@pytest.mark.parametrize("locker", [0, 8, -1])
async def test_locker_fuera_de_rango_en_api(client, crear_equipo, crear_usuario, locker):  # INV-14
    eq = await crear_equipo("CAM-1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.post(
        f"{B}/equipamiento/{eq.id}/unidades",
        json={"numero_serie": "s", "codigo_inventario": "i", "locker": locker},
        headers=auth(admin),
    )
    assert r.status_code == 422


async def test_locker_fuera_de_rango_en_la_base(db, crear_equipo):  # INV-14
    eq = await crear_equipo("CAM-1")
    db.add(UnidadFisica(equipamiento_id=eq.id, numero_serie="s", codigo_inventario="i", sede=USH, locker=8))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


# ── Edición de equipamiento (PRE-12) ─────────────────────────────────────────


async def test_editar_equipamiento(client, crear_equipo, crear_usuario):  # INV-15
    eq = await crear_equipo("CAM-1", unidades=((USH,),))
    await crear_equipo("MIC-1", categoria="audio")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    url = f"{B}/equipamiento/{eq.id}"
    r = await client.patch(
        url,
        json={"nombre": "Nuevo", "categoria_id": "audio", "alta_gama": True, "descripcion": None,
              "reglas_cuidado": ["No mojar"], "max_dias_prestamo": 6},
        headers=auth(admin),
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert (cuerpo["nombre"], cuerpo["categoria_id"], cuerpo["alta_gama"]) == ("Nuevo", "audio", True)
    assert cuerpo["codigo"] == "CAM-1" and cuerpo["marca"] == "Sony"  # lo no enviado no cambia
    assert (cuerpo["max_dias_prestamo"], cuerpo["reglas_cuidado"]) == (6, ["No mojar"])

    for invalido in ({"codigo": "OTRO"}, {"sede": "Ushuaia"}, {"activo": False}, {"nombre": None}):
        r = await client.patch(url, json=invalido, headers=auth(admin))
        assert r.status_code == 422, invalido
    r = await client.patch(url, json={"categoria_id": "nada"}, headers=auth(admin))
    assert r.status_code == 422 and r.json()["code"] == "CATEGORIA_INEXISTENTE"
    r = await client.patch(f"{B}/equipamiento/999", json={"nombre": "x"}, headers=auth(admin))
    assert r.status_code == 404 and r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"


async def test_editar_equipamiento_de_otra_sede(client, crear_equipo, crear_usuario):  # INV-15, INV-20
    solo_rg = await crear_equipo("TRI-1", "Trípode", unidades=((RG,),))
    ambas = await crear_equipo("CAM-1", unidades=((USH,), (RG,)))
    sin_unidades = await crear_equipo("NEW-1", "Nuevo")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/equipamiento/{solo_rg.id}", json={"nombre": "X"}, headers=auth(admin))
    assert r.status_code == 404
    r = await client.patch(f"{B}/equipamiento/{ambas.id}", json={"nombre": "Editado"}, headers=auth(admin))
    assert r.status_code == 200
    assert [u["sede"] for u in r.json()["unidades"]] == ["Ushuaia"]  # sólo lo visible
    r = await client.patch(f"{B}/equipamiento/{sin_unidades.id}", json={"nombre": "Y"}, headers=auth(admin))
    assert r.status_code == 200


# ── Baja lógica (RN-I5, D-06) ────────────────────────────────────────────────


async def test_baja_y_reactivacion(client, crear_equipo, crear_usuario):  # INV-16
    eq = await crear_equipo("CAM-1", unidades=((USH,),))
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    url = f"{B}/equipamiento/{eq.id}/estado"
    r = await client.patch(url, json={"activo": False}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["activo"] is False
    r = await client.patch(url, json={"activo": True}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["activo"] is True


async def test_baja_con_unidades_prestadas(client, crear_equipo, crear_usuario):  # INV-16
    eq = await crear_equipo("CAM-1", unidades=((USH,), (USH, E.PRESTADO)))
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/equipamiento/{eq.id}/estado", json={"activo": False}, headers=auth(admin))
    assert r.status_code == 409 and r.json()["code"] == "EQUIPAMIENTO_CON_PRESTAMOS"


async def test_baja_con_unidades_en_ambas_sedes(client, crear_equipo, crear_usuario):  # INV-16, D-06
    eq = await crear_equipo("CAM-1", unidades=((USH,), (RG,)))
    url = f"{B}/equipamiento/{eq.id}/estado"
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(url, json={"activo": False}, headers=auth(admin))
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.patch(url, json={"activo": False}, headers=auth(sa))
    assert r.status_code == 200 and r.json()["activo"] is False


# ── Edición de unidades (PRE-12) ─────────────────────────────────────────────


async def test_editar_unidad(client, db, crear_equipo, crear_usuario):  # INV-17
    await crear_equipo("CAM-1", unidades=((USH, E.DISPONIBLE, 3), (USH,)))
    primera = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(
        f"{B}/unidades/{primera}",
        json={"numero_serie": "NUEVA", "codigo_inventario": "CAM-S-99", "locker": 5},
        headers=auth(admin),
    )
    assert r.status_code == 200
    assert (r.json()["numero_serie"], r.json()["codigo_inventario"], r.json()["locker"]) == ("NUEVA", "CAM-S-99", 5)
    assert r.json()["sede"] == "Ushuaia" and r.json()["estado"] == "disponible"
    r = await client.patch(f"{B}/unidades/{primera}", json={"locker": None}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["locker"] is None
    for invalido in ({"sede": "Río Grande"}, {"estado": "baja"}, {"locker": 8}, {"numero_serie": None}):
        r = await client.patch(f"{B}/unidades/{primera}", json=invalido, headers=auth(admin))
        assert r.status_code == 422, invalido
    r = await client.patch(f"{B}/unidades/{primera}", json={"codigo_inventario": "CAM-1-U2"}, headers=auth(admin))
    assert r.status_code == 409 and r.json()["code"] == "INVENTARIO_DUPLICADO"


async def test_unidad_de_otra_sede(client, db, crear_equipo, crear_usuario):  # INV-20
    await crear_equipo("CAM-1", unidades=((RG,),))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    for ruta, cuerpo in ((f"/unidades/{uid}", {"locker": 1}), (f"/unidades/{uid}/estado", {"estado": "baja"})):
        r = await client.patch(f"{B}{ruta}", json=cuerpo, headers=auth(admin))
        assert r.status_code == 404 and r.json()["code"] == "UNIDAD_NO_ENCONTRADA"
    assert (await client.get(f"{B}/unidades", headers=auth(admin))).json() == []


# ── Estados (PRE-14) ─────────────────────────────────────────────────────────

_PERMITIDAS = [
    (E.DISPONIBLE, E.MANTENIMIENTO), (E.DISPONIBLE, E.BAJA),
    (E.MANTENIMIENTO, E.DISPONIBLE), (E.MANTENIMIENTO, E.BAJA),
]
_CONFLICTO = [
    (E.PRESTADO, E.DISPONIBLE), (E.PRESTADO, E.MANTENIMIENTO), (E.PRESTADO, E.BAJA),
    (E.BAJA, E.DISPONIBLE), (E.BAJA, E.MANTENIMIENTO),
]


@pytest.mark.parametrize(("desde", "hacia"), _PERMITIDAS)
async def test_transiciones_permitidas(client, db, crear_equipo, crear_usuario, desde, hacia):  # INV-18
    await crear_equipo("CAM-1", unidades=((USH, desde),))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/unidades/{uid}/estado", json={"estado": hacia}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["estado"] == hacia


async def test_mantenimiento_baja_el_stock_disponible(client, db, crear_equipo, crear_usuario):  # INV-18
    eq = await crear_equipo("CAM-1", unidades=((USH,), (USH,)))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    await client.patch(f"{B}/unidades/{uid}/estado", json={"estado": "mantenimiento"}, headers=auth(admin))
    est = await crear_usuario(R.ESTUDIANTE, USH)
    item = (await client.get(f"{B}/equipamiento/{eq.id}", headers=auth(est))).json()
    assert (item["cantidad_total"], item["cantidad_disponible"], item["en_mantenimiento"]) == (2, 1, False)


@pytest.mark.parametrize(("desde", "hacia"), _CONFLICTO)
async def test_transiciones_invalidas(client, db, crear_equipo, crear_usuario, desde, hacia):  # INV-19
    await crear_equipo("CAM-1", unidades=((USH, desde),))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/unidades/{uid}/estado", json={"estado": hacia}, headers=auth(admin))
    assert r.status_code == 409 and r.json()["code"] == "TRANSICION_ESTADO_INVALIDA"
    assert await _estado(db, uid) == desde


async def test_prestado_no_se_acepta_por_api(client, db, crear_equipo, crear_usuario):  # INV-19
    await crear_equipo("CAM-1", unidades=((USH,),))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/unidades/{uid}/estado", json={"estado": "prestado"}, headers=auth(admin))
    assert r.status_code == 422 and r.json()["code"] == "ESTADO_NO_PERMITIDO"
    assert await _estado(db, uid) == E.DISPONIBLE


async def test_mismo_estado_es_idempotente(client, db, crear_equipo, crear_usuario):  # INV-18
    await crear_equipo("CAM-1", unidades=((USH, E.BAJA),))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/unidades/{uid}/estado", json={"estado": "baja"}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["estado"] == "baja"


async def test_cambios_concurrentes_de_estado(client, db, crear_equipo, crear_usuario):  # INV-21
    await crear_equipo("CAM-1", unidades=((USH,),))
    uid = await _unidad_id(db, "CAM-1-U1")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    h = auth(admin)
    respuestas = await asyncio.gather(
        client.patch(f"{B}/unidades/{uid}/estado", json={"estado": "baja"}, headers=h),
        client.patch(f"{B}/unidades/{uid}/estado", json={"estado": "disponible"}, headers=h),
        client.patch(f"{B}/unidades/{uid}/estado", json={"estado": "mantenimiento"}, headers=h),
    )
    assert all(r.status_code in (200, 409) for r in respuestas)
    # Con `baja` terminal, el resultado depende del orden pero nunca queda incoherente:
    # si `baja` se aplicó, la unidad no puede haber vuelto a otro estado.
    final = await _estado(db, uid)
    estados_ok = [r.json()["estado"] for r in respuestas if r.status_code == 200]
    if "baja" in estados_ok:
        assert final == E.BAJA
    assert final in (E.BAJA, E.MANTENIMIENTO, E.DISPONIBLE)

