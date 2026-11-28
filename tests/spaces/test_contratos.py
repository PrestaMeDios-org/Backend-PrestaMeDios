"""Contratos y reglas puras de `spaces` (sin base de datos).

Migrados desde ``tests/test_spaces_schemas.py`` y ``tests/test_spaces_availability.py``
(PR #6) y adaptados a SPEC-02: el horario ya no es fijo en el contrato (NFR-13).
"""

from datetime import date, time, timezone

import pytest
from pydantic import ValidationError

from app.modules.spaces.availability import bloqueo_solapa, intervalos_libres
from app.modules.spaces.models import BloqueoEspacio
from app.modules.spaces.schemas import (
    BloqueoEspacioCreate,
    ReservaEspacioCreate,
    ReservaEspacioUpdateStatus,
)

A, C = time(9, 0), time(16, 0)


def _reserva(**cambios):
    datos = {
        "id_espacio": 2,
        "fecha_reserva": date(2026, 10, 12),
        "hora_inicio": time(10, 0),
        "hora_fin": time(11, 0),
    }
    datos.update(cambios)
    return ReservaEspacioCreate(**datos)


class TestReservaEspacioCreate:
    @pytest.mark.parametrize(("inicio", "fin"), [(time(11), time(11)), (time(12), time(11))])
    def test_fin_no_posterior(self, inicio, fin):
        with pytest.raises(ValidationError):
            _reserva(hora_inicio=inicio, hora_fin=fin)

    def test_horas_con_zona_rechazadas(self):
        with pytest.raises(ValidationError):
            _reserva(hora_inicio=time(10, tzinfo=timezone.utc), hora_fin=time(11, tzinfo=timezone.utc))


class TestReservaEspacioUpdateStatus:
    def test_rechazada_requiere_motivo(self):
        with pytest.raises(ValidationError):
            ReservaEspacioUpdateStatus(nuevo_estado="Rechazada")


class TestBloqueoEspacioCreate:
    def _bloqueo(self, **cambios):
        datos = {
            "id_espacio": 1,
            "fecha_inicio": date(2026, 10, 12),
            "fecha_fin": date(2026, 10, 12),
            "motivo": "Mantenimiento",
        }
        datos.update(cambios)
        return BloqueoEspacioCreate(**datos)

    @pytest.mark.parametrize(
        "cambios",
        [
            {"fecha_inicio": date(2026, 10, 14)},
            {"hora_inicio": time(10)},
            {"hora_inicio": time(15), "hora_fin": time(14)},
        ],
        ids=["fecha-fin-anterior", "parcial-sin-hora-fin", "rango-invertido"],
    )
    def test_rangos_invalidos(self, cambios):
        with pytest.raises(ValidationError):
            self._bloqueo(**cambios)


def test_intervalos_libres_une_solapamientos_y_duraciones_arbitrarias():
    assert intervalos_libres(
        [(time(10), time(10, 45)), (time(10, 30), time(12, 15)), (time(14), time(14, 30))], A, C
    ) == [(time(9), time(10)), (time(12, 15), time(14)), (time(14, 30), time(16))]


def test_intervalos_libres_respetan_horario_configurable():  # GLO-03
    assert intervalos_libres([(time(8), time(9, 30))], time(8, 30), time(18)) == [
        (time(9, 30), time(18))
    ]


def test_bloqueo_parcial_aplica_en_cada_fecha_y_bordes_contiguos():  # EC-24
    bloqueo = BloqueoEspacio(
        id_espacio=1,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 14),
        hora_inicio=time(10),
        hora_fin=time(12),
        motivo="Mantenimiento",
    )
    assert bloqueo_solapa(bloqueo, date(2026, 10, 13), time(10, 30), time(11, 30))
    assert not bloqueo_solapa(bloqueo, date(2026, 10, 15), time(10, 30), time(11, 30))
    assert not bloqueo_solapa(bloqueo, date(2026, 10, 13), time(12), time(13))
