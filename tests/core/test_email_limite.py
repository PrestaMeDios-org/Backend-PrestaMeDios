"""SPEC-11 §6.7 · Límite diario de correos (``EMAIL_LIMITE_DIARIO``) — AC-P18.

El contador vive en la base (``envios_correo_diarios``) porque la API y el contenedor
de tareas son procesos distintos (plan §5.4). Backend ``memoria`` (conftest).
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import database
from app.core import email
from app.core.email import ErrorEnvioCorreo, TipoCorreo, enviar_correo
from app.core.models import EnvioCorreoDiario
from app.core.settings import ZONA_HORARIA_LAB, get_settings

pytestmark = pytest.mark.integracion

CONTEXTO = {"titulo": "Aviso", "mensaje": "Texto"}


@pytest.fixture
def con_limite(db, sessionmaker_, monkeypatch):
    """Usa la base de tests para el contador y fija el límite."""
    monkeypatch.setattr(database, "AsyncSessionLocal", sessionmaker_)

    def _fijar(limite: int | None) -> None:
        monkeypatch.setattr(get_settings(), "email_limite_diario", limite)

    return _fijar


async def _enviar(destinatario: str = "a@untdf.edu.ar") -> None:
    await enviar_correo(TipoCorreo.NOTIFICACION, destinatario, CONTEXTO)


async def test_corta_al_llegar_al_limite_sin_enviar(con_limite, correos, db):  # AC-P18
    con_limite(2)
    await _enviar("a@untdf.edu.ar")
    await _enviar("b@untdf.edu.ar")
    with pytest.raises(ErrorEnvioCorreo) as exc:
        await _enviar("c@untdf.edu.ar")
    assert exc.value.motivo == "limite_diario"
    assert [c.destinatario for c in correos] == ["a@untdf.edu.ar", "b@untdf.edu.ar"]
    fila = await db.scalar(select(EnvioCorreoDiario))
    assert fila.cantidad == 2  # el intento rechazado no suma


async def test_al_dia_siguiente_vuelve_a_enviar(con_limite, correos, monkeypatch):  # AC-P18
    con_limite(1)
    await _enviar()
    with pytest.raises(ErrorEnvioCorreo):
        await _enviar()
    manana = datetime.now(ZONA_HORARIA_LAB) + timedelta(days=1)
    monkeypatch.setattr(email, "ahora_lab", lambda: manana)
    await _enviar()
    assert len(correos) == 2


async def test_ultimo_cupo_concurrente(con_limite, correos):  # AC-P18, reserva atómica
    con_limite(1)
    resultados = await asyncio.gather(_enviar("a@untdf.edu.ar"), _enviar("b@untdf.edu.ar"), return_exceptions=True)
    errores = [r for r in resultados if isinstance(r, ErrorEnvioCorreo)]
    assert len(errores) == 1 and errores[0].motivo == "limite_diario"
    assert len(correos) == 1


async def test_sin_limite_no_toca_la_base(con_limite, correos, monkeypatch):  # plan §5.4
    con_limite(None)

    def _prohibido():
        raise AssertionError("Sin EMAIL_LIMITE_DIARIO el transporte no debe abrir sesiones")

    monkeypatch.setattr(database, "AsyncSessionLocal", _prohibido)
    await _enviar()
    assert len(correos) == 1


def test_motivo_por_defecto_es_smtp():  # compatibilidad con quien ya captura el error
    assert ErrorEnvioCorreo("Falló").motivo == "smtp"
