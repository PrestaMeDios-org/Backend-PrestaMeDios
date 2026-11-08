"""Aprobar una orden (SPEC-05 Fase 2). Por ahora, T2.5: unidades libres por línea.

`GET /ordenes/{id}/unidades-libres` (RN-L12; AC-L47, AC-L58): por cada línea, las
unidades del modelo en la sede de la orden que están `disponible` y sin otra línea
`reservado` o `entregado` que se solape con su período. Las órdenes de estos tests
piden del 2/12 10:00 al 4/12 15:00. `crear_linea(..., dia=d)` ocupa del d/12 10:00 al
(d+2)/12 15:00.
"""

from datetime import datetime

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum as U
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum
from app.modules.loans.models import DetallePrestamo, OrdenPedido
from tests.conftest import TZ, auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
RETIRO = datetime(2026, 12, 2, 10, tzinfo=TZ)
DEVOLUCION = datetime(2026, 12, 4, 15, tzinfo=TZ)


@pytest.fixture
def crear_orden(db, crear_usuario):
    """Fábrica: una orden ``pendiente`` con una línea por cada equipamiento indicado."""

    async def _crear(*equipamientos, sede: SedeEnum = USH, solicitante=None) -> OrdenPedido:
        solicitante = solicitante or await crear_usuario(E, sede)
        orden = OrdenPedido(
            solicitante_id=solicitante._cache_auth["id"],
            sede=sede,
            estado=EstadoOrdenEnum.PENDIENTE,
            detalles=[
                DetallePrestamo(
                    equipamiento_id=eq.id,
                    estado=EstadoDetalleEnum.PENDIENTE,
                    retiro_pactado=RETIRO,
                    devolucion_pactada=DEVOLUCION,
                    fin_ocupacion=DEVOLUCION,
                )
                for eq in equipamientos
            ],
        )
        db.add(orden)
        await db.commit()
        return orden

    return _crear


def _ids(equipamiento) -> list[int]:
    """Ids de las unidades en el orden en que las devuelve `inventory` (por código)."""
    return [u.id for u in sorted(equipamiento.unidades, key=lambda u: u.codigo_inventario)]


async def _libres(client, usuario, orden_id: int):
    return await client.get(f"{BASE}/ordenes/{orden_id}/unidades-libres", headers=auth(usuario))


async def _por_linea(client, usuario, orden_id: int) -> dict[int, list[int]]:
    r = await _libres(client, usuario, orden_id)
    assert r.status_code == 200, r.json()
    return {linea["detalle_id"]: linea["unidades"] for linea in r.json()}


# ── GET /ordenes/{id}/unidades-libres ────────────────────────────────────────


async def test_devuelve_las_unidades_libres_de_cada_linea(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L58
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    tripode = await crear_equipamiento(estados=(U.DISPONIBLE,))
    orden = await crear_orden(camara, camara, tripode)
    admin = await crear_usuario(A, USH)

    r = await _libres(client, admin, orden.id)

    assert r.status_code == 200, r.json()
    assert r.json() == [
        {"detalle_id": d.id, "equipamiento_id": d.equipamiento_id, "unidades": unidades}
        for d, unidades in zip(
            orden.detalles, [_ids(camara), _ids(camara), _ids(tripode)], strict=True
        )
    ]


async def test_solo_cuentan_las_unidades_disponibles(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L58, PRE-14
    camara = await crear_equipamiento(estados=(U.DISPONIBLE, U.PRESTADO, U.MANTENIMIENTO, U.BAJA))
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    assert await _por_linea(client, admin, orden.id) == {orden.detalles[0].id: [_ids(camara)[0]]}


async def test_solo_cuentan_las_unidades_de_la_sede_de_la_orden(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L58, P5
    de_rio_grande = await crear_equipamiento(sede=RG)
    orden = await crear_orden(de_rio_grande)
    superadmin = await crear_usuario(S)

    assert await _por_linea(client, superadmin, orden.id) == {orden.detalles[0].id: []}


async def test_una_reserva_que_se_solapa_excluye_la_unidad(
    client, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # AC-L47, RN-L12
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    ocupada, libre = _ids(camara)
    unidad = next(u for u in camara.unidades if u.id == ocupada)
    await crear_linea(camara, unidad, EstadoDetalleEnum.RESERVADO, dia=1)  # 1/12 al 3/12
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    assert await _por_linea(client, admin, orden.id) == {orden.detalles[0].id: [libre]}


async def test_una_reserva_en_otras_fechas_no_excluye_la_unidad(
    client, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # AC-L47: criterio por fechas (D-L17 descartada)
    camara = await crear_equipamiento()
    await crear_linea(camara, camara.unidades[0], EstadoDetalleEnum.RESERVADO, dia=10)
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    assert await _por_linea(client, admin, orden.id) == {orden.detalles[0].id: _ids(camara)}


@pytest.mark.parametrize(
    "estado",
    [EstadoDetalleEnum.DEVUELTO, EstadoDetalleEnum.CANCELADO, EstadoDetalleEnum.NO_RETIRADO],
)
async def test_una_linea_que_ya_libero_la_unidad_no_la_ocupa(
    client, crear_usuario, crear_equipamiento, crear_linea, crear_orden, estado
):  # RN-L12
    camara = await crear_equipamiento()
    await crear_linea(camara, camara.unidades[0], estado, dia=1)
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    assert await _por_linea(client, admin, orden.id) == {orden.detalles[0].id: _ids(camara)}


async def test_las_otras_ordenes_pendientes_no_ocupan(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # RN-L03: la unidad se asigna recién al aprobar
    camara = await crear_equipamiento()
    await crear_orden(camara)
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    assert await _por_linea(client, admin, orden.id) == {orden.detalles[0].id: _ids(camara)}


async def test_solo_devuelve_ids(client, crear_usuario, crear_equipamiento, crear_orden):
    # P6, plan §8.5.6: ni datos del solicitante ni de otras reservas
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    r = await _libres(client, admin, orden.id)
    assert set(r.json()[0]) == {"detalle_id", "equipamiento_id", "unidades"}


async def test_un_admin_de_otra_sede_recibe_404(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # RN-L26
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin_rg = await crear_usuario(A, RG)

    r = await _libres(client, admin_rg, orden.id)

    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"


async def test_una_orden_inexistente_responde_404(client, crear_usuario):
    admin = await crear_usuario(A, USH)
    r = await _libres(client, admin, 999)
    assert r.status_code == 404


@pytest.mark.parametrize("rol", [E, D])
async def test_estudiantes_y_docentes_reciben_403_aun_siendo_duenos(
    client, crear_usuario, crear_equipamiento, crear_orden, rol
):  # es una herramienta del administrador para aprobar
    dueño = await crear_usuario(rol, USH)
    camara = await crear_equipamiento()
    orden = await crear_orden(camara, solicitante=dueño)

    r = await _libres(client, dueño, orden.id)

    assert r.status_code == 403
