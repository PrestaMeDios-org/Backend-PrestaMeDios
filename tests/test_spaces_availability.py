"""Tests de intervalos libres y reglas de conflicto de spaces."""

import asyncio
from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.spaces import router
from app.modules.spaces.availability import bloqueo_solapa_reserva, intervalos_libres
from app.modules.spaces.models import BloqueoEspacio, ReservaEspacio
from app.modules.spaces.schemas import (
    BloqueoEspacioCreate,
    ReservaEspacioCreate,
    ReservaEspacioUpdateStatus,
)


def test_intervalos_libres_une_solapamientos_y_admite_duraciones_arbitrarias():
    assert intervalos_libres(
        [
            (time(10, 0), time(10, 45)),
            (time(10, 30), time(12, 15)),
            (time(14, 0), time(14, 30)),
        ]
    ) == [
        (time(9, 0), time(10, 0)),
        (time(12, 15), time(14, 0)),
        (time(14, 30), time(16, 0)),
    ]


def test_bloqueo_parcial_se_aplica_en_cada_fecha_del_rango():
    bloqueo = BloqueoEspacio(
        id_espacio=1,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 14),
        hora_inicio=time(10, 0),
        hora_fin=time(11, 0),
        motivo="Mantenimiento",
    )
    reserva = ReservaEspacio(
        id_usuario=1,
        id_espacio=1,
        fecha_reserva=date(2026, 10, 13),
        hora_inicio=time(10, 30),
        hora_fin=time(11, 30),
    )
    assert bloqueo_solapa_reserva(bloqueo, reserva)
    reserva.fecha_reserva = date(2026, 10, 15)
    assert not bloqueo_solapa_reserva(bloqueo, reserva)


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _Scalars(self.rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _FakeSession:
    def __init__(self, results):
        self.results = iter(results)
        self.execute = AsyncMock(side_effect=lambda *_args, **_kwargs: next(self.results))
        self.add = AsyncMock()
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.rollback = AsyncMock()
        self.refresh = AsyncMock()


def test_crear_bloqueo_rechaza_reserva_activa_solapada(monkeypatch):
    reserva = SimpleNamespace(
        id_espacio=1,
        fecha_reserva=date(2026, 10, 12),
        hora_inicio=time(10, 0),
        hora_fin=time(11, 0),
    )
    db = _FakeSession([_Result([reserva])])
    monkeypatch.setattr(router, "_bloquear_espacio", AsyncMock())
    payload = BloqueoEspacioCreate(
        id_espacio=1,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 12),
        hora_inicio=time(10, 30),
        hora_fin=time(11, 30),
        motivo="Mantenimiento",
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(router.crear_bloqueo(payload, db))

    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


def test_aprobar_reserva_rechaza_bloqueo_solapado(monkeypatch):
    reserva = SimpleNamespace(
        id_reserva=9,
        id_espacio=1,
        fecha_reserva=date(2026, 10, 12),
        hora_inicio=time(10, 0),
        hora_fin=time(11, 0),
        estado_reserva="Pendiente",
        motivo=None,
    )
    bloqueo = BloqueoEspacio(
        id_espacio=1,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 12),
        hora_inicio=time(10, 30),
        hora_fin=time(11, 30),
        motivo="Mantenimiento",
    )
    db = _FakeSession(
        [
            _Result([reserva]),
            _Result([]),
            _Result([bloqueo]),
        ]
    )
    monkeypatch.setattr(router, "_bloquear_espacio", AsyncMock())
    payload = ReservaEspacioUpdateStatus(nuevo_estado="Aprobada")

    with pytest.raises(HTTPException) as error:
        asyncio.run(router.actualizar_estado_reserva(9, payload, db))

    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


