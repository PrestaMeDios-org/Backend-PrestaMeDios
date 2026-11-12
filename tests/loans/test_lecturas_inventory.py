"""Lecturas públicas de `loans` para la Fase C de `inventory` (SPEC-05 §10.2, T2.11, T2.12).

- `reservas_futuras_de_unidad`: reservas aprobadas que empiezan desde una fecha, para el
  aviso de `reservas_afectadas` (PRE-17, SPEC-04 §5.3).
- `historial_de_unidad`: las líneas de una unidad con su solicitante, para
  `GET /unidades/{id}/historial` (PRE-12, SPEC-04 §5.5).

`crear_linea(..., dia=d)` arma una orden `aprobada` con una línea del d/12 10:00 al
(d+2)/12 15:00, así que líneas que ocupan la misma unidad van separadas por 3 días o más.
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.core.enums import RolUsuario, SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum as U
from app.modules.loans import service
from app.modules.loans.enums import EstadoDetalleEnum as D

pytestmark = pytest.mark.integracion

TZ = timezone(timedelta(hours=-3))  # zona del laboratorio, igual que en conftest
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _retiro(dia: int) -> datetime:
    return datetime(2026, 12, dia, 10, tzinfo=TZ)


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


# ── reservas_futuras_de_unidad (T2.11) ───────────────────────────────────────


async def test_solo_las_reservas_aprobadas_que_empiezan_desde_la_fecha_ordenadas(
    db, crear_equipamiento, crear_linea
):  # PRE-17
    eq = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    unidad, otra = eq.unidades
    await crear_linea(eq, unidad, D.RESERVADO, dia=1)  # empieza antes de `desde`
    await crear_linea(eq, unidad, D.ENTREGADO, dia=5)  # ya retirada
    tarde = await crear_linea(eq, unidad, D.RESERVADO, dia=20)
    justo = await crear_linea(eq, unidad, D.RESERVADO, dia=10)  # empieza justo en `desde`
    await crear_linea(eq, unidad, D.CANCELADO, dia=10)  # ya no ocupa
    await crear_linea(eq, otra, D.RESERVADO, dia=15)  # otra unidad

    reservas = await service.reservas_futuras_de_unidad(db, unidad.id, _retiro(10))

    assert reservas == [
        service.ReservaFutura(
            orden_id=orden.id,
            detalle_id=orden.detalles[0].id,
            retiro=orden.detalles[0].retiro_pactado,
            devolucion=orden.detalles[0].devolucion_pactada,
        )
        for orden in (justo, tarde)
    ]


async def test_sin_reservas_futuras_devuelve_una_lista_vacia(db, crear_equipamiento):
    eq = await crear_equipamiento()
    assert await service.reservas_futuras_de_unidad(db, eq.unidades[0].id, _retiro(1)) == []


async def test_reservas_futuras_usa_una_sola_consulta(
    db, crear_equipamiento, crear_linea, contar_consultas
):
    eq = await crear_equipamiento()
    await crear_linea(eq, eq.unidades[0], D.RESERVADO, dia=10)
    contar_consultas.clear()

    await service.reservas_futuras_de_unidad(db, eq.unidades[0].id, _retiro(1))

    assert len(contar_consultas) == 1


def test_la_reserva_futura_no_tiene_identidad_y_es_inmutable():  # P6
    reserva = service.ReservaFutura(
        orden_id=1, detalle_id=2, retiro=_retiro(1), devolucion=_retiro(3)
    )
    campos = [c.name for c in dataclasses.fields(reserva)]
    assert campos == ["orden_id", "detalle_id", "retiro", "devolucion"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        reserva.retiro = _retiro(2)  # type: ignore[misc]


# ── historial_de_unidad (T2.12) ──────────────────────────────────────────────


async def test_el_historial_trae_todas_las_lineas_de_la_unidad_de_la_mas_reciente(
    db, crear_usuario, crear_equipamiento, crear_linea
):  # PRE-12
    eq = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    unidad, otra = eq.unidades
    ana = await crear_usuario(RolUsuario.ESTUDIANTE, USH, nombre="Ana", apellido="Pérez")
    beto = await crear_usuario(RolUsuario.DOCENTE, USH, nombre="Beto", apellido="Gómez")
    vieja = await crear_linea(eq, unidad, D.DEVUELTO, dia=1, solicitante=ana)
    cancelada = await crear_linea(eq, unidad, D.CANCELADO, dia=5, solicitante=beto)
    nueva = await crear_linea(eq, unidad, D.RESERVADO, dia=10, solicitante=ana)
    await crear_linea(eq, otra, D.RESERVADO, dia=12)  # otra unidad
    admin = await crear_usuario(RolUsuario.ADMIN_LOCAL, USH)

    historial = await service.historial_de_unidad(db, unidad.id, admin)

    assert [(m.orden_id, m.estado) for m in historial] == [
        (nueva.id, D.RESERVADO),
        (cancelada.id, D.CANCELADO),
        (vieja.id, D.DEVUELTO),
    ]
    primero = historial[0]
    assert primero.detalle_id == nueva.detalles[0].id
    assert (primero.solicitante.nombre, primero.solicitante.apellido) == ("Ana", "Pérez")
    assert historial[1].solicitante.nombre == "Beto"
    assert primero.retiro_pactado == nueva.detalles[0].retiro_pactado
    assert primero.devolucion_pactada == nueva.detalles[0].devolucion_pactada
    # Hasta la 0012 (Fase 3) no hay marcas de entrega ni devolución.
    assert (primero.entregado_en, primero.devuelto_en, primero.observacion_devolucion) == (
        None,
        None,
        None,
    )


async def test_el_historial_pagina_con_limit_y_offset(
    db, crear_usuario, crear_equipamiento, crear_linea
):
    eq = await crear_equipamiento()
    unidad = eq.unidades[0]
    ordenes = [await crear_linea(eq, unidad, D.DEVUELTO, dia=d) for d in (1, 5, 9)]
    superadmin = await crear_usuario(RolUsuario.SUPERADMIN)

    pagina1 = await service.historial_de_unidad(db, unidad.id, superadmin, limit=2)
    pagina2 = await service.historial_de_unidad(db, unidad.id, superadmin, limit=2, offset=2)

    assert [m.orden_id for m in pagina1] == [ordenes[2].id, ordenes[1].id]
    assert [m.orden_id for m in pagina2] == [ordenes[0].id]


async def test_el_admin_local_solo_ve_ordenes_de_su_sede(
    db, crear_usuario, crear_equipamiento, crear_linea
):  # P5, RN-L26
    eq = await crear_equipamiento()
    unidad = eq.unidades[0]
    orden = await crear_linea(eq, unidad, D.DEVUELTO, dia=1)
    admin_ush = await crear_usuario(RolUsuario.ADMIN_LOCAL, USH)
    admin_rg = await crear_usuario(RolUsuario.ADMIN_LOCAL, RG)
    superadmin = await crear_usuario(RolUsuario.SUPERADMIN)

    assert [m.orden_id for m in await service.historial_de_unidad(db, unidad.id, admin_ush)] == [
        orden.id
    ]
    assert await service.historial_de_unidad(db, unidad.id, admin_rg) == []
    assert [m.orden_id for m in await service.historial_de_unidad(db, unidad.id, superadmin)] == [
        orden.id
    ]


@pytest.mark.parametrize("rol", [RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE])
async def test_estudiantes_y_docentes_reciben_una_lista_vacia(
    db, crear_usuario, crear_equipamiento, crear_linea, rol
):  # P6
    eq = await crear_equipamiento()
    dueño = await crear_usuario(rol, USH)
    await crear_linea(eq, eq.unidades[0], D.DEVUELTO, dia=1, solicitante=dueño)

    assert await service.historial_de_unidad(db, eq.unidades[0].id, dueño) == []


async def test_el_historial_usa_dos_consultas(
    db, crear_usuario, crear_equipamiento, crear_linea, contar_consultas
):  # las líneas y los solicitantes, sin una consulta por línea
    eq = await crear_equipamiento()
    for d in (1, 5, 9):
        await crear_linea(eq, eq.unidades[0], D.DEVUELTO, dia=d)
    admin = await crear_usuario(RolUsuario.ADMIN_LOCAL, USH)
    contar_consultas.clear()

    historial = await service.historial_de_unidad(db, eq.unidades[0].id, admin)

    assert len(historial) == 3
    assert len(contar_consultas) == 2


async def test_una_unidad_sin_lineas_devuelve_vacio_con_una_consulta(
    db, crear_usuario, crear_equipamiento, contar_consultas
):
    eq = await crear_equipamiento()
    admin = await crear_usuario(RolUsuario.ADMIN_LOCAL, USH)
    contar_consultas.clear()

    assert await service.historial_de_unidad(db, eq.unidades[0].id, admin) == []
    assert len(contar_consultas) == 1


def test_el_movimiento_solo_expone_la_identidad_minima():  # P6, SPEC-04 §5.5
    campos = [c.name for c in dataclasses.fields(service.MovimientoUnidad)]
    assert campos == [
        "orden_id",
        "detalle_id",
        "solicitante",
        "estado",
        "retiro_pactado",
        "devolucion_pactada",
        "entregado_en",
        "devuelto_en",
        "observacion_devolucion",
    ]
    privados = {"dni", "email", "telefono"}
    assert not privados & {c.name for c in dataclasses.fields(service.DatosPublicosUsuario)}
