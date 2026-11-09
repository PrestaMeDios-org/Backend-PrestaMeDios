"""SPEC-03 Fase B3 · Renovación deslizante de la sesión (D-06 de SPEC-01, D-13, D-14).

AC-91…AC-94; RN-65…RN-69. Los tokens con ``auth_time`` viejo o sin el claim se emiten a
mano, con la misma firma que la aplicación.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.core.settings import JWT_ALGORITHM, JWT_ISSUER, get_settings
from app.modules.users.models import Usuario
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.integracion

RENOVAR = "/api/v1/auth/renovar"
CERRAR = "/api/v1/auth/me/sesiones/cerrar"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def _epoch(delta: timedelta = timedelta()) -> int:
    return int((datetime.now(UTC) + delta).timestamp())


def _token(
    usuario: Usuario,
    *,
    auth_time: int | None = None,
    iat: int | None = None,
    exp: int | None = None,
    sin_auth_time: bool = False,
    tv: int | None = None,
) -> str:
    """Token firmado con los claims de la aplicación y los tiempos que pida el test."""
    datos = usuario._cache_auth  # type: ignore[attr-defined]
    iat = iat if iat is not None else _epoch(timedelta(minutes=-10))
    claims = {
        "sub": str(datos["id"]),
        "rol": datos["rol"].value,
        "sede": datos["sede"].value if datos["sede"] is not None else None,
        "tv": tv if tv is not None else datos["token_version"],
        "iss": JWT_ISSUER,
        "iat": iat,
        "exp": exp if exp is not None else _epoch(timedelta(minutes=20)),
        "jti": "test",
    }
    if not sin_auth_time:
        claims["auth_time"] = auth_time if auth_time is not None else iat
    return jwt.encode(claims, get_settings().jwt_secret_key, algorithm=JWT_ALGORITHM)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _tope() -> timedelta:
    return timedelta(hours=get_settings().jwt_sesion_max_horas)


class TestRenovar:
    async def test_token_nuevo_con_el_mismo_auth_time(self, client, crear_usuario):  # AC-91
        u = await crear_usuario(RolUsuario.DOCENTE, SedeEnum.RIO_GRANDE)
        inicio = _epoch(timedelta(hours=-2))
        anterior = _token(u, auth_time=inicio)

        r = await client.post(RENOVAR, headers=_bearer(anterior))

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == get_settings().jwt_access_token_expire_minutes * 60
        assert body["usuario"]["id"] == u.id and body["usuario"]["rol"] == "DOCENTE"
        nuevo = _claims(body["access_token"])
        assert nuevo["auth_time"] == inicio  # RN-65
        assert nuevo["exp"] > _claims(anterior)["exp"]
        assert nuevo["exp"] - nuevo["iat"] == body["expires_in"]
        assert (await client.get(ME, headers=_bearer(body["access_token"]))).status_code == 200

    async def test_el_token_anterior_sigue_valido(self, client, crear_usuario):  # RN-67
        u = await crear_usuario()
        anterior = _token(u)
        assert (await client.post(RENOVAR, headers=_bearer(anterior))).status_code == 200
        assert (await client.get(ME, headers=_bearer(anterior))).status_code == 200

    async def test_renovar_varias_veces_conserva_el_inicio(self, client, crear_usuario):  # RN-65
        u = await crear_usuario()
        r = await client.post(LOGIN, json={"email": u.email, "password": PASSWORD})
        token = r.json()["access_token"]
        inicio = _claims(token)["auth_time"]
        for _ in range(3):
            r = await client.post(RENOVAR, headers=_bearer(token))
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]
        assert _claims(token)["auth_time"] == inicio

    async def test_con_cambio_de_password_pendiente(self, client, db, crear_usuario):  # §7.2
        u = await crear_usuario()
        u.debe_cambiar_password = True
        await db.commit()
        r = await client.post(RENOVAR, headers=auth(u))
        assert r.status_code == 200, r.text
        assert r.json()["usuario"]["debe_cambiar_password"] is True

    @pytest.mark.parametrize("rol", list(RolUsuario))
    async def test_todos_los_roles(self, client, crear_usuario, rol):
        u = await crear_usuario(rol, SedeEnum.USHUAIA)
        assert (await client.post(RENOVAR, headers=auth(u))).status_code == 200


class TestTope:  # AC-92, RN-66, RN-67
    async def test_pasado_el_tope(self, client, crear_usuario):
        u = await crear_usuario()
        vieja = _token(u, auth_time=_epoch(-_tope() - timedelta(minutes=1)))
        r = await client.post(RENOVAR, headers=_bearer(vieja))
        assert r.status_code == 401
        assert r.json()["code"] == "TOKEN_SESION_MAXIMA"
        assert r.headers["www-authenticate"] == "Bearer"

    async def test_justo_antes_del_tope(self, client, crear_usuario):
        u = await crear_usuario()
        token = _token(u, auth_time=_epoch(-_tope() + timedelta(minutes=1)))
        assert (await client.post(RENOVAR, headers=_bearer(token))).status_code == 200

    async def test_tope_configurable(self, client, crear_usuario, monkeypatch):
        monkeypatch.setattr(get_settings(), "jwt_sesion_max_horas", 1)
        u = await crear_usuario()
        token = _token(u, auth_time=_epoch(timedelta(minutes=-61)))
        r = await client.post(RENOVAR, headers=_bearer(token))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_SESION_MAXIMA"

    async def test_token_vencido(self, client, crear_usuario):
        u = await crear_usuario()
        vencido = _token(u, exp=_epoch(timedelta(minutes=-5)))
        r = await client.post(RENOVAR, headers=_bearer(vencido))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRADO"

    async def test_token_revocado(self, client, crear_usuario):
        u = await crear_usuario()
        r = await client.post(RENOVAR, headers=_bearer(_token(u, tv=99)))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_REVOCADO"

    @pytest.mark.parametrize(
        "estado", [EstadoCuenta.SUSPENDIDO, EstadoCuenta.INACTIVO]
    )
    async def test_cuenta_no_activa(self, client, db, crear_usuario, estado):
        u = await crear_usuario()
        token = _token(u)
        u.estado = estado
        await db.commit()
        r = await client.post(RENOVAR, headers=_bearer(token))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_REVOCADO"

    async def test_sin_token(self, client):
        r = await client.post(RENOVAR)
        assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"

    async def test_token_invalido(self, client):
        r = await client.post(RENOVAR, headers=_bearer("no.es.un-token"))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_INVALIDO"


class TestSinAuthTime:  # AC-93, RN-68
    async def test_usa_iat_como_inicio(self, client, crear_usuario):
        u = await crear_usuario()
        iat = _epoch(timedelta(minutes=-25))
        viejo = _token(u, iat=iat, sin_auth_time=True)
        assert "auth_time" not in _claims(viejo)

        r = await client.post(RENOVAR, headers=_bearer(viejo))

        assert r.status_code == 200, r.text
        assert _claims(r.json()["access_token"])["auth_time"] == iat

    async def test_iat_pasado_el_tope(self, client, crear_usuario):
        u = await crear_usuario()
        viejo = _token(
            u, iat=_epoch(-_tope() - timedelta(minutes=1)), sin_auth_time=True
        )
        r = await client.post(RENOVAR, headers=_bearer(viejo))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_SESION_MAXIMA"


class TestCerrarSesiones:  # AC-94, RN-69, D-14
    async def test_revoca_las_demas_y_el_nuevo_funciona(self, client, db, crear_usuario):
        u = await crear_usuario()
        otra_pc = (await client.post(LOGIN, json={"email": u.email, "password": PASSWORD}))
        otra_pc_token = otra_pc.json()["access_token"]
        inicio = _epoch(timedelta(hours=-1))
        esta_pestana = _token(u, auth_time=inicio)

        r = await client.post(CERRAR, headers=_bearer(esta_pestana))

        assert r.status_code == 200, r.text
        nuevo = r.json()["access_token"]
        for viejo in (esta_pestana, otra_pc_token):
            r_viejo = await client.get(ME, headers=_bearer(viejo))
            assert r_viejo.status_code == 401 and r_viejo.json()["code"] == "TOKEN_REVOCADO"
            r_ren = await client.post(RENOVAR, headers=_bearer(viejo))
            assert r_ren.status_code == 401 and r_ren.json()["code"] == "TOKEN_REVOCADO"
        assert (await client.get(ME, headers=_bearer(nuevo))).status_code == 200

        await db.refresh(u)
        assert u.token_version == 1
        claims = _claims(nuevo)
        assert claims["tv"] == 1
        assert claims["auth_time"] == inicio  # no estira el tope de RN-66

    async def test_el_nuevo_se_renueva(self, client, crear_usuario):
        u = await crear_usuario(RolUsuario.SUPERADMIN)
        nuevo = (await client.post(CERRAR, headers=auth(u))).json()["access_token"]
        assert (await client.post(RENOVAR, headers=_bearer(nuevo))).status_code == 200

    async def test_con_cambio_de_password_pendiente(self, client, db, crear_usuario):
        # SPEC-02 RN-33: con el cambio obligatorio pendiente sólo se cambia la contraseña.
        u = await crear_usuario()
        u.debe_cambiar_password = True
        await db.commit()
        r = await client.post(CERRAR, headers=auth(u))
        assert r.status_code == 403 and r.json()["code"] == "CAMBIO_PASSWORD_REQUERIDO"
        await db.refresh(u)
        assert u.token_version == 0

    async def test_sin_token(self, client):
        r = await client.post(CERRAR)
        assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"

    async def test_token_revocado(self, client, crear_usuario):
        u = await crear_usuario()
        r = await client.post(CERRAR, headers=_bearer(_token(u, tv=5)))
        assert r.status_code == 401 and r.json()["code"] == "TOKEN_REVOCADO"
