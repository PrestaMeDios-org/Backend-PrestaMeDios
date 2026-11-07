"""Validaciones puras de `loans` (SPEC-05 §9; plan-05 §4.1). No usan base de datos."""

from datetime import datetime, time, timedelta, timezone

import pytest

from app.core.errors import AppError
from app.modules.loans import service

TZ = timezone(timedelta(hours=-3))  # zona del laboratorio (Ushuaia)
UTC = timezone.utc
APERTURA, CIERRE = time(9, 0), time(16, 0)


def _lab(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 12, dia, hora, minuto, tzinfo=TZ)


# ── Franja operativa (RN-L04) ────────────────────────────────────────────────


@pytest.mark.parametrize(("hora", "minuto"), [(9, 0), (10, 30), (16, 0)])
def test_franja_acepta_horas_dentro_del_horario(hora, minuto):  # AC-L07, EC-L03
    service._validar_franja(_lab(1, hora, minuto), _lab(3, hora, minuto), APERTURA, CIERRE)


@pytest.mark.parametrize(("hora", "minuto"), [(8, 59), (16, 1), (0, 0)])
def test_franja_rechaza_el_retiro_fuera_de_horario(hora, minuto):  # AC-L07
    with pytest.raises(AppError) as exc:
        service._validar_franja(_lab(1, hora, minuto), _lab(3, 15), APERTURA, CIERRE)
    assert exc.value.status_code == 422
    assert exc.value.code == "FRANJA_FUERA_DE_HORARIO"
    assert exc.value.extra["campo"] == "retiro"


@pytest.mark.parametrize(("hora", "minuto"), [(8, 59), (16, 1)])
def test_franja_rechaza_la_devolucion_fuera_de_horario(hora, minuto):  # AC-L07
    with pytest.raises(AppError) as exc:
        service._validar_franja(_lab(1, 10), _lab(3, hora, minuto), APERTURA, CIERRE)
    assert exc.value.code == "FRANJA_FUERA_DE_HORARIO"
    assert exc.value.extra["campo"] == "devolucion"


def test_franja_convierte_a_la_zona_del_laboratorio():  # EC-L04
    # 12:00 y 18:00 UTC son las 09:00 y las 15:00 en Ushuaia (UTC-3).
    service._validar_franja(
        datetime(2026, 12, 1, 12, 0, tzinfo=UTC),
        datetime(2026, 12, 3, 18, 0, tzinfo=UTC),
        APERTURA,
        CIERRE,
    )
    with pytest.raises(AppError):  # 11:59 UTC son las 08:59 locales
        service._validar_franja(
            datetime(2026, 12, 1, 11, 59, tzinfo=UTC),
            datetime(2026, 12, 3, 18, 0, tzinfo=UTC),
            APERTURA,
            CIERRE,
        )


# ── Anticipación (RN-L05) ────────────────────────────────────────────────────

AHORA = _lab(1, 10)


def test_anticipacion_exacta_es_valida():  # AC-L08
    service._validar_anticipacion(AHORA + timedelta(hours=24), AHORA, 24)


def test_anticipacion_insuficiente_se_rechaza():  # AC-L08
    with pytest.raises(AppError) as exc:
        service._validar_anticipacion(AHORA + timedelta(hours=23, minutes=59), AHORA, 24)
    assert exc.value.status_code == 422
    assert exc.value.code == "ANTICIPACION_INSUFICIENTE"
    assert exc.value.extra["anticipacion_min_horas"] == 24


def test_anticipacion_cero_horas_acepta_el_retiro_inmediato():  # AC-L08
    service._validar_anticipacion(AHORA, AHORA, 0)


def test_anticipacion_rechaza_un_retiro_en_el_pasado():  # AC-L08
    with pytest.raises(AppError) as exc:
        service._validar_anticipacion(AHORA - timedelta(hours=1), AHORA, 0)
    assert exc.value.code == "ANTICIPACION_INSUFICIENTE"


# ── Días corridos y plazo (RN-L06) ───────────────────────────────────────────


def test_dias_corridos_en_el_mismo_dia_es_uno():  # EC-L02
    assert service._dias_corridos(_lab(1, 10), _lab(1, 15)) == 1


def test_dias_corridos_cuenta_ambos_extremos():  # D-L04
    assert service._dias_corridos(_lab(1, 10), _lab(4, 15)) == 4


def test_dias_corridos_usa_la_fecha_local():  # EC-L04
    # 02:00 UTC del día 4 es el día 3 a las 23:00 en Ushuaia.
    devolucion = datetime(2026, 12, 4, 2, 0, tzinfo=UTC)
    assert service._dias_corridos(_lab(1, 10), devolucion) == 3


@pytest.mark.parametrize(
    ("es_notebook", "max_item", "esperado"),
    [
        (False, 4, 4),  # equipo común: parámetro general
        (False, 2, 2),  # el ítem pide menos que el parámetro
        (False, 15, 4),  # el ítem no puede ampliar el parámetro
        (False, None, 4),
        (True, 15, 15),  # notebook: parámetro de notebooks
        (True, 10, 10),
        (True, None, 15),
    ],
)
def test_limite_dias_es_el_menor_entre_parametro_e_item(es_notebook, max_item, esperado):
    assert service._limite_dias(es_notebook, 4, 15, max_item) == esperado  # AC-L11, EC-L01


def test_plazo_dentro_del_limite_es_valido():  # AC-L10
    service._validar_plazo(_lab(1, 10), _lab(4, 15), 4, equipamiento_id=7)


def test_plazo_excedido_identifica_el_item_y_el_maximo():  # AC-L10
    with pytest.raises(AppError) as exc:
        service._validar_plazo(_lab(1, 10), _lab(5, 15), 4, equipamiento_id=7)
    assert exc.value.status_code == 422
    assert exc.value.code == "LIMITE_DIAS_EXCEDIDO"
    assert exc.value.extra == {"equipamiento_id": 7, "max_dias": 4}
