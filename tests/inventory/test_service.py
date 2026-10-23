"""SPEC-04 §6 · Funciones públicas de `inventory` para `loans` — INV-22 (y INV-21 a nivel servicio)."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.enums import SedeEnum
from app.core.errors import AppError
from app.modules.inventory.enums import EstadoUnidadEnum as E
from app.modules.inventory.models import UnidadFisica
from app.modules.inventory.service import (
    liberar_unidad,
    marcar_unidad_prestada,
    unidad_es_asignable,
    unidades_asignables,
)

pytestmark = pytest.mark.integracion

USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


async def _ids(db, equipo) -> dict[str, int]:
    filas = await db.execute(
        select(UnidadFisica.codigo_inventario, UnidadFisica.id).where(
            UnidadFisica.equipamiento_id == equipo.id
        )
    )
    return dict(filas.all())


async def test_solo_unidades_disponibles_de_la_sede(db, crear_equipo):  # INV-22
    eq = await crear_equipo(
        "CAM", unidades=((USH,), (USH, E.MANTENIMIENTO), (USH, E.BAJA), (USH, E.PRESTADO), (RG,))
    )
    ids = await _ids(db, eq)
    assert await unidades_asignables(db, eq.id, USH) == [ids["CAM-U1"]]
    assert await unidades_asignables(db, eq.id, RG) == [ids["CAM-U5"]]
    assert await unidad_es_asignable(db, ids["CAM-U1"], USH) is True
    assert await unidad_es_asignable(db, ids["CAM-U1"], RG) is False  # otra sede
    for codigo in ("CAM-U2", "CAM-U3", "CAM-U4"):
        assert await unidad_es_asignable(db, ids[codigo], USH) is False


async def test_item_inactivo_no_es_asignable(db, crear_equipo):  # INV-22
    eq = await crear_equipo("CAM", unidades=((USH,),), activo=False)
    ids = await _ids(db, eq)
    assert await unidades_asignables(db, eq.id, USH) == []
    assert await unidad_es_asignable(db, ids["CAM-U1"], USH) is False


async def test_entrega_y_devolucion(db, crear_equipo):  # INV-22
    eq = await crear_equipo("CAM", unidades=((USH,),))
    uid = (await _ids(db, eq))["CAM-U1"]
    unidad = await marcar_unidad_prestada(db, uid)
    await db.commit()
    assert unidad.estado is E.PRESTADO
    with pytest.raises(AppError) as exc:
        await marcar_unidad_prestada(db, uid)
    assert exc.value.status_code == 409 and exc.value.code == "TRANSICION_ESTADO_INVALIDA"
    await db.rollback()
    unidad = await liberar_unidad(db, uid)
    await db.commit()
    assert unidad.estado is E.DISPONIBLE
    with pytest.raises(AppError) as exc:
        await liberar_unidad(db, uid)
    assert exc.value.code == "TRANSICION_ESTADO_INVALIDA"
    with pytest.raises(AppError) as exc:
        await marcar_unidad_prestada(db, 9999)
    assert exc.value.status_code == 404 and exc.value.code == "UNIDAD_NO_ENCONTRADA"


async def test_no_se_presta_en_mantenimiento(db, crear_equipo):  # INV-22
    eq = await crear_equipo("CAM", unidades=((USH, E.MANTENIMIENTO),))
    uid = (await _ids(db, eq))["CAM-U1"]
    with pytest.raises(AppError) as exc:
        await marcar_unidad_prestada(db, uid)
    assert exc.value.code == "TRANSICION_ESTADO_INVALIDA"


async def test_dos_entregas_simultaneas_de_la_misma_unidad(
    db, sessionmaker_, crear_equipo
):  # INV-21
    eq = await crear_equipo("CAM", unidades=((USH,),))
    uid = (await _ids(db, eq))["CAM-U1"]

    async def entregar() -> str:
        async with sessionmaker_() as sesion:
            try:
                await marcar_unidad_prestada(sesion, uid)
                await asyncio.sleep(0.2)  # mantiene el bloqueo para forzar la carrera
                await sesion.commit()
                return "ok"
            except AppError as exc:
                await sesion.rollback()
                return exc.code

    resultados = await asyncio.gather(entregar(), entregar())
    assert sorted(resultados) == ["TRANSICION_ESTADO_INVALIDA", "ok"]
