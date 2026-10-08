"""SPEC-02 UC-10/UC-11 y cambio obligatorio — AC-46…AC-48, EC-29, EC-30, EC-33."""

import pytest
from sqlalchemy import select

from app.core.enums import RolUsuario, SedeEnum
from app.modules.users.cli import crear_superadmin
from app.modules.users.models import UsuarioHistorialCambios
from app.modules.users.schemas import UsuarioAdminCreate
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.integracion

ME = "/api/v1/auth/me"
PWD = "/api/v1/auth/me/password"
LOGIN = "/api/v1/auth/login"


async def _historial(db, usuario_id):
    db.expire_all()  # usar ids capturados antes: las instancias quedan expiradas
    return (
        await db.scalars(
            select(UsuarioHistorialCambios)
            .where(UsuarioHistorialCambios.usuario_id == usuario_id)
            .order_by(UsuarioHistorialCambios.id)
        )
    ).all()


class TestEditarContacto:  # AC-46
    async def test_telefono(self, client, db, crear_usuario):
        u = await crear_usuario()
        uid = u.id
        r = await client.patch(ME, json={"telefono": "+54 2964 111222"}, headers=auth(u))
        assert r.status_code == 200, r.text
        assert r.json()["telefono"] == "+54 2964 111222"
        (h,) = await _historial(db, uid)
        assert h.cambios == {"telefono": [None, "+54 2964 111222"]} and h.actor_id == uid

    async def test_borrar_telefono(self, client, crear_usuario):
        u = await crear_usuario()
        await client.patch(ME, json={"telefono": "+54 2964 111222"}, headers=auth(u))
        r = await client.patch(ME, json={"telefono": None}, headers=auth(u))
        assert r.status_code == 200 and r.json()["telefono"] is None

    @pytest.mark.parametrize(
        "payload",
        [{"dni": "12345678"}, {"rol": "SUPERADMIN"}, {"sede": "Río Grande"}, {"nombre": "X"}, {}],
    )
    async def test_campos_protegidos_o_vacio(self, client, crear_usuario, payload):
        u = await crear_usuario()
        assert (await client.patch(ME, json=payload, headers=auth(u))).status_code == 422

    async def test_password_actual_sin_email(self, client, crear_usuario):  # EC-30
        u = await crear_usuario()
        r = await client.patch(
            ME, json={"telefono": "123456", "password_actual": PASSWORD}, headers=auth(u)
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("password", [None, "Incorrecta99"])
    async def test_email_requiere_password_correcta(self, client, crear_usuario, password):
        u = await crear_usuario()
        payload = {"email": "nuevo@gmail.com"}
        if password:
            payload["password_actual"] = password
        r = await client.patch(ME, json=payload, headers=auth(u))
        assert r.status_code == 403 and r.json()["code"] == "PASSWORD_ACTUAL_INCORRECTA"

    async def test_cambio_de_email_y_login(self, client, crear_usuario):  # EC-29
        u = await crear_usuario()
        r = await client.patch(
            ME,
            json={"email": "  Nuevo.Mail@Gmail.com ", "password_actual": PASSWORD},
            headers=auth(u),
        )
        assert r.status_code == 200 and r.json()["email"] == "nuevo.mail@gmail.com"
        login = await client.post(LOGIN, json={"email": "NUEVO.mail@gmail.com", "password": PASSWORD})
        assert login.status_code == 200

    async def test_email_ajeno(self, client, crear_usuario):
        await crear_usuario(email="ocupado@untdf.edu.ar")
        u = await crear_usuario()
        r = await client.patch(
            ME, json={"email": "ocupado@untdf.edu.ar", "password_actual": PASSWORD}, headers=auth(u)
        )
        assert r.status_code == 409 and r.json()["code"] == "EMAIL_YA_REGISTRADO"


class TestCambiarPassword:  # AC-47
    async def test_exitoso_revoca_token_anterior(self, client, db, crear_usuario):
        u = await crear_usuario()
        uid, email = u.id, u.email
        viejo = auth(u)
        r = await client.post(
            PWD, json={"password_actual": PASSWORD, "password_nueva": "NuevaClave2026"}, headers=viejo
        )
        assert r.status_code == 200, r.text
        nuevo = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await client.get(ME, headers=viejo)).json()["code"] == "TOKEN_REVOCADO"
        assert (await client.get(ME, headers=nuevo)).status_code == 200
        login = await client.post(LOGIN, json={"email": email, "password": "NuevaClave2026"})
        assert login.status_code == 200
        (h,) = await _historial(db, uid)
        assert h.cambios == {"password": ["***", "***"]}

    async def test_actual_incorrecta(self, client, crear_usuario):
        u = await crear_usuario()
        r = await client.post(
            PWD, json={"password_actual": "Otra12345", "password_nueva": "NuevaClave2026"}, headers=auth(u)
        )
        assert r.status_code == 403 and r.json()["code"] == "PASSWORD_ACTUAL_INCORRECTA"

    @pytest.mark.parametrize("nueva", ["abcdefgh", PASSWORD])
    async def test_debil_o_igual(self, client, crear_usuario, nueva):
        u = await crear_usuario()
        r = await client.post(
            PWD, json={"password_actual": PASSWORD, "password_nueva": nueva}, headers=auth(u)
        )
        assert r.status_code == 422


