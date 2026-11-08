"""Concurrencia al validar órdenes (SPEC-05 Fase 2, T2.8; AC-L23, AC-L24, AC-L55, EC-L10).

Cada pedido HTTP usa su propia sesión y su propia conexión (el `client` de `conftest`
abre una sesión por pedido y el engine usa `NullPool`), como en producción (ADR-013,
AC-L55). Los pedidos salen a la vez con `asyncio.gather`; las aserciones miran el
resultado (uno gana y el otro recibe el código esperado) y nunca el orden de llegada.
Cada caso se repite en varias rondas independientes para darle más chances a la carrera.

Lo que se protege:
- `FOR UPDATE` sobre la orden serializa las acciones sobre una misma orden (RN-L14).
- El `EXCLUDE` de `0009` impide dos reservas solapadas de una misma unidad (RN-L12).
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.enums import RolUsuario, SedeEnum
from app.core.settings import ahora_lab
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum
from app.modules.loans.models import DetallePrestamo, OrdenHistorialEstado, OrdenPedido
from tests.conftest import auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"
RONDAS = 5
RETIRO = (ahora_lab() + timedelta(days=7)).replace(hour=10, minute=0, second=0, microsecond=0)
DURACION = timedelta(days=2, hours=5)


@pytest.fixture
def crear_orden(db, crear_usuario):
    """Fábrica: una orden ``pendiente`` de una línea, del solicitante indicado o uno nuevo."""

    async def _crear(equipamiento, *, retiro: datetime = RETIRO, solicitante=None):
        solicitante = solicitante or await crear_usuario(RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA)
        orden = OrdenPedido(
            solicitante_id=solicitante._cache_auth["id"],
            sede=SedeEnum.USHUAIA,
            estado=EstadoOrdenEnum.PENDIENTE,
            detalles=[
                DetallePrestamo(
                    equipamiento_id=equipamiento.id,
                    estado=EstadoDetalleEnum.PENDIENTE,
                    retiro_pactado=retiro,
                    devolucion_pactada=retiro + DURACION,
                    fin_ocupacion=retiro + DURACION,
                )
            ],
        )
        db.add(orden)
        await db.commit()
        return orden

    return _crear


@pytest.fixture
async def admin(crear_usuario):
    return await crear_usuario(RolUsuario.ADMIN_LOCAL, SedeEnum.USHUAIA)


def _patch(client, usuario, orden: OrdenPedido, cuerpo: dict):
    """La corrutina del pedido, sin esperarla: se lanza junto con otras."""
    return client.patch(f"{BASE}/ordenes/{orden.id}/estado", json=cuerpo, headers=auth(usuario))


def _aprobacion(orden: OrdenPedido, unidad_id: int) -> dict:
    return {
        "estado": "aprobada",
        "asignaciones": [{"detalle_id": orden.detalles[0].id, "unidad_fisica_id": unidad_id}],
    }


RECHAZO = {"estado": "rechazada", "motivo": "Sin stock"}
CANCELACION = {"estado": "cancelada"}


async def _orden_en_base(db, orden_id: int) -> OrdenPedido:
    stmt = (
        select(OrdenPedido)
        .where(OrdenPedido.id == orden_id)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one()


async def _transiciones(db, orden_id: int) -> int:
    stmt = select(func.count()).where(OrdenHistorialEstado.orden_id == orden_id)
    return await db.scalar(stmt)


async def _reservas_de_unidad(db, unidad_id: int) -> int:
    stmt = select(func.count()).where(
        DetallePrestamo.unidad_fisica_id == unidad_id,
        DetallePrestamo.estado == EstadoDetalleEnum.RESERVADO,
    )
    return await db.scalar(stmt)


# ── AC-L23: dos aprobaciones sobre la misma unidad ───────────────────────────


async def test_dos_aprobaciones_solapadas_de_la_misma_unidad_una_gana(
    client, db, admin, crear_equipamiento, crear_orden
):  # AC-L23, RN-L12, RN-L13
    for ronda in range(RONDAS):
        camara = await crear_equipamiento()
        unidad = camara.unidades[0].id
        # La segunda empieza un día después: los períodos se solapan pero no son iguales.
        primera = await crear_orden(camara)
        segunda = await crear_orden(camara, retiro=RETIRO + timedelta(days=1))

        respuestas = await asyncio.gather(
            _patch(client, admin, primera, _aprobacion(primera, unidad)),
            _patch(client, admin, segunda, _aprobacion(segunda, unidad)),
        )

        codigos = sorted(r.status_code for r in respuestas)
        assert codigos == [200, 409], (ronda, [r.json() for r in respuestas])
        perdedora_r = next(r for r in respuestas if r.status_code == 409)
        assert perdedora_r.json()["code"] == "UNIDAD_NO_DISPONIBLE"
        assert await _reservas_de_unidad(db, unidad) == 1
        # La perdedora sigue pendiente, sin unidad ni resolución (sin cambios parciales).
        ganadora_id = primera.id if respuestas[0].status_code == 200 else segunda.id
        perdedora_id = segunda.id if ganadora_id == primera.id else primera.id
        perdedora = await _orden_en_base(db, perdedora_id)
        assert perdedora.estado is EstadoOrdenEnum.PENDIENTE
        assert perdedora.resuelto_en is None
        assert perdedora.detalles[0].estado is EstadoDetalleEnum.PENDIENTE
        assert perdedora.detalles[0].unidad_fisica_id is None
        assert await _transiciones(db, perdedora_id) == 0
        assert (await _orden_en_base(db, ganadora_id)).estado is EstadoOrdenEnum.APROBADA


async def test_dos_aprobaciones_de_la_misma_unidad_en_fechas_distintas_prosperan(
    client, db, admin, crear_equipamiento, crear_orden
):  # AC-L23: con períodos que no se solapan, ambas se aprueban
    for ronda in range(RONDAS):
        camara = await crear_equipamiento()
        unidad = camara.unidades[0].id
        primera = await crear_orden(camara)
        segunda = await crear_orden(camara, retiro=RETIRO + timedelta(days=10))

        respuestas = await asyncio.gather(
            _patch(client, admin, primera, _aprobacion(primera, unidad)),
            _patch(client, admin, segunda, _aprobacion(segunda, unidad)),
        )

        assert [r.status_code for r in respuestas] == [200, 200], (ronda, respuestas[1].json())
        assert await _reservas_de_unidad(db, unidad) == 2


# ── AC-L24: dos acciones sobre la misma orden ────────────────────────────────


@pytest.mark.parametrize(
    "acciones",
    [("aprobar", "rechazar"), ("aprobar", "aprobar"), ("rechazar", "rechazar")],
)
async def test_dos_acciones_sobre_la_misma_orden_una_prospera(
    client, db, admin, crear_equipamiento, crear_orden, acciones
):  # AC-L24, RN-L14
    for ronda in range(RONDAS):
        camara = await crear_equipamiento()
        orden = await crear_orden(camara)
        cuerpos = {"aprobar": _aprobacion(orden, camara.unidades[0].id), "rechazar": RECHAZO}

        respuestas = await asyncio.gather(
            *(_patch(client, admin, orden, cuerpos[a]) for a in acciones)
        )

        codigos = sorted(r.status_code for r in respuestas)
        assert codigos == [200, 409], (ronda, [r.json() for r in respuestas])
        assert next(r for r in respuestas if r.status_code == 409).json()["code"] == (
            "TRANSICION_INVALIDA"
        )
        # El estado final es el de la que prosperó, con una sola transición registrada.
        ganadora = acciones[[r.status_code for r in respuestas].index(200)]
        esperado = {"aprobar": EstadoOrdenEnum.APROBADA, "rechazar": EstadoOrdenEnum.RECHAZADA}
        assert (await _orden_en_base(db, orden.id)).estado is esperado[ganadora]
        assert await _transiciones(db, orden.id) == 1


# ── EC-L10: el dueño cancela mientras el administrador aprueba ───────────────


async def test_cancelacion_del_dueno_simultanea_con_la_aprobacion(
    client, db, admin, crear_usuario, crear_equipamiento, crear_orden
):  # EC-L10, RN-L14
    """Una prospera. La otra recibe el error de su acción sobre el estado que dejó la primera:
    si ganó la cancelación, aprobar responde 409 TRANSICION_INVALIDA; si ganó la aprobación,
    cancelar una orden aprobada responde 403 CANCELACION_NO_PERMITIDA (AC-L32)."""
    for ronda in range(RONDAS):
        dueño = await crear_usuario(RolUsuario.ESTUDIANTE, SedeEnum.USHUAIA)
        camara = await crear_equipamiento()
        orden = await crear_orden(camara, solicitante=dueño)

        aprobar, cancelar = await asyncio.gather(
            _patch(client, admin, orden, _aprobacion(orden, camara.unidades[0].id)),
            _patch(client, dueño, orden, CANCELACION),
        )

        final = await _orden_en_base(db, orden.id)
        if aprobar.status_code == 200:
            assert cancelar.status_code == 403, (ronda, cancelar.json())
            assert cancelar.json()["code"] == "CANCELACION_NO_PERMITIDA"
            assert final.estado is EstadoOrdenEnum.APROBADA
            assert final.detalles[0].estado is EstadoDetalleEnum.RESERVADO
        else:
            assert cancelar.status_code == 200, (ronda, cancelar.json(), aprobar.json())
            assert aprobar.status_code == 409, (ronda, aprobar.json())
            assert aprobar.json()["code"] == "TRANSICION_INVALIDA"
            assert final.estado is EstadoOrdenEnum.CANCELADA
            assert final.detalles[0].estado is EstadoDetalleEnum.CANCELADO
            assert final.detalles[0].unidad_fisica_id is None
        assert await _transiciones(db, orden.id) == 1
