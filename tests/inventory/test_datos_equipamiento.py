"""C8 de SPEC-05 · `datos_equipamiento_por_ids` (función pública de `inventory`, SPEC-04 §6)."""

import dataclasses

import pytest
from sqlalchemy import event

from app.core.enums import SedeEnum
from app.modules.inventory.models import Equipamiento
from app.modules.inventory.service import DatosEquipamiento, datos_equipamiento_por_ids

pytestmark = pytest.mark.integracion

USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


@pytest.fixture
def consultas(engine):
    """Cuenta las sentencias SQL que llegan a la base mientras dura el test."""
    sentencias: list[str] = []

    def _registrar(conn, cursor, statement, parameters, context, executemany):
        sentencias.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _registrar)
    yield sentencias
    event.remove(engine.sync_engine, "before_cursor_execute", _registrar)


async def test_devuelve_todos_los_campos(sessionmaker_, crear_equipo):
    a = await crear_equipo(
        "CAM-1", "Cámara Sony", unidades=((USH,),), alta_gama=True, max_dias_prestamo=7
    )
    b = await crear_equipo("NB-1", "Notebook", es_notebook=True, max_dias_prestamo=15)
    async with sessionmaker_() as sesion:
        datos = await datos_equipamiento_por_ids(sesion, [a.id, b.id])
    assert datos == {
        a.id: DatosEquipamiento(
            id=a.id, codigo="CAM-1", nombre="Cámara Sony", activo=True,
            es_notebook=False, alta_gama=True, max_dias_prestamo=7,
        ),
        b.id: DatosEquipamiento(
            id=b.id, codigo="NB-1", nombre="Notebook", activo=True,
            es_notebook=True, alta_gama=False, max_dias_prestamo=15,
        ),
    }


async def test_incluye_items_inactivos_y_sin_unidades(sessionmaker_, crear_equipo):
    inactivo = await crear_equipo("OLD-1", "Retirado", activo=False)
    async with sessionmaker_() as sesion:
        datos = await datos_equipamiento_por_ids(sesion, [inactivo.id])
    assert datos[inactivo.id].activo is False  # decide quien llama (RN-I5)


async def test_no_filtra_por_sede(sessionmaker_, crear_equipo):
    eq = await crear_equipo("CAM-2", unidades=((USH,), (RG,)))
    async with sessionmaker_() as sesion:
        assert eq.id in await datos_equipamiento_por_ids(sesion, [eq.id])


async def test_entrada_vacia_no_consulta_la_base(sessionmaker_, consultas):
    async with sessionmaker_() as sesion:
        assert await datos_equipamiento_por_ids(sesion, []) == {}
        assert await datos_equipamiento_por_ids(sesion, iter(())) == {}
    assert consultas == []


async def test_omite_inexistentes_y_repetidos(sessionmaker_, crear_equipo):
    eq = await crear_equipo("CAM-3")
    async with sessionmaker_() as sesion:
        datos = await datos_equipamiento_por_ids(sesion, [eq.id, eq.id, 9999, eq.id])
    assert list(datos) == [eq.id]


async def test_acepta_cualquier_iterable(sessionmaker_, crear_equipo):
    a = await crear_equipo("CAM-4")
    b = await crear_equipo("CAM-5")
    async with sessionmaker_() as sesion:
        datos = await datos_equipamiento_por_ids(sesion, (i for i in {a.id, b.id}))
    assert set(datos) == {a.id, b.id}


async def test_una_sola_consulta_para_todo_el_lote(sessionmaker_, crear_equipo, consultas):
    ids = [(await crear_equipo(f"E-{i}", f"Equipo {i}", unidades=((USH,),))).id for i in range(5)]
    consultas.clear()
    async with sessionmaker_() as sesion:
        datos = await datos_equipamiento_por_ids(sesion, ids + ids)
    assert len(datos) == 5
    selects = [s for s in consultas if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    assert "unidades_fisicas" not in selects[0]  # no arrastra las unidades


async def test_no_carga_la_entidad_en_la_sesion(sessionmaker_, crear_equipo):
    eq = await crear_equipo("CAM-6", unidades=((USH,),))
    async with sessionmaker_() as sesion:
        await datos_equipamiento_por_ids(sesion, [eq.id])
        assert not [o for o in sesion.identity_map.values() if isinstance(o, Equipamiento)]


async def test_no_hace_flush_ni_commit(sessionmaker_, crear_equipo):
    eq = await crear_equipo("CAM-7")
    async with sessionmaker_() as sesion:
        pendiente = Equipamiento(
            codigo="PEND-1", nombre="Pendiente", marca="X", modelo="Y", categoria_id="cameras"
        )
        sesion.add(pendiente)
        await datos_equipamiento_por_ids(sesion, [eq.id])
        assert pendiente in sesion.new  # sigue sin flush: la transacción es de quien llama
        await sesion.rollback()
    async with sessionmaker_() as otra:
        assert await datos_equipamiento_por_ids(otra, [pendiente.id or -1]) == {}


def test_el_resultado_es_inmutable():
    d = DatosEquipamiento(
        id=1, codigo="C", nombre="N", activo=True, es_notebook=False,
        alta_gama=False, max_dias_prestamo=4,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.activo = False  # type: ignore[misc]