def test_crear_reserva_rechaza_bloqueo_existente(monkeypatch):
    bloqueo = BloqueoEspacio(
        id_espacio=1,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 12),
        hora_inicio=time(10, 0),
        hora_fin=time(11, 0),
        motivo="Mantenimiento",
    )
    db = _FakeSession([_Result([bloqueo])])
    monkeypatch.setattr(router, "_bloquear_espacio", AsyncMock())
    payload = ReservaEspacioCreate(
        id_usuario=1,
        id_espacio=1,
        fecha_reserva=date(2026, 10, 12),
        hora_inicio=time(10, 30),
        hora_fin=time(11, 30),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(router.crear_reserva(payload, db))

    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


def test_transicion_desde_estado_terminal_es_rechazada(monkeypatch):
    reserva = SimpleNamespace(
        id_reserva=9,
        id_espacio=1,
        estado_reserva="Rechazada",
    )
    db = _FakeSession([_Result([reserva])])
    monkeypatch.setattr(router, "_bloquear_espacio", AsyncMock())

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            router.actualizar_estado_reserva(
                9, ReservaEspacioUpdateStatus(nuevo_estado="Aprobada"), db
            )
        )

    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


def test_aprobar_reserva_pendiente_sin_conflictos(monkeypatch):
    reserva = SimpleNamespace(
        id_reserva=9,
        id_espacio=1,
        fecha_reserva=date(2026, 10, 12),
        hora_inicio=time(10, 0),
        hora_fin=time(11, 0),
        estado_reserva="Pendiente",
        motivo=None,
    )
    db = _FakeSession([_Result([reserva]), _Result([]), _Result([]), _Result([])])
    monkeypatch.setattr(router, "_bloquear_espacio", AsyncMock())

    result = asyncio.run(
        router.actualizar_estado_reserva(
            9, ReservaEspacioUpdateStatus(nuevo_estado="Aprobada"), db
        )
    )

    assert result.estado_reserva == "Aprobada"
    db.commit.assert_awaited_once()


def test_reserva_aprobada_puede_pasar_a_en_uso(monkeypatch):
    reserva = SimpleNamespace(
        id_reserva=9,
        id_espacio=1,
        fecha_reserva=date(2026, 10, 12),
        hora_inicio=time(10, 0),
        hora_fin=time(11, 0),
        estado_reserva="Aprobada",
        motivo=None,
    )
    db = _FakeSession([_Result([reserva]), _Result([]), _Result([])])
    monkeypatch.setattr(router, "_bloquear_espacio", AsyncMock())

    result = asyncio.run(
        router.actualizar_estado_reserva(
            9, ReservaEspacioUpdateStatus(nuevo_estado="En_Uso"), db
        )
    )

    assert result.estado_reserva == "En_Uso"
    db.commit.assert_awaited_once()


def test_consultar_disponibilidad_devuelve_intervalos_por_espacio():
    espacio = SimpleNamespace(id_espacio=3)
    reserva = SimpleNamespace(
        id_reserva=42,
        id_usuario=1,
        id_espacio=3,
        fecha_reserva=date(2026, 10, 12),
        hora_inicio=time(10, 15),
        hora_fin=time(11, 45),
        estado_reserva="Aprobada",
        motivo=None,
        created_at=datetime(2026, 10, 1),
    )
    bloqueo = SimpleNamespace(
        id_bloqueo=1,
        id_espacio=3,
        fecha_inicio=date(2026, 10, 12),
        fecha_fin=date(2026, 10, 12),
        hora_inicio=time(13, 0),
        hora_fin=time(14, 0),
        motivo="Mantenimiento",
        created_at=datetime(2026, 10, 1),
    )
    db = _FakeSession([_Result([espacio]), _Result([reserva]), _Result([bloqueo])])

    response = asyncio.run(
        router.consultar_disponibilidad(1, date(2026, 10, 12), None, db)
    )

    assert response["intervalos_disponibles"] == [
        {
            "id_espacio": 3,
            "intervalos_libres": [
                {"hora_inicio": time(9, 0), "hora_fin": time(10, 15)},
                {"hora_inicio": time(11, 45), "hora_fin": time(13, 0)},
                {"hora_inicio": time(14, 0), "hora_fin": time(16, 0)},
            ],
        }
    ]
