"""Tests de contratos Pydantic del dominio spaces (API-First)."""

from datetime import date, time

import pytest
from pydantic import ValidationError

from app.modules.spaces.schemas import (
    BloqueoEspacioCreate,
    EstadoReserva,
    DisponibilidadEspacioFilter,
    EspacioCreate,
    ReservaEspacioCreate,
    ReservaEspacioUpdateStatus,
)


def _reserva_valida(**overrides) -> dict:
    data = {
        "id_usuario": 1,
        "id_espacio": 2,
        "fecha_reserva": date(2026, 10, 12),
        "hora_inicio": time(10, 0),
        "hora_fin": time(11, 0),
    }
    data.update(overrides)
    return data


class TestReservaEspacioCreate:
    def test_defaults_pendiente(self):
        r = ReservaEspacioCreate(**_reserva_valida())
        assert r.estado_reserva == EstadoReserva.PENDIENTE
        assert r.motivo is None

    def test_hora_inicio_anterior_a_09_rechazada(self):
        with pytest.raises(ValidationError):
            ReservaEspacioCreate(**_reserva_valida(hora_inicio=time(8, 30)))

    def test_hora_fin_posterior_a_16_rechazada(self):
        with pytest.raises(ValidationError):
            ReservaEspacioCreate(**_reserva_valida(hora_inicio=time(15, 0), hora_fin=time(16, 30)))

    def test_limites_09_y_16_validos(self):
        r = ReservaEspacioCreate(**_reserva_valida(hora_inicio=time(9, 0), hora_fin=time(16, 0)))
        assert r.hora_inicio == time(9, 0)
        assert r.hora_fin == time(16, 0)

    def test_hora_fin_no_posterior_rechazada(self):
        with pytest.raises(ValidationError):
            ReservaEspacioCreate(**_reserva_valida(hora_inicio=time(11, 0), hora_fin=time(11, 0)))
        with pytest.raises(ValidationError):
            ReservaEspacioCreate(**_reserva_valida(hora_inicio=time(12, 0), hora_fin=time(11, 0)))


class TestReservaEspacioUpdateStatus:
    def test_aprobada_sin_motivo_ok(self):
        u = ReservaEspacioUpdateStatus(nuevo_estado="Aprobada")
        assert u.motivo_rechazo is None

    def test_rechazada_requiere_motivo(self):
        with pytest.raises(ValidationError):
            ReservaEspacioUpdateStatus(nuevo_estado="Rechazada")

    def test_rechazada_con_motivo_ok(self):
        u = ReservaEspacioUpdateStatus(nuevo_estado="Rechazada", motivo_rechazo="Mantenimiento")
        assert u.motivo_rechazo == "Mantenimiento"

    def test_estado_invalido_rechazado(self):
        with pytest.raises(ValidationError):
            ReservaEspacioUpdateStatus(nuevo_estado="En_Uso")


class TestBloqueoEspacioCreate:
    def test_fecha_fin_anterior_rechazada(self):
        with pytest.raises(ValidationError):
            BloqueoEspacioCreate(
                id_espacio=1,
                fecha_inicio=date(2026, 10, 14),
                fecha_fin=date(2026, 10, 12),
                motivo="Mantenimiento",
            )

    def test_rango_horario_invalido_rechazado(self):
        with pytest.raises(ValidationError):
            BloqueoEspacioCreate(
                id_espacio=1,
                fecha_inicio=date(2026, 10, 12),
                fecha_fin=date(2026, 10, 12),
                hora_inicio=time(15, 0),
                hora_fin=time(14, 0),
                motivo="Mantenimiento",
            )

    def test_dia_completo_sin_horas_ok(self):
        b = BloqueoEspacioCreate(
            id_espacio=1,
            fecha_inicio=date(2026, 10, 12),
            fecha_fin=date(2026, 10, 12),
            motivo="Contingencia",
        )
        assert b.hora_inicio is None and b.hora_fin is None


class TestEspacioYFiltro:
    def test_espacio_create(self):
        e = EspacioCreate(nombre="Aula-Estudio 1", id_sede=1)
        assert e.tipo is None

    def test_filtro_disponibilidad(self):
        f = DisponibilidadEspacioFilter(id_sede=1, fecha=date(2026, 10, 12))
        assert f.id_espacio is None
