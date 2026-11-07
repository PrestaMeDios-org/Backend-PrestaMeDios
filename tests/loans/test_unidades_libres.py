"""`unidades_libres`: unidades libres por modelo y período (SPEC-05 RN-L10, §10.2, §15.3).

D-L17 quedó descartada (spec v0.3.0): una línea `reservado` o `entregado` solo ocupa la
unidad durante su período. Con una reserva en otras fechas, la unidad sigue libre.

`crear_linea(..., dia=d)` arma una línea con período [d/12 10:00, (d+2)/12 15:00).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.enums import SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum as E
from app.modules.loans import service
from app.modules.loans.enums import EstadoDetalleEnum as D

pytestmark = pytest.mark.integracion

TZ = timezone(timedelta(hours=-3))  # zona del laboratorio, igual que en conftest


def _instante(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 12, dia, hora, minuto, tzinfo=TZ)


# Período de consulta por defecto: se solapa con una línea creada con dia=1.
DESDE, HASTA = _instante(2, 10), _instante(4, 15)


def _ids_por_codigo(equipamiento):
    """Ids de las unidades en el orden en que `inventory` las devuelve."""
    return [u.id for u in sorted(equipamiento.unidades, key=lambda u: u.codigo_inventario)]


async def _libres(db, ids, sede=SedeEnum.USHUAIA, desde=DESDE, hasta=HASTA):
    return await service.ids_unidades_libres(db, ids, sede, desde, hasta)


# ── Criterio físico (inventory) ──────────────────────────────────────────────


async def test_sin_lineas_todas_las_unidades_disponibles_estan_libres(db, crear_equipamiento):
    eq = await crear_equipamiento(estados=(E.DISPONIBLE,) * 3)
    assert await _libres(db, [eq.id]) == {eq.id: _ids_por_codigo(eq)}


async def test_solo_cuentan_las_unidades_disponibles_fisicamente(db, crear_equipamiento):
    eq = await crear_equipamiento(estados=(E.DISPONIBLE, E.PRESTADO, E.MANTENIMIENTO, E.BAJA))
    assert await _libres(db, [eq.id]) == {eq.id: [_ids_por_codigo(eq)[0]]}


async def test_solo_cuentan_las_unidades_de_la_sede(db, crear_equipamiento):  # P5
    eq = await crear_equipamiento(sede=SedeEnum.RIO_GRANDE)
    assert await _libres(db, [eq.id], SedeEnum.USHUAIA) == {eq.id: []}
    assert await _libres(db, [eq.id], SedeEnum.RIO_GRANDE) == {eq.id: _ids_por_codigo(eq)}


async def test_un_item_inactivo_no_tiene_unidades_libres(db, crear_equipamiento):
    eq = await crear_equipamiento(activo=False)
    assert await _libres(db, [eq.id]) == {eq.id: []}


# ── Criterio por fechas (loans) ──────────────────────────────────────────────


async def test_una_unidad_reservada_o_entregada_en_el_periodo_no_esta_libre(
    db, crear_equipamiento, crear_linea
):  # AC-L56, AC-L58
    eq = await crear_equipamiento(estados=(E.DISPONIBLE,) * 4)
    u1, u2, u3, u4 = sorted(eq.unidades, key=lambda u: u.codigo_inventario)
    await crear_linea(eq, u1, D.RESERVADO, dia=1)
    await crear_linea(eq, u2, D.ENTREGADO, dia=3)

    assert await _libres(db, [eq.id]) == {eq.id: [u3.id, u4.id]}


async def test_una_reserva_en_otras_fechas_no_ocupa_la_unidad(
    db, crear_equipamiento, crear_linea
):  # AC-L47, AC-L56, §15.3 (D-L17 descartada)
    eq = await crear_equipamiento()
    await crear_linea(eq, eq.unidades[0], D.RESERVADO, dia=20)

    assert await _libres(db, [eq.id]) == {eq.id: [eq.unidades[0].id]}
    assert await _libres(db, [eq.id], desde=_instante(19, 10), hasta=_instante(21, 10)) == {
        eq.id: []
    }


async def test_devolver_y_retirar_en_el_mismo_instante_no_choca(
    db, crear_equipamiento, crear_linea
):  # período semiabierto [retiro, fin_ocupacion), como el EXCLUDE
    eq = await crear_equipamiento()
    await crear_linea(eq, eq.unidades[0], D.RESERVADO, dia=1)  # termina el 3/12 15:00
    unidad = eq.unidades[0].id

    justo_despues = await _libres(db, [eq.id], desde=_instante(3, 15), hasta=_instante(4, 15))
    un_minuto_antes = await _libres(
        db, [eq.id], desde=_instante(3, 14, 59), hasta=_instante(4, 15)
    )
    termina_al_retiro = await _libres(db, [eq.id], desde=_instante(1, 9), hasta=_instante(1, 10))

    assert justo_despues == {eq.id: [unidad]}
    assert un_minuto_antes == {eq.id: []}
    assert termina_al_retiro == {eq.id: [unidad]}


@pytest.mark.parametrize(
    "estado", [D.PENDIENTE, D.DEVUELTO, D.RECHAZADO, D.NO_RETIRADO, D.CANCELADO]
)
async def test_las_lineas_que_no_ocupan_no_quitan_la_unidad(
    db, crear_equipamiento, crear_linea, estado
):
    eq = await crear_equipamiento()
    await crear_linea(eq, eq.unidades[0], estado, dia=1)
    assert await _libres(db, [eq.id]) == {eq.id: [eq.unidades[0].id]}


# ── Forma de la respuesta ────────────────────────────────────────────────────


async def test_varios_modelos_en_una_llamada(db, crear_equipamiento, crear_linea):
    con_stock = await crear_equipamiento(estados=(E.DISPONIBLE,) * 2)
    sin_unidades = await crear_equipamiento(estados=())
    ocupado = await crear_equipamiento()
    await crear_linea(ocupado, ocupado.unidades[0], D.RESERVADO, dia=1)

    ids = [con_stock.id, sin_unidades.id, ocupado.id, 999_999, con_stock.id]  # con un repetido
    libres = await _libres(db, ids)

    assert libres == {
        con_stock.id: _ids_por_codigo(con_stock),
        sin_unidades.id: [],
        ocupado.id: [],
        999_999: [],
    }


async def test_sin_modelos_devuelve_un_diccionario_vacio(db):
    assert await _libres(db, []) == {}


async def test_un_periodo_invertido_o_vacio_es_un_error_de_programacion(db):
    with pytest.raises(ValueError):
        await _libres(db, [1], desde=HASTA, hasta=DESDE)
    with pytest.raises(ValueError):
        await _libres(db, [1], desde=DESDE, hasta=DESDE)


async def test_la_api_publica_devuelve_solo_cantidades(
    db, crear_equipamiento, crear_linea
):  # §10.2: sin identidad de unidades ni de solicitantes
    eq = await crear_equipamiento(estados=(E.DISPONIBLE,) * 3)
    await crear_linea(eq, eq.unidades[0], D.RESERVADO, dia=1)

    assert await service.unidades_libres(db, [eq.id, 999_999], SedeEnum.USHUAIA, DESDE, HASTA) == {
        eq.id: 2,
        999_999: 0,
    }
