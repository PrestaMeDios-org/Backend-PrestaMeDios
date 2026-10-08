"""UC-05 · Directorio con aislamiento de sede (USR-04, GLO-01) — AC-20…AC-24, EC-07…EC-10."""

import pytest

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from tests.conftest import auth

pytestmark = pytest.mark.integracion

URL = "/api/v1/users"
R, E = RolUsuario, EstadoCuenta
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


@pytest.fixture
async def poblacion(crear_usuario):
    """3 usuarios en Ushuaia (incluye al admin local), 2 en Río Grande y 1 SUPERADMIN."""
    admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH, apellido="Alvarez")
    await crear_usuario(R.ESTUDIANTE, USH, E.PENDIENTE_APROBACION, apellido="Benitez")
    await crear_usuario(R.DOCENTE, USH, E.PENDIENTE_APROBACION, apellido="Castro")
    await crear_usuario(R.ESTUDIANTE, RG, apellido="Diaz")
    await crear_usuario(R.DOCENTE, RG, E.PENDIENTE_APROBACION, apellido="Echeverria")
    superadmin = await crear_usuario(R.SUPERADMIN, apellido="Ader")
    return {"admin_ush": admin_ush, "superadmin": superadmin}


async def _get(client, actor, **params):
    return await client.get(URL, params=params, headers=auth(actor))


async def test_aislamiento_admin_local(client, poblacion):  # AC-20, EC-07
    admin = poblacion["admin_ush"]
    r = await _get(client, admin)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert {u["sede"] for u in body["items"]} == {"Ushuaia"}

    r_propia = await _get(client, admin, sede="Ushuaia")
    assert r_propia.json()["total"] == 3

    r_ajena = await _get(client, admin, sede="Río Grande")
    assert r_ajena.status_code == 403 and r_ajena.json()["code"] == "SEDE_FUERA_DE_ALCANCE"


async def test_vista_superadmin(client, poblacion):  # AC-21, EC-10
    sa = poblacion["superadmin"]
    assert (await _get(client, sa)).json()["total"] == 6
    rg = (await _get(client, sa, sede="Río Grande")).json()
    assert rg["total"] == 2
    assert all(u["rol"] != "SUPERADMIN" for u in rg["items"])


async def test_filtros_combinados_bandeja(client, poblacion):  # AC-22
    r = await _get(client, poblacion["admin_ush"], estado="PENDIENTE_APROBACION", rol="DOCENTE")
    items = r.json()["items"]
    assert [u["apellido"] for u in items] == ["Castro"]

    r_sa = await _get(client, poblacion["superadmin"], estado="PENDIENTE_APROBACION")
    assert r_sa.json()["total"] == 3


async def test_admin_local_buscando_superadmins(client, poblacion):  # EC-09
    r = await _get(client, poblacion["admin_ush"], rol="SUPERADMIN")
    assert r.status_code == 200 and r.json()["total"] == 0


async def test_busqueda_literal(client, crear_usuario):  # AC-23
    sa = await crear_usuario(R.SUPERADMIN)
    await crear_usuario(apellido="Ciento%Uno")
    await crear_usuario(apellido="Normal")
    r = await _get(client, sa, q="%U")
    assert [u["apellido"] for u in r.json()["items"]] == ["Ciento%Uno"]
    r2 = await _get(client, sa, q="_o")
    assert r2.json()["total"] == 0


async def test_busqueda_por_nombre_email_y_dni(client, crear_usuario):
    sa = await crear_usuario(R.SUPERADMIN)
    u = await crear_usuario(nombre="Joaquín", email="jota@untdf.edu.ar")
    for q in ("joaq", "JOTA@", u.dni[:5]):
        ids = [i["id"] for i in (await _get(client, sa, q=q)).json()["items"]]
        assert u.id in ids, q


async def test_paginacion_y_orden(client, poblacion):  # AC-23
    sa = poblacion["superadmin"]
    p2 = (await _get(client, sa, limit=2, offset=2)).json()
    assert p2["total"] == 6 and p2["limit"] == 2 and p2["offset"] == 2
    assert [u["apellido"] for u in p2["items"]] == ["Benitez", "Castro"]

    desc = (await _get(client, sa, direccion="desc", limit=1)).json()
    assert desc["items"][0]["apellido"] == "Echeverria"

    assert (await _get(client, sa, limit=101)).status_code == 422
    assert (await _get(client, sa, offset=-1)).status_code == 422
    assert (await _get(client, sa, q="a")).status_code == 422


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
async def test_roles_sin_acceso(client, crear_usuario, rol):  # AC-24
    u = await crear_usuario(rol, USH)
    r = await _get(client, u)
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


async def test_detalle_no_expone_hash(client, poblacion, crear_usuario):
    u = await crear_usuario(R.ESTUDIANTE, USH)
    r = await client.get(f"{URL}/{u.id}", headers=auth(poblacion["admin_ush"]))
    assert r.status_code == 200
    assert "password_hash" not in r.json() and r.json()["dni"] == u.dni


async def test_sin_resultados(client, crear_usuario):  # UC-05 FA-01
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _get(client, sa, q="inexistente")
    assert r.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
