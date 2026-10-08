"""UC-03/UC-04 · Login JWT y sesión (USR-01) — AC-15…AC-19, EC-01…EC-06, EC-14, EC-16."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.modules.users.models import Usuario, UsuarioHistorialEstado
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.integracion

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


async def _login(client, email: str, password: str = PASSWORD):
    return await client.post(LOGIN, json={"email": email, "password": password})


async def test_login_exitoso_y_me(client, db, crear_usuario):  # AC-15
    u = await crear_usuario(RolUsuario.ADMIN_LOCAL, SedeEnum.RIO_GRANDE)
    r = await _login(client, u.email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 3600
    assert body["usuario"]["id"] == u.id and body["usuario"]["rol"] == "ADMIN_LOCAL"
    assert body["usuario"]["sede"] == "Río Grande"
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert {"sub", "rol", "sede", "tv", "iss", "iat", "exp", "jti"} <= set(claims)

    me = await client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["id"] == u.id

    await db.refresh(u)
    assert u.ultimo_login_en is not None


async def test_email_con_mayusculas_y_espacios(client, crear_usuario):  # EC-14
    await crear_usuario(email="ana.gomez@untdf.edu.ar")
    assert (await _login(client, "  Ana.GOMEZ@untdf.EDU.ar ")).status_code == 200


@pytest.mark.parametrize("estado", list(EstadoCuenta))
async def test_credenciales_invalidas_indistinguibles(client, crear_usuario, estado):  # AC-16, EC-02
    u = await crear_usuario(estado=estado)
    r_mala = await _login(client, u.email, "ClaveIncorrecta1")
    r_inexistente = await _login(client, "nadie@untdf.edu.ar", "ClaveIncorrecta1")
    for r in (r_mala, r_inexistente):
        assert r.status_code == 401
        assert r.json() == {"detail": "Email o contraseña incorrectos.", "code": "CREDENCIALES_INVALIDAS"}


@pytest.mark.parametrize(
    ("estado", "codigo"),
    [
        (EstadoCuenta.PENDIENTE_APROBACION, "CUENTA_PENDIENTE_APROBACION"),
        (EstadoCuenta.RECHAZADO, "CUENTA_RECHAZADA"),
        (EstadoCuenta.INACTIVO, "CUENTA_INACTIVA"),
    ],
)
async def test_cuentas_no_activas(client, crear_usuario, estado, codigo):  # AC-17, EC-03
    u = await crear_usuario(estado=estado)
    r = await _login(client, u.email)
    assert r.status_code == 403
    assert r.json()["code"] == codigo
    assert "access_token" not in r.json()


async def test_sancionado_vigente(client, crear_usuario):  # AC-17, EC-01
    hasta = datetime.now(UTC) + timedelta(days=7)
    u = await crear_usuario(estado=EstadoCuenta.SUSPENDIDO, suspendido_hasta=hasta)
    r = await _login(client, u.email)
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "CUENTA_SUSPENDIDA"
    assert datetime.fromisoformat(body["suspendido_hasta"]) == hasta
    assert "access_token" not in body


async def test_suspension_indefinida(client, crear_usuario):  # EC-06
    u = await crear_usuario(estado=EstadoCuenta.SUSPENDIDO)
    r = await _login(client, u.email)
    assert r.status_code == 403
    assert r.json()["code"] == "CUENTA_SUSPENDIDA" and r.json()["suspendido_hasta"] is None


async def test_fin_automatico_de_sancion(client, db, crear_usuario):  # AC-18, EC-05
    u = await crear_usuario(
        estado=EstadoCuenta.SUSPENDIDO, suspendido_hasta=datetime.now(UTC) - timedelta(minutes=1)
    )
    u_id = u.id
    r = await _login(client, u.email)
    assert r.status_code == 200, r.text

    db.expire_all()
    actualizado = await db.get(Usuario, u_id)
    assert actualizado.estado == EstadoCuenta.ACTIVO and actualizado.suspendido_hasta is None
    hist = (
        await db.scalars(
            select(UsuarioHistorialEstado).where(UsuarioHistorialEstado.usuario_id == u_id)
        )
    ).all()
    assert [(h.estado_anterior, h.estado_nuevo, h.actor_id) for h in hist] == [
        (EstadoCuenta.SUSPENDIDO, EstadoCuenta.ACTIVO, None)
    ]


class TestTokens:  # AC-19, EC-15, EC-16
    async def test_sin_header(self, client):
        r = await client.get(ME)
        assert r.status_code == 401
        assert r.json()["code"] == "NO_AUTENTICADO"
        assert r.headers["www-authenticate"] == "Bearer"

    async def test_esquema_distinto_de_bearer(self, client):
        r = await client.get(ME, headers={"Authorization": "Basic YWJjOmRlZg=="})
        assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"

    async def test_token_alterado(self, client, crear_usuario):
        u = await crear_usuario()
        token = auth(u)["Authorization"] + "x"
        r = await client.get(ME, headers={"Authorization": token})
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_INVALIDO"

    async def test_usuario_inexistente(self, client, db, crear_usuario):  # EC-16
        u = await crear_usuario()
        headers = auth(u)
        await db.delete(u)
        await db.commit()
        r = await client.get(ME, headers=headers)
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_INVALIDO"

    async def test_token_version_desfasada(self, client, db, crear_usuario):
        u = await crear_usuario()
        headers = auth(u)
        u.token_version += 1
        await db.commit()
        r = await client.get(ME, headers=headers)
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_REVOCADO"

    async def test_me_lee_datos_vigentes_de_la_base(self, client, db, crear_usuario):  # EC-11
        u = await crear_usuario(nombre="Ana")
        headers = auth(u)
        u.nombre = "Analía"
        await db.commit()
        r = await client.get(ME, headers=headers)
        assert r.json()["nombre"] == "Analía"
