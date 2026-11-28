"""Tests de contrato (sin base de datos) de `users` (SPEC-01 §6.5, §6.10, §6.11)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.modules.users.schemas import (
    CambioEstadoRequest,
    RegistroRequest,
    UsuarioAdminCreate,
)

BASE = {
    "email": "lucia.perez@untdf.edu.ar",
    "password": "Camara2026!",
    "nombre": "Lucía",
    "apellido": "Pérez",
    "dni": "40123456",
    "telefono": "+54 2901 555123",
    "rol": "ESTUDIANTE",
    "sede": "Ushuaia",
}


def _registro(**cambios):
    return RegistroRequest(**{**BASE, **cambios})


class TestRegistroRequest:
    @pytest.mark.parametrize("password", ["abcdefgh", "1234567", "12345678", "a" * 129])
    def test_password_debil(self, password):  # AC-05
        with pytest.raises(ValidationError):
            _registro(password=password)

    def test_password_igual_al_email(self):  # AC-05
        with pytest.raises(ValidationError):
            _registro(email="ana2026@untdf.edu.ar", password="Ana2026@UNTDF.edu.ar")

    @pytest.mark.parametrize("dni", ["123456", "123456789", "4012345a", "40.123.456"])
    def test_dni_invalido(self, dni):
        with pytest.raises(ValidationError):
            _registro(dni=dni)

    def test_nombres_con_acentos_apostrofe_y_guion(self):
        r = _registro(nombre="María José", apellido="O'Brien-Núñez")
        assert r.apellido == "O'Brien-Núñez"


class TestUsuarioAdminCreate:
    def test_superadmin_con_sede_rechazado(self):  # AC-14
        with pytest.raises(ValidationError):
            UsuarioAdminCreate(**{**BASE, "rol": "SUPERADMIN", "sede": "Ushuaia"})

    def test_admin_local_sin_sede_rechazado(self):  # AC-14
        with pytest.raises(ValidationError):
            UsuarioAdminCreate(**{**BASE, "rol": "ADMIN_LOCAL", "sede": None})

class TestCambioEstadoRequest:
    @pytest.mark.parametrize("estado", ["RECHAZADO", "SUSPENDIDO", "INACTIVO"])
    def test_motivo_obligatorio(self, estado):  # AC-10, RN-14
        with pytest.raises(ValidationError):
            CambioEstadoRequest(nuevo_estado=estado)

    def test_pendiente_no_es_destino(self):
        with pytest.raises(ValidationError):
            CambioEstadoRequest(nuevo_estado="PENDIENTE_APROBACION")

    def test_suspendido_hasta_pasado(self):  # UC-07 FA-04
        with pytest.raises(ValidationError):
            CambioEstadoRequest(
                nuevo_estado="SUSPENDIDO",
                motivo="Demora",
                suspendido_hasta=datetime.now(UTC) - timedelta(days=1),
            )

    def test_suspendido_hasta_con_otro_estado(self):
        with pytest.raises(ValidationError):
            CambioEstadoRequest(
                nuevo_estado="INACTIVO",
                motivo="Baja",
                suspendido_hasta=datetime.now(UTC) + timedelta(days=1),
            )

    def test_suspendido_hasta_sin_zona_horaria(self):
        with pytest.raises(ValidationError):
            CambioEstadoRequest(
                nuevo_estado="SUSPENDIDO",
                motivo="Demora",
                suspendido_hasta=datetime.now() + timedelta(days=1),
            )
