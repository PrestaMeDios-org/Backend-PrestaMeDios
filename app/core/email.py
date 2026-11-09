"""Transporte de correo transversal (SPEC-03 §5.1, D-05, ADR-023).

`core` sólo arma el mensaje desde una plantilla y lo envía: qué se avisa, a quién y
cuándo lo decide el módulo que llama (USR-02 en `users`, los avisos en `notifications`).

- Plantillas en ``app/core/plantillas_correo/<TIPO>.txt``: primera línea asunto, el
  resto cuerpo, con variables ``$nombre`` de ``string.Template`` (RN-71).
- Backends: ``smtp`` (``smtplib`` en un hilo, timeout 10 s) y ``memoria`` (tests, RN-76).
- El log nunca lleva el contexto ni el cuerpo: pueden traer el enlace de recuperación
  (RN-74, NFR-19).
"""

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import EmailMessage
from enum import StrEnum
from functools import lru_cache
from importlib import resources
from string import Template

from app.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

PREFIJO_ASUNTO = "[PrestaMeDios] "
TIMEOUT_SMTP_SEGUNDOS = 10
# La completa `renderizar_correo` con `FRONTEND_URL`; el llamador no puede pasarla (RN-77).
VARIABLE_ENLACE_APP = "enlace_app"


class TipoCorreo(StrEnum):
    """Un valor por tipo de mensaje; cada uno tiene su plantilla (RN-71)."""

    RECUPERACION_PASSWORD = "RECUPERACION_PASSWORD"  # USR-02
    NOTIFICACION = "NOTIFICACION"  # genérico para `notifications` (RN-77, ADR-023)


class ErrorEnvioCorreo(Exception):
    """El transporte no pudo entregar el mensaje (RN-73). Nunca lleva el contenido."""


@dataclass(frozen=True, slots=True)
class CorreoRenderizado:
    asunto: str
    cuerpo: str


@dataclass(frozen=True, slots=True)
class CorreoEnviado:
    """Lo que guarda el backend ``memoria`` (RN-76)."""

    tipo: TipoCorreo
    destinatario: str
    asunto: str
    cuerpo: str


_bandeja: list[CorreoEnviado] = []


def bandeja_memoria() -> list[CorreoEnviado]:
    """Mensajes enviados con el backend ``memoria``, en orden. Sólo para tests."""
    return _bandeja


def vaciar_bandeja_memoria() -> None:
    _bandeja.clear()


# ── Plantillas (RN-71) ───────────────────────────────────────────────────────


@lru_cache
def _plantilla(tipo: TipoCorreo) -> tuple[Template, Template]:
    texto = (
        resources.files("app.core")
        .joinpath("plantillas_correo", f"{tipo.value}.txt")
        .read_text(encoding="utf-8")
    )
    asunto, _, cuerpo = texto.partition("\n")
    return Template(asunto.strip()), Template(cuerpo.strip())


def renderizar_correo(tipo: TipoCorreo, contexto: Mapping[str, str]) -> CorreoRenderizado:
    """Asunto y cuerpo desde la plantilla de ``tipo``. Falla si falta una variable.

    El error nombra el tipo y la variable, nunca los valores (RN-74). Se agrega
    ``enlace_app`` = ``FRONTEND_URL``; si el llamador la manda, se rechaza para que el
    pie no se pueda falsear.
    """
    if VARIABLE_ENLACE_APP in contexto:
        raise ValueError(f"`{VARIABLE_ENLACE_APP}` la completa el transporte, no el llamador.")
    datos = {**contexto, VARIABLE_ENLACE_APP: get_settings().frontend_url}
    asunto, cuerpo = _plantilla(TipoCorreo(tipo))
    try:
        return CorreoRenderizado(
            asunto=PREFIJO_ASUNTO + asunto.substitute(datos),
            cuerpo=cuerpo.substitute(datos) + "\n",
        )
    except KeyError as exc:
        raise ValueError(
            f"Falta la variable `{exc.args[0]}` para el correo {tipo.value}."
        ) from None


# ── Envío (RN-72…RN-75) ──────────────────────────────────────────────────────


def _mensaje(settings: Settings, destinatario: str, correo: CorreoRenderizado) -> EmailMessage:
    mensaje = EmailMessage()
    mensaje["From"] = settings.email_from
    mensaje["To"] = destinatario  # uno por mensaje, sin copias (RN-75)
    mensaje["Subject"] = correo.asunto
    mensaje.set_content(correo.cuerpo)
    return mensaje


def _enviar_smtp(settings: Settings, mensaje: EmailMessage) -> None:
    try:
        if settings.smtp_tls == "ssl":
            servidor: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=TIMEOUT_SMTP_SEGUNDOS,
                context=ssl.create_default_context(),
            )
        else:
            servidor = smtplib.SMTP(
                settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SMTP_SEGUNDOS
            )
        with servidor:
            if settings.smtp_tls == "starttls":
                servidor.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                servidor.login(settings.smtp_user, settings.smtp_password)
            servidor.send_message(mensaje)
    except (OSError, smtplib.SMTPException) as exc:
        raise ErrorEnvioCorreo(f"Falló el envío por SMTP ({type(exc).__name__}).") from exc


async def enviar_correo(
    tipo: TipoCorreo,
    destinatario: str,
    contexto: Mapping[str, str],
    *,
    usuario_id: int | None = None,
) -> None:
    """Renderiza y envía. Función común, sin dependencias de FastAPI: se llama desde un
    endpoint (con ``BackgroundTasks``) o desde un servicio, después del commit (RN-72).

    Un fallo del transporte llega como ``ErrorEnvioCorreo`` y decide quien llama (RN-73).
    ``usuario_id`` sólo se usa para el log (RN-74).
    """
    settings = get_settings()
    correo = renderizar_correo(tipo, contexto)  # antes de enviar: una variable faltante falla acá
    try:
        if settings.email_backend == "memoria":
            _bandeja.append(CorreoEnviado(tipo, destinatario, correo.asunto, correo.cuerpo))
        else:
            await asyncio.to_thread(
                _enviar_smtp, settings, _mensaje(settings, destinatario, correo)
            )
    except ErrorEnvioCorreo:
        logger.warning("Correo no enviado: tipo=%s usuario_id=%s", tipo.value, usuario_id)
        raise
    logger.info("Correo enviado: tipo=%s usuario_id=%s", tipo.value, usuario_id)
