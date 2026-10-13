"""UC-01 · Autorregistro (USR-01, USR-05) — AC-01…AC-06, EC-12, EC-22."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.modules.users.models import Usuario, UsuarioHistorialEstado

pytestmark = pytest.mark.integracion

URL = "/api/v1/auth/register"
DATOS = {
    "email": "lucia.perez@untdf.edu.ar",
    "password": "Camara2026!",
    "nombre": "Lucía",
    "apellido": "Pérez",
    "dni": "40123456",
    "telefono": "+54 2901 555123",
    "rol": "ESTUDIANTE",
    "sede": "Ushuaia",
}


async def _historial(db, usuario_id: int) -> list[UsuarioHistorialEstado]:
    db.expire_all()
    res = await db.scalars(
        select(UsuarioHistorialEstado)
        .where(UsuarioHistorialEstado.usuario_id == usuario_id)
        .order_by(UsuarioHistorialEstado.id)
    )
    return list(res.all())


async def test_registro_exitoso_queda_pendiente(client, db):  # AC-01
    r = await client.post(URL, json=DATOS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estado"] == "PENDIENTE_APROBACION"
    assert body["rol"] == "ESTUDIANTE" and body["sede"] == "Ushuaia"
    assert "access_token" not in body and "password_hash" not in body and "password" not in body

    usuario = await db.get(Usuario, body["id"])
    assert usuario.password_hash.startswith("$argon2id$")
    assert DATOS["password"] not in usuario.password_hash

    hist = await _historial(db, body["id"])
    assert [(h.estado_anterior, h.estado_nuevo, h.actor_id) for h in hist] == [
        (None, EstadoCuenta.PENDIENTE_APROBACION, None)
    ]


async def test_email_normalizado_y_duplicado(client):  # AC-02
    r = await client.post(URL, json={**DATOS, "email": "  Lucia.PEREZ@UNTDF.edu.ar "})
    assert r.status_code == 201
    assert r.json()["email"] == "lucia.perez@untdf.edu.ar"

    r2 = await client.post(URL, json={**DATOS, "dni": "40999999"})
    assert r2.status_code == 409
    assert r2.json() == {"detail": "Ya existe una cuenta con ese email.", "code": "EMAIL_YA_REGISTRADO"}


async def test_dni_duplicado(client):  # UC-01 FA-02
    assert (await client.post(URL, json=DATOS)).status_code == 201
    r = await client.post(URL, json={**DATOS, "email": "otra@untdf.edu.ar"})
    assert r.status_code == 409 and r.json()["code"] == "DNI_YA_REGISTRADO"


@pytest.mark.parametrize(
    "cambio",
    [{"rol": "ADMIN_LOCAL"}, {"rol": "SUPERADMIN"}, {"estado": "ACTIVO"}, {"token_version": 9}],
)
async def test_no_se_autoasignan_privilegios(client, db, cambio):  # AC-03, EC-22
    r = await client.post(URL, json={**DATOS, **cambio})
    assert r.status_code == 422
    assert await db.scalar(select(func.count()).select_from(Usuario)) == 0


@pytest.mark.parametrize("sede", [None, "Ambas sedes"])
async def test_sede_obligatoria(client, sede):  # AC-04
    assert (await client.post(URL, json={**DATOS, "sede": sede})).status_code == 422


@pytest.mark.parametrize("password", ["abcdefgh", "1234567"])
async def test_password_debil(client, password):  # AC-05
    assert (await client.post(URL, json={**DATOS, "password": password})).status_code == 422


async def test_password_igual_al_email(client):  # AC-05
    datos = {**DATOS, "email": "ana2026@untdf.edu.ar", "password": "ana2026@untdf.edu.ar"}
    assert (await client.post(URL, json=datos)).status_code == 422


async def test_re_registro_tras_rechazo(client, db, crear_usuario):  # AC-06, D-04
    rechazada = await crear_usuario(
        RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA, EstadoCuenta.RECHAZADO, email=DATOS["email"]
    )
    rechazada_dni = rechazada.dni
    r = await client.post(URL, json={**DATOS, "dni": rechazada_dni, "sede": "Río Grande"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == rechazada.id
    assert body["estado"] == "PENDIENTE_APROBACION" and body["sede"] == "Río Grande"

    hist = await _historial(db, rechazada.id)
    assert (hist[-1].estado_anterior, hist[-1].estado_nuevo) == (
        EstadoCuenta.RECHAZADO,
        EstadoCuenta.PENDIENTE_APROBACION,
    )


async def test_re_registro_no_aplica_a_cuentas_activas(client, crear_usuario):
    await crear_usuario(email=DATOS["email"])
    r = await client.post(URL, json=DATOS)
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_YA_REGISTRADO"


async def test_registros_concurrentes_mismo_email(client, db):  # EC-12
    respuestas = await asyncio.gather(
        client.post(URL, json={**DATOS, "dni": "41000001"}),
        client.post(URL, json={**DATOS, "dni": "41000002"}),
    )
    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [201, 409]
    conflicto = next(r for r in respuestas if r.status_code == 409)
    assert conflicto.json()["code"] == "EMAIL_YA_REGISTRADO"
    assert await db.scalar(select(func.count()).select_from(Usuario)) == 1
