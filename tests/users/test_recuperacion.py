"""SPEC-03 §5 · Recuperación de contraseña (USR-02) — AC-71…AC-79."""

import hashlib
import logging
import re
import smtplib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.enums import EstadoCuenta
from app.core.settings import get_settings
from app.modules.users.models import IntentoRecuperacion, TokenRecuperacion
from app.modules.users.schemas import MENSAJE_RECUPERACION_NEUTRO

pytestmark = pytest.mark.integracion

SOLICITAR = "/api/v1/auth/recuperacion"
CONFIRMAR = "/api/v1/auth/recuperacion/confirmar"
LOGIN = "/api/v1/auth/login"
NUEVA = "Restablecida2026"


def _token_del_correo(correo) -> str:
    (token,) = re.findall(r"#/restablecer\?token=([A-Za-z0-9_\-]+)", correo.cuerpo)
    return token


async def _pedir(client, email: str):
    return await client.post(SOLICITAR, json={"email": email})


async def _tokens(db, usuario_id: int) -> list[TokenRecuperacion]:
    db.expire_all()
    return list(
        (
            await db.scalars(
                select(TokenRecuperacion)
                .where(TokenRecuperacion.usuario_id == usuario_id)
                .order_by(TokenRecuperacion.id)
            )
        ).all()
    )


class TestSolicitar:
    async def test_cuenta_activa(self, client, db, crear_usuario, correos):  # AC-71
        u = await crear_usuario(email="lucia@untdf.edu.ar", nombre="Lucía")
        uid = u.id
        r = await _pedir(client, "  Lucia@UNTDF.edu.ar ")  # EC-36
        assert r.status_code == 202
        assert r.json() == {"detail": MENSAJE_RECUPERACION_NEUTRO}

        (correo,) = correos
        assert correo.destinatario == "lucia@untdf.edu.ar"
        assert correo.asunto.startswith("[PrestaMeDios] ")
        assert "Hola, Lucía" in correo.cuerpo
        token = _token_del_correo(correo)
        assert f"{get_settings().frontend_url}/#/restablecer?token={token}" in correo.cuerpo
        assert len(token) >= 43  # 256 bits en base64url (RN-46)

        (fila,) = await _tokens(db, uid)
        assert fila.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in fila.token_hash and fila.usado_en is None
        vigencia = fila.expira_en - datetime.now(UTC)
        assert timedelta(minutes=29) < vigencia <= timedelta(minutes=30)

    @pytest.mark.parametrize(
        "estado",
        [
            EstadoCuenta.PENDIENTE_APROBACION,
            EstadoCuenta.RECHAZADO,
            EstadoCuenta.SUSPENDIDO,
            EstadoCuenta.INACTIVO,
        ],
    )
    async def test_cuentas_no_activas_misma_respuesta(
        self, client, db, crear_usuario, correos, estado
    ):  # AC-72, RN-45
        await crear_usuario(estado=estado, email="otra@untdf.edu.ar")
        await crear_usuario(email="activa@untdf.edu.ar")
        referencia = await _pedir(client, "activa@untdf.edu.ar")
        correos.clear()

        r = await _pedir(client, "otra@untdf.edu.ar")
        assert (r.status_code, r.json()) == (referencia.status_code, referencia.json())
        assert correos == []
        assert await db.scalar(select(func.count()).select_from(TokenRecuperacion)) == 1

    async def test_email_inexistente(self, client, correos):  # AC-72, RN-44
        r = await _pedir(client, "nadie@untdf.edu.ar")
        assert r.status_code == 202 and r.json() == {"detail": MENSAJE_RECUPERACION_NEUTRO}
        assert correos == []

    async def test_sin_token_y_campos_desconocidos(self, client):  # AC-79
        r = await client.post(SOLICITAR, json={"email": "a@untdf.edu.ar", "rol": "SUPERADMIN"})
        assert r.status_code == 422
        r = await client.post(SOLICITAR, json={"email": "no-es-un-email"})
        assert r.status_code == 422


class TestLimite:  # AC-78, RN-49
    @pytest.mark.parametrize("existe", [True, False])
    async def test_cuarta_solicitud_por_email(self, client, crear_usuario, correos, existe):
        if existe:
            await crear_usuario(email="lucia@untdf.edu.ar")
        for _ in range(3):
            assert (await _pedir(client, "lucia@untdf.edu.ar")).status_code == 202
        r = await _pedir(client, "LUCIA@untdf.edu.ar")
        assert r.status_code == 429 and r.json()["code"] == "DEMASIADOS_INTENTOS"
        assert len(correos) == (3 if existe else 0)
        # Otro email sigue pudiendo pedir.
        assert (await _pedir(client, "otro@untdf.edu.ar")).status_code == 202

    async def test_limite_por_ip(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "recuperacion_max_por_ip_hora", 2)
        assert (await _pedir(client, "a@untdf.edu.ar")).status_code == 202
        assert (await _pedir(client, "b@untdf.edu.ar")).status_code == 202
        r = await _pedir(client, "c@untdf.edu.ar")
        assert r.status_code == 429 and r.json()["code"] == "DEMASIADOS_INTENTOS"

    async def test_intentos_viejos(self, client, db):
        for _ in range(3):
            await _pedir(client, "lucia@untdf.edu.ar")
        await db.execute(
            update(IntentoRecuperacion).values(created_at=func.now() - timedelta(hours=25))
        )
        await db.commit()
        assert (await _pedir(client, "lucia@untdf.edu.ar")).status_code == 202
        db.expire_all()
        assert await db.scalar(select(func.count()).select_from(IntentoRecuperacion)) == 1

    async def test_no_guarda_el_email(self, client, db):
        await _pedir(client, "lucia@untdf.edu.ar")
        (intento,) = (await db.scalars(select(IntentoRecuperacion))).all()
        assert "lucia" not in intento.email_hash and len(intento.email_hash) == 64
        assert intento.ip == "127.0.0.1"


class _SMTPQueFalla:
    def __init__(self, *args, **kwargs):
        raise ConnectionRefusedError("sin servidor")


async def test_fallo_de_smtp_no_cambia_la_respuesta(
    client, db, crear_usuario, monkeypatch, caplog
):  # AC-79, RN-73
    settings = get_settings()
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(smtplib, "SMTP", _SMTPQueFalla)
    caplog.set_level(logging.INFO)
    u = await crear_usuario(email="lucia@untdf.edu.ar")
    uid = u.id

    r = await _pedir(client, "lucia@untdf.edu.ar")
    assert r.status_code == 202 and r.json() == {"detail": MENSAJE_RECUPERACION_NEUTRO}
    assert f"No se pudo enviar el correo de recuperación: usuario_id={uid}" in caplog.text
    assert "restablecer?token=" not in caplog.text
    (fila,) = await _tokens(db, uid)
    assert fila.token_hash not in caplog.text


async def test_endpoints_sin_sesion_en_openapi(client):  # AC-79, P4.1
    esquema = (await client.get("/openapi.json")).json()
    for ruta in (SOLICITAR, CONFIRMAR):
        if ruta in esquema["paths"]:
            assert "security" not in esquema["paths"][ruta]["post"]
    assert "429" in esquema["paths"][SOLICITAR]["post"]["responses"]
