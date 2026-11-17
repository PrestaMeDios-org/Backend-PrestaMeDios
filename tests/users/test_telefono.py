"""SPEC-09 Fase B · teléfono obligatorio (USR-05, ADR-022 b, D-16 de SPEC-03).

AC-113…AC-119; EC-58 y EC-59. Las cuentas que crea ``crear_usuario`` no tienen
teléfono: son las "cuentas viejas" de RN-87.
"""

import sys

import pytest
from sqlalchemy import func, select

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.modules.users import cli
from app.modules.users.models import Usuario, UsuarioHistorialCambios
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.integracion

R, E = RolUsuario, EstadoCuenta
REGISTRO = "/api/v1/auth/register"
ME = "/api/v1/auth/me"
USERS = "/api/v1/users"
TELEFONO = "+54 2901 555123"

DATOS_REGISTRO = {
    "email": "nueva.estudiante@untdf.edu.ar",
    "password": "Camara2026!",
    "nombre": "Nadia",
    "apellido": "Estudiante",
    "dni": "42111222",
    "telefono": TELEFONO,
    "rol": "ESTUDIANTE",
    "sede": "Ushuaia",
}
DATOS_ALTA = {
    "email": "nuevo.admin@untdf.edu.ar",
    "password": "Laboratorio1",
    "nombre": "Nicolás",
    "apellido": "Admin",
    "dni": "29111222",
    "telefono": "+54 2964 400100",
    "rol": "ADMIN_LOCAL",
    "sede": "Río Grande",
}


def _sin_telefono(datos: dict) -> dict:
    return {k: v for k, v in datos.items() if k != "telefono"}


async def _cuentas(db) -> int:
    return await db.scalar(select(func.count()).select_from(Usuario))


async def _cambios(db, usuario_id: int) -> list[dict]:
    db.expire_all()
    filas = await db.scalars(
        select(UsuarioHistorialCambios)
        .where(UsuarioHistorialCambios.usuario_id == usuario_id)
        .order_by(UsuarioHistorialCambios.id)
    )
    return [h.cambios for h in filas.all()]


# ── Altas ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("datos", [_sin_telefono(DATOS_REGISTRO), {**DATOS_REGISTRO, "telefono": None}])
async def test_registro_exige_telefono(client, db, datos):  # AC-113, RN-86
    r = await client.post(REGISTRO, json=datos)
    assert r.status_code == 422, r.text
    assert await _cuentas(db) == 0


async def test_registro_con_telefono(client, db):  # AC-113
    r = await client.post(REGISTRO, json=DATOS_REGISTRO)
    assert r.status_code == 201, r.text
    assert (await db.get(Usuario, r.json()["id"])).telefono == TELEFONO


async def test_re_registro_exige_telefono_y_lo_reemplaza(client, db, crear_usuario):  # AC-114, EC-58
    rechazada = await crear_usuario(R.ESTUDIANTE, SedeEnum.USHUAIA, E.RECHAZADO, email=DATOS_REGISTRO["email"])
    rid, dni = rechazada.id, rechazada.dni
    datos = {**DATOS_REGISTRO, "dni": dni}

    r = await client.post(REGISTRO, json=_sin_telefono(datos))
    assert r.status_code == 422, r.text

    r = await client.post(REGISTRO, json={**datos, "telefono": "+54 2901 999000"})
    assert r.status_code == 201, r.text
    assert r.json()["id"] == rid and r.json()["estado"] == "PENDIENTE_APROBACION"
    db.expire_all()
    assert (await db.get(Usuario, rid)).telefono == "+54 2901 999000"


@pytest.mark.parametrize("datos", [_sin_telefono(DATOS_ALTA), {**DATOS_ALTA, "telefono": None}])
async def test_alta_administrativa_exige_telefono(client, db, crear_usuario, datos):  # AC-115
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.post(USERS, json=datos, headers=auth(sa))
    assert r.status_code == 422, r.text
    assert await _cuentas(db) == 1  # sólo el SUPERADMIN