class TestCambioObligatorio:  # AC-48, EC-33
    DATOS = {
        "email": "nueva.docente@untdf.edu.ar",
        "password": "Temporal2026",
        "nombre": "Nora",
        "apellido": "Docente",
        "dni": "27111222",
        "rol": "DOCENTE",
        "sede": "Ushuaia",
    }

    async def test_flujo_completo(self, client, crear_usuario):
        sa = await crear_usuario(RolUsuario.SUPERADMIN)
        r = await client.post("/api/v1/users", json=self.DATOS, headers=auth(sa))
        assert r.status_code == 201 and r.json()["debe_cambiar_password"] is True

        login = await client.post(LOGIN, json={"email": self.DATOS["email"], "password": "Temporal2026"})
        assert login.status_code == 200
        assert login.json()["usuario"]["debe_cambiar_password"] is True
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        assert (await client.get(ME, headers=h)).status_code == 200
        bloqueado = await client.get("/api/v1/config/parametros", headers=h)
        assert bloqueado.status_code == 403 and bloqueado.json()["code"] == "CAMBIO_PASSWORD_REQUERIDO"
        perfil = await client.patch(ME, json={"telefono": "123456"}, headers=h)
        assert perfil.status_code == 403 and perfil.json()["code"] == "CAMBIO_PASSWORD_REQUERIDO"

        cambio = await client.post(
            PWD, json={"password_actual": "Temporal2026", "password_nueva": "Propia2026x"}, headers=h
        )
        assert cambio.status_code == 200
        assert cambio.json()["usuario"]["debe_cambiar_password"] is False
        h2 = {"Authorization": f"Bearer {cambio.json()['access_token']}"}
        assert (await client.get("/api/v1/config/parametros", headers=h2)).status_code == 200

    async def test_cli_no_exige_cambio(self, db):
        datos = UsuarioAdminCreate(
            email="sa@untdf.edu.ar", password="Laboratorio2026", nombre="Sa", apellido="Admin",
            dni="30111222", rol=RolUsuario.SUPERADMIN, sede=None,
        )
        usuario, _ = await crear_superadmin(db, datos)
        assert usuario.debe_cambiar_password is False


async def test_registro_propio_no_exige_cambio(client):
    r = await client.post(
        "/api/v1/auth/register",
        json={**TestCambioObligatorio.DATOS, "rol": "ESTUDIANTE", "sede": SedeEnum.RIO_GRANDE.value},
    )
    assert r.status_code == 201 and r.json()["debe_cambiar_password"] is False
