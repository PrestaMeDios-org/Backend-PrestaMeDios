"""SPEC-03 §5.1 · Transporte de correo — AC-100, AC-101 (RN-71…RN-77).

Sin base de datos: el backend ``memoria`` lo fija ``tests/conftest.py``.
"""

import logging
import smtplib
from string import Template

import pytest

from app.core import email
from app.core.email import (
    ErrorEnvioCorreo,
    TipoCorreo,
    enviar_correo,
    renderizar_correo,
)
from app.core.settings import get_settings

CONTEXTOS = {
    TipoCorreo.RECUPERACION_PASSWORD: {
        "nombre": "Lucía",
        "enlace": "http://localhost:8443/#/restablecer?token=abc",
        "vigencia_minutos": "30",
    },
    TipoCorreo.NOTIFICACION: {"titulo": "Préstamo aprobado", "mensaje": "Retirá el equipo el lunes."},
}


class TestRenderizar:  # AC-100, RN-71
    def test_cada_tipo_tiene_plantilla_y_contexto_de_ejemplo(self):
        assert set(CONTEXTOS) == set(TipoCorreo)

    @pytest.mark.parametrize("tipo", list(TipoCorreo))
    def test_sin_variables_sin_reemplazar(self, tipo):
        correo = renderizar_correo(tipo, CONTEXTOS[tipo])
        assert correo.asunto.startswith("[PrestaMeDios] ")  # RN-75
        assert "$" not in correo.asunto + correo.cuerpo
        assert "\n" not in correo.asunto

    def test_notificacion(self):  # RN-77
        correo = renderizar_correo(TipoCorreo.NOTIFICACION, CONTEXTOS[TipoCorreo.NOTIFICACION])
        assert correo.asunto == "[PrestaMeDios] Préstamo aprobado"
        assert correo.cuerpo.startswith("Retirá el equipo el lunes.")
        assert get_settings().frontend_url in correo.cuerpo
        assert "aviso automático" in correo.cuerpo

    def test_recuperacion_lleva_enlace_y_vigencia(self):
        correo = renderizar_correo(
            TipoCorreo.RECUPERACION_PASSWORD, CONTEXTOS[TipoCorreo.RECUPERACION_PASSWORD]
        )
        assert "Hola, Lucía" in correo.cuerpo
        assert "#/restablecer?token=abc" in correo.cuerpo and "30 minutos" in correo.cuerpo

    def test_variable_faltante_falla_sin_mostrar_valores(self):
        with pytest.raises(ValueError) as exc:
            renderizar_correo(TipoCorreo.NOTIFICACION, {"titulo": "secreto-titulo"})
        assert "mensaje" in str(exc.value) and "NOTIFICACION" in str(exc.value)
        assert "secreto-titulo" not in str(exc.value)

    def test_enlace_app_del_llamador_se_rechaza(self):
        with pytest.raises(ValueError):
            renderizar_correo(
                TipoCorreo.NOTIFICACION,
                {**CONTEXTOS[TipoCorreo.NOTIFICACION], "enlace_app": "https://phishing.example"},
            )

    def test_valores_con_signo_pesos_no_se_reinterpretan(self):
        correo = renderizar_correo(
            TipoCorreo.NOTIFICACION, {"titulo": "Multa de $500", "mensaje": "$titulo"}
        )
        assert correo.asunto.endswith("Multa de $500")
        assert correo.cuerpo.startswith("$titulo")