# ── Edición ──────────────────────────────────────────────────────────────────


async def test_mi_perfil_no_borra_el_telefono(client, db, crear_usuario):  # AC-116, RN-88
    u = await crear_usuario()
    uid = u.id
    assert (await client.patch(ME, json={"telefono": TELEFONO}, headers=auth(u))).status_code == 200

    r = await client.patch(ME, json={"telefono": None}, headers=auth(u))
    assert r.status_code == 422, r.text
    assert "teléfono" in r.text

    r = await client.patch(ME, json={"telefono": "+54 2964 111222"}, headers=auth(u))
    assert r.status_code == 200 and r.json()["telefono"] == "+54 2964 111222"
    assert await _cambios(db, uid) == [
        {"telefono": [None, TELEFONO]},
        {"telefono": [TELEFONO, "+54 2964 111222"]},
    ]


async def test_edicion_administrativa_no_borra_el_telefono(client, db, crear_usuario):  # AC-117, RN-88
    admin = await crear_usuario(R.ADMIN_LOCAL, SedeEnum.USHUAIA)
    est = await crear_usuario(R.ESTUDIANTE, SedeEnum.USHUAIA)
    url = f"{USERS}/{est.id}"
    assert (await client.patch(url, json={"telefono": TELEFONO}, headers=auth(admin))).status_code == 200

    r = await client.patch(url, json={"telefono": None}, headers=auth(admin))
    assert r.status_code == 422, r.text
    r = await client.patch(url, json={"nombre": "Analía", "telefono": None}, headers=auth(admin))
    assert r.status_code == 422, r.text


# ── Cuentas viejas sin teléfono (RN-87) ──────────────────────────────────────


async def test_cuenta_sin_telefono_sigue_operando(client, db, crear_usuario):  # AC-118, RN-87, EC-59
    admin = await crear_usuario(R.ADMIN_LOCAL, SedeEnum.USHUAIA)
    vieja = await crear_usuario(R.ESTUDIANTE, SedeEnum.USHUAIA, E.PENDIENTE_APROBACION, email="vieja@untdf.edu.ar")
    activa = await crear_usuario(R.ESTUDIANTE, SedeEnum.USHUAIA, E.ACTIVO, email="activa@untdf.edu.ar")
    vid, aid = vieja.id, activa.id

    # Inicia sesión y ve su perfil sin teléfono.
    login = await client.post("/api/v1/auth/login", json={"email": "activa@untdf.edu.ar", "password": PASSWORD})
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get(ME, headers=h)
    assert me.status_code == 200 and me.json()["telefono"] is None

    # Cambia su email sin tocar el teléfono.
    r = await client.patch(
        ME, json={"email": "activa.nueva@untdf.edu.ar", "password_actual": PASSWORD}, headers=h
    )
    assert r.status_code == 200, r.text

    # Un administrador la edita en otros campos, la aprueba y la suspende.
    r = await client.patch(f"{USERS}/{vid}", json={"nombre": "Vera"}, headers=auth(admin))
    assert r.status_code == 200, r.text
    r = await client.patch(f"{USERS}/{vid}/estado", json={"nuevo_estado": "ACTIVO"}, headers=auth(admin))
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{USERS}/{aid}/estado", json={"nuevo_estado": "SUSPENDIDO", "motivo": "Prueba"}, headers=auth(admin)
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    assert (await db.get(Usuario, vid)).telefono is None
    assert (await db.get(Usuario, aid)).telefono is None


# ── CLI ──────────────────────────────────────────────────────────────────────


def test_crear_superadmin_exige_telefono(monkeypatch, capsys):  # AC-119, D-11
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli", "crear-superadmin", "--email", "sa@untdf.edu.ar", "--nombre", "Sa",
         "--apellido", "Admin", "--dni", "30111222"],
    )
    llamado = False

    async def _no_debe_correr(args):
        nonlocal llamado
        llamado = True
        return 0

    monkeypatch.setattr(cli, "_main", _no_debe_correr)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "--telefono" in capsys.readouterr().err
    assert not llamado
