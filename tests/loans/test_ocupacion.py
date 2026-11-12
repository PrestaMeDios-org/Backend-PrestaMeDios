"""`ocupacion_de_unidades`: períodos ocupados por unidad (SPEC-05 §10.2, PRE-01).

`crear_linea(..., dia=d)` arma una línea con período [d/12 10:00, (d+2)/12 15:00).
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.modules.inventory.enums import EstadoUnidadEnum as E
from app.modules.loans import service
from app.modules.loans.enums import EstadoDetalleEnum as D

pytestmark = pytest.mark.integracion

TZ = timezone(timedelta(hours=-3))  # zona del laboratorio, igual que en conftest


def _instante(dia: int, hora: int) -> datetime:
    return datetime(2026, 12, dia, hora, tzinfo=TZ)


DESDE, HASTA = _instante(1, 0), _instante(31, 0)  # todo diciembre


def _periodo(dia: int) -> service.PeriodoOcupado:
    """El período que arma `crear_linea` para ese día."""
    inicio = _instante(dia, 10)
    return service.PeriodoOcupado(desde=inicio, hasta=inicio + timedelta(days=2, hours=5))


@pytest.fixture
def contar_consultas(db):
    """Cuenta las sentencias que la sesión manda a la base."""
    sentencias: list[str] = []

    def _registrar(conn, cursor, statement, *args):
        sentencias.append(statement)

    motor = db.bind.sync_engine
    event.listen(motor, "before_cursor_execute", _registrar)
    yield sentencias
    event.remove(motor, "before_cursor_execute", _registrar)


async def test_devuelve_los_periodos_ocupados_de_cada_unidad(
    db, crear_equipamiento, crear_linea
):
    eq = await crear_equipamiento(estados=(E.DISPONIBLE,) * 3)
    u1, u2, u3 = sorted(eq.unidades, key=lambda u: u.codigo_inventario)
    await crear_linea(eq, u1, D.RESERVADO, dia=10)
    await crear_linea(eq, u1, D.ENTREGADO, dia=1)  # se crea después pero empieza antes
    await crear_linea(eq, u2, D.RESERVADO, dia=20)

    ocupacion = await service.ocupacion_de_unidades(db, [u1.id, u2.id, u3.id], DESDE, HASTA)

    assert ocupacion == {
        u1.id: [_periodo(1), _periodo(10)],  # ordenados por inicio
        u2.id: [_periodo(20)],
        u3.id: [],
    }


@pytest.mark.parametrize(
    "estado", [D.PENDIENTE, D.DEVUELTO, D.RECHAZADO, D.NO_RETIRADO, D.CANCELADO]
)
async def test_las_lineas_que_no_ocupan_no_aparecen(db, crear_equipamiento, crear_linea, estado):
    eq = await crear_equipamiento()
    unidad = eq.unidades[0]
    await crear_linea(eq, unidad, estado, dia=5)
    assert await service.ocupacion_de_unidades(db, [unidad.id], DESDE, HASTA) == {unidad.id: []}


async def test_solo_los_periodos_que_se_solapan_con_el_rango(db, crear_equipamiento, crear_linea):
    eq = await crear_equipamiento()
    unidad = eq.unidades[0]
    await crear_linea(eq, unidad, D.RESERVADO, dia=1)  # termina el 3/12 15:00
    await crear_linea(eq, unidad, D.RESERVADO, dia=20)

    semana = await service.ocupacion_de_unidades(db, [unidad.id], _instante(2, 0), _instante(9, 0))
    desde_el_fin = await service.ocupacion_de_unidades(
        db, [unidad.id], _instante(3, 15), _instante(9, 0)
    )

    assert semana == {unidad.id: [_periodo(1)]}  # el período no se recorta al rango
    assert desde_el_fin == {unidad.id: []}  # [retiro, fin) es semiabierto


async def test_sin_unidades_devuelve_vacio_sin_consultar(db, contar_consultas):
    assert await service.ocupacion_de_unidades(db, [], DESDE, HASTA) == {}
    assert contar_consultas == []


async def test_usa_una_sola_consulta_y_omite_repetidos(
    db, crear_equipamiento, crear_linea, contar_consultas
):
    eq = await crear_equipamiento(estados=(E.DISPONIBLE,) * 2)
    u1, u2 = eq.unidades
    await crear_linea(eq, u1, D.RESERVADO, dia=1)
    contar_consultas.clear()

    ocupacion = await service.ocupacion_de_unidades(db, [u1.id, u2.id, u1.id], DESDE, HASTA)

    assert len(contar_consultas) == 1
    assert list(ocupacion) == [u1.id, u2.id]


async def test_una_unidad_inexistente_queda_libre(db):
    assert await service.ocupacion_de_unidades(db, [999_999], DESDE, HASTA) == {999_999: []}


async def test_un_periodo_invertido_o_vacio_es_un_error(db):
    with pytest.raises(ValueError):
        await service.ocupacion_de_unidades(db, [1], HASTA, DESDE)
    with pytest.raises(ValueError):
        await service.ocupacion_de_unidades(db, [1], DESDE, DESDE)


def test_el_periodo_es_inmutable_y_no_tiene_identidad():  # P6
    periodo = _periodo(1)
    assert [c.name for c in dataclasses.fields(periodo)] == ["desde", "hasta"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        periodo.desde = _instante(2, 10)  # type: ignore[misc]