class TestEnviar:  # AC-101, RN-72…RN-74
    async def test_desde_un_servicio_sin_request(self, correos):
        async def servicio_cualquiera() -> None:
            await enviar_correo(
                TipoCorreo.NOTIFICACION, "ana@untdf.edu.ar", CONTEXTOS[TipoCorreo.NOTIFICACION]
            )

        await servicio_cualquiera()
        (enviado,) = correos
        assert enviado.tipo == TipoCorreo.NOTIFICACION
        assert enviado.destinatario == "ana@untdf.edu.ar"
        assert enviado.asunto == "[PrestaMeDios] Préstamo aprobado"

    async def test_variable_faltante_no_envia(self, correos):
        with pytest.raises(ValueError):
            await enviar_correo(TipoCorreo.NOTIFICACION, "ana@untdf.edu.ar", {"titulo": "x"})
        assert correos == []

    async def test_log_sin_contexto_ni_cuerpo(self, correos, caplog):
        caplog.set_level(logging.INFO, logger="app.core.email")
        contexto = CONTEXTOS[TipoCorreo.RECUPERACION_PASSWORD]
        await enviar_correo(
            TipoCorreo.RECUPERACION_PASSWORD, "ana@untdf.edu.ar", contexto, usuario_id=7
        )
        assert "tipo=RECUPERACION_PASSWORD usuario_id=7" in caplog.text
        assert "token=abc" not in caplog.text and "Lucía" not in caplog.text
        assert "ana@untdf.edu.ar" not in caplog.text


class _SMTPQueFalla:
    def __init__(self, *args, **kwargs):
        raise ConnectionRefusedError("sin servidor")


class _SMTPFalso:
    enviados: list = []
    llamadas: list = []

    def __init__(self, host, port, timeout):
        self.llamadas.append(("conectar", host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        self.llamadas.append(("starttls",))

    def login(self, usuario, clave):
        self.llamadas.append(("login", usuario))

    def send_message(self, mensaje):
        self.enviados.append(mensaje)


class TestBackendSmtp:  # RN-73, RN-75
    @pytest.fixture
    def smtp(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "email_backend", "smtp")
        monkeypatch.setattr(settings, "smtp_tls", "starttls")
        monkeypatch.setattr(settings, "smtp_user", "usuario-smtp")
        _SMTPFalso.enviados, _SMTPFalso.llamadas = [], []
        return monkeypatch

    async def test_envia_con_starttls_login_y_timeout(self, smtp, correos):
        smtp.setattr(smtplib, "SMTP", _SMTPFalso)
        await enviar_correo(
            TipoCorreo.NOTIFICACION, "ana@untdf.edu.ar", CONTEXTOS[TipoCorreo.NOTIFICACION]
        )
        (mensaje,) = _SMTPFalso.enviados
        assert mensaje["To"] == "ana@untdf.edu.ar" and mensaje["Cc"] is None
        assert mensaje["Subject"] == "[PrestaMeDios] Préstamo aprobado"
        nombres = [llamada[0] for llamada in _SMTPFalso.llamadas]
        assert nombres == ["conectar", "starttls", "login"]
        assert _SMTPFalso.llamadas[0][3] == 10
        assert correos == []  # no usa la bandeja de memoria

    async def test_fallo_llega_como_error_envio_y_se_registra(self, smtp, caplog):
        smtp.setattr(smtplib, "SMTP", _SMTPQueFalla)
        caplog.set_level(logging.INFO, logger="app.core.email")
        with pytest.raises(ErrorEnvioCorreo) as exc:
            await enviar_correo(
                TipoCorreo.RECUPERACION_PASSWORD,
                "ana@untdf.edu.ar",
                CONTEXTOS[TipoCorreo.RECUPERACION_PASSWORD],
                usuario_id=3,
            )
        assert "token=abc" not in str(exc.value)
        assert "Correo no enviado: tipo=RECUPERACION_PASSWORD usuario_id=3" in caplog.text
        assert "token=abc" not in caplog.text


def test_plantillas_se_cachean():
    email._plantilla.cache_clear()
    renderizar_correo(TipoCorreo.NOTIFICACION, CONTEXTOS[TipoCorreo.NOTIFICACION])
    renderizar_correo(TipoCorreo.NOTIFICACION, CONTEXTOS[TipoCorreo.NOTIFICACION])
    assert email._plantilla.cache_info().hits >= 1
    assert isinstance(email._plantilla(TipoCorreo.NOTIFICACION)[0], Template)
