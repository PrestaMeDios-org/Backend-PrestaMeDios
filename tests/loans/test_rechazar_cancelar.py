"""Rechazar y cancelar la propia orden (SPEC-05 Fase 2, T2.6; AC-L27, L28, L29, L31, L32).

`PATCH /ordenes/{id}/estado`: el administrador con jurisdicción rechaza una orden
`pendiente` con motivo; el solicitante cancela su orden `pendiente`. Cada transición
deja la resolución (`resuelto_por_id`, `resuelto_en`) y una fila en
`ordenes_historial_estado` (D-L10). Aprobar (T2.7) y la cancelación de una `aprobada`
por el administrador (T2.9) todavía responden 501.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.enums import RolUsuario, SedeEnum
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum
from app.modules.loans.models import DetallePrestamo, OrdenHistorialEstado, OrdenPedido
from tests.conftest import TZ, auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
P = EstadoOrdenEnum.PENDIENTE

RECHAZO = {"estado": "rechazada", "motivo": "Sin stock para esas fechas"}
CANCELACION = {"estado": "cancelada"}
APROBACION = {"estado": "aprobada", "asignaciones": [{"detalle_id": 1, "unidad_fisica_id": 1}]}

ESTADO_LINEA = {
    EstadoOrdenEnum.PENDIENTE: EstadoDetalleEnum.PENDIENTE,
    EstadoOrdenEnum.RECHAZADA: EstadoDetalleEnum.RECHAZADO,
    EstadoOrdenEnum.CANCELADA: EstadoDetalleEnum.CANCELADO,
}


@pytest.fixture
def crear_orden(db, crear_equipamiento):
    """Fábrica: una orden con dos líneas sin unidad, en el estado indicado."""

    async def _crear(solicitante, estado: EstadoOrdenEnum = P, sede: SedeEnum = USH):
        equipamiento = await crear_equipamiento(sede=sede)
        retiro = datetime(2026, 12, 1, 10, tzinfo=TZ)
        devolucion = retiro + timedelta(days=2, hours=5)
        orden = OrdenPedido(
            solicitante_id=solicitante._cache_auth["id"],
            sede=sede,
            estado=estado,
            detalles=[
                DetallePrestamo(
                    equipamiento_id=equipamiento.id,
                    estado=ESTADO_LINEA[estado],
                    retiro_pactado=retiro,
                    devolucion_pactada=devolucion,
                    fin_ocupacion=devolucion,
                )
                for _ in range(2)
            ],
        )
        db.add(orden)
        await db.commit()
        return orden.id

    return _crear


async def _patch(client, usuario, orden_id: int, cuerpo: dict):
    return await client.patch(
        f"{BASE}/ordenes/{orden_id}/estado", json=cuerpo, headers=auth(usuario)
    )


async def _orden(db, orden_id: int) -> OrdenPedido:
    """La orden tal como quedó en la base (sin lo que tenga en caché la sesión)."""
    stmt = (
        select(OrdenPedido)
        .where(OrdenPedido.id == orden_id)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one()


async def _historial(db, orden_id: int) -> list[OrdenHistorialEstado]:
    stmt = select(OrdenHistorialEstado).where(OrdenHistorialEstado.orden_id == orden_id)
    return list((await db.scalars(stmt)).all())


def _id(usuario) -> int:
    return usuario._cache_auth["id"]


async def _orden_aprobada(db, solicitante) -> int:
    """Una orden ``aprobada`` sin líneas: alcanza para los controles de transición."""
    orden = OrdenPedido(solicitante_id=_id(solicitante), sede=USH, estado=EstadoOrdenEnum.APROBADA)
    db.add(orden)
    await db.commit()
    return orden.id


async def _sin_cambios(db, orden_id: int, estado: EstadoOrdenEnum) -> None:
    orden = await _orden(db, orden_id)
    assert orden.estado is estado
    assert orden.resuelto_por_id is None and orden.resuelto_en is None
    assert await _historial(db, orden_id) == []


# ── Rechazar ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("rol", "sede_admin"), [(A, USH), (S, None)])
async def test_el_admin_rechaza_con_motivo(
    client, db, crear_usuario, crear_orden, rol, sede_admin
):  # AC-L27, RN-L15
    ana = await crear_usuario(E, USH, nombre="Ana", apellido="Pérez")
    orden_id = await crear_orden(ana)
    admin = await crear_usuario(rol, sede_admin)

    r = await _patch(client, admin, orden_id, RECHAZO)

    assert r.status_code == 200, r.json()
    cuerpo = r.json()
    assert cuerpo["estado"] == "rechazada"
    assert cuerpo["motivo_resolucion"] == RECHAZO["motivo"]
    assert [d["estado"] for d in cuerpo["detalles"]] == ["rechazado", "rechazado"]
    assert cuerpo["situacion"] == "finalizada"  # RN-L31
    assert cuerpo["resuelto_en"] is not None
    assert cuerpo["solicitante"]["nombre"] == "Ana"
    orden = await _orden(db, orden_id)
    assert orden.resuelto_por_id == _id(admin)


async def test_el_rechazo_queda_en_el_historial(client, db, crear_usuario, crear_orden):
    # D-L10, P7.3
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    admin = await crear_usuario(A, USH)

    await _patch(client, admin, orden_id, RECHAZO)

    [fila] = await _historial(db, orden_id)
    assert fila.estado_anterior is EstadoOrdenEnum.PENDIENTE
    assert fila.estado_nuevo is EstadoOrdenEnum.RECHAZADA
    assert fila.motivo == RECHAZO["motivo"]
    assert fila.actor_id == _id(admin)
    assert fila.created_at is not None


async def test_rechazar_sin_motivo_responde_422_y_no_cambia_nada(
    client, db, crear_usuario, crear_orden
):  # AC-L27
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    admin = await crear_usuario(A, USH)

    r = await _patch(client, admin, orden_id, {"estado": "rechazada"})

    assert r.status_code == 422
    assert r.json()["code"] == "MOTIVO_REQUERIDO"
    await _sin_cambios(db, orden_id, P)


async def test_un_motivo_en_blanco_no_alcanza(client, db, crear_usuario, crear_orden):
    # AC-L27: el esquema recorta los espacios y exige al menos un carácter
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    admin = await crear_usuario(A, USH)
    r = await _patch(client, admin, orden_id, {"estado": "rechazada", "motivo": "   "})
    assert r.status_code == 422
    await _sin_cambios(db, orden_id, P)


@pytest.mark.parametrize(
    "estado", [EstadoOrdenEnum.RECHAZADA, EstadoOrdenEnum.CANCELADA, EstadoOrdenEnum.APROBADA]
)
async def test_solo_se_rechaza_una_pendiente(
    client, db, crear_usuario, crear_orden, estado
):  # AC-L28
    ana = await crear_usuario(E, USH)
    if estado is EstadoOrdenEnum.APROBADA:
        orden_id = await _orden_aprobada(db, ana)
    else:
        orden_id = await crear_orden(ana, estado)
    admin = await crear_usuario(A, USH)

    r = await _patch(client, admin, orden_id, RECHAZO)

    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"
    assert (await _orden(db, orden_id)).estado is estado


async def test_la_transicion_se_controla_antes_que_el_motivo(
    client, db, crear_usuario, crear_orden
):  # plan §8.5.4: 409 antes que 422
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana, EstadoOrdenEnum.RECHAZADA)
    admin = await crear_usuario(A, USH)
    r = await _patch(client, admin, orden_id, {"estado": "rechazada"})
    assert r.status_code == 409


async def test_un_admin_de_otra_sede_recibe_404(client, db, crear_usuario, crear_orden):
    # AC-L29, RN-L26
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    admin_rg = await crear_usuario(A, RG)

    r = await _patch(client, admin_rg, orden_id, RECHAZO)

    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"
    await _sin_cambios(db, orden_id, P)


async def test_una_orden_inexistente_responde_404(client, crear_usuario):
    admin = await crear_usuario(A, USH)
    r = await _patch(client, admin, 999, RECHAZO)
    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"


@pytest.mark.parametrize("rol", [E, D])
@pytest.mark.parametrize("cuerpo", [RECHAZO, APROBACION])
async def test_el_dueño_no_puede_aprobar_ni_rechazar(
    client, db, crear_usuario, crear_orden, rol, cuerpo
):  # AC-L29: el control es por rol y no revela si la orden existe
    dueño = await crear_usuario(rol, USH)
    orden_id = await crear_orden(dueño)

    propia = await _patch(client, dueño, orden_id, cuerpo)
    inexistente = await _patch(client, dueño, 999, cuerpo)

    assert propia.status_code == inexistente.status_code == 403
    assert propia.json()["code"] == "ROL_NO_AUTORIZADO"
    await _sin_cambios(db, orden_id, P)


# ── Cancelar la propia ───────────────────────────────────────────────────────


@pytest.mark.parametrize("rol", [E, D])
async def test_el_dueño_cancela_su_orden_pendiente(
    client, db, crear_usuario, crear_orden, rol
):  # AC-L31, RN-L16
    dueño = await crear_usuario(rol, USH)
    orden_id = await crear_orden(dueño)

    r = await _patch(client, dueño, orden_id, CANCELACION)

    assert r.status_code == 200, r.json()
    cuerpo = r.json()
    assert cuerpo["estado"] == "cancelada"
    assert [d["estado"] for d in cuerpo["detalles"]] == ["cancelado", "cancelado"]
    assert cuerpo["motivo_resolucion"] is None
    assert cuerpo["resuelto_en"] is not None
    assert cuerpo["solicitante"] is None  # el dueño no recibe su resumen
    orden = await _orden(db, orden_id)
    assert orden.resuelto_por_id == _id(dueño)
    [fila] = await _historial(db, orden_id)
    assert (fila.estado_anterior, fila.estado_nuevo) == (P, EstadoOrdenEnum.CANCELADA)
    assert fila.actor_id == _id(dueño)
    assert fila.motivo is None


async def test_el_dueño_puede_dejar_un_motivo(client, db, crear_usuario, crear_orden):
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)

    r = await _patch(client, ana, orden_id, {"estado": "cancelada", "motivo": "Ya no lo uso"})

    assert r.status_code == 200
    assert r.json()["motivo_resolucion"] == "Ya no lo uso"
    [fila] = await _historial(db, orden_id)
    assert fila.motivo == "Ya no lo uso"


async def test_el_dueño_no_puede_cancelar_una_aprobada(client, db, crear_usuario):
    # AC-L32
    ana = await crear_usuario(E, USH)
    orden_id = await _orden_aprobada(db, ana)

    r = await _patch(client, ana, orden_id, CANCELACION)

    assert r.status_code == 403
    assert r.json()["code"] == "CANCELACION_NO_PERMITIDA"
    await _sin_cambios(db, orden_id, EstadoOrdenEnum.APROBADA)


@pytest.mark.parametrize("estado", [EstadoOrdenEnum.RECHAZADA, EstadoOrdenEnum.CANCELADA])
async def test_el_dueño_no_cancela_una_orden_cerrada(
    client, db, crear_usuario, crear_orden, estado
):  # AC-L28
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana, estado)
    r = await _patch(client, ana, orden_id, CANCELACION)
    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"


@pytest.mark.parametrize("rol", [E, D])
async def test_nadie_cancela_una_orden_ajena(
    client, db, crear_usuario, crear_orden, rol
):  # RN-L25: otro solicitante, aun de la misma sede, recibe 404
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    otro = await crear_usuario(rol, USH)

    r = await _patch(client, otro, orden_id, CANCELACION)

    assert r.status_code == 404
    await _sin_cambios(db, orden_id, P)


async def test_el_admin_no_cancela_una_pendiente(client, db, crear_usuario, crear_orden):
    # AC-L28, RN-L16: una pendiente se rechaza, no se cancela
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    admin = await crear_usuario(A, USH)

    r = await _patch(client, admin, orden_id, {"estado": "cancelada", "motivo": "x"})

    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"
    await _sin_cambios(db, orden_id, P)


# ── Pendientes de T2.7 y T2.9 ────────────────────────────────────────────────


async def test_aprobar_todavia_responde_501(client, db, crear_usuario, crear_orden):
    # Se reemplaza en T2.7 (test_aprobar.py)
    ana = await crear_usuario(E, USH)
    orden_id = await crear_orden(ana)
    admin = await crear_usuario(A, USH)

    r = await _patch(client, admin, orden_id, APROBACION)

    assert r.status_code == 501
    assert r.json()["code"] == "NO_IMPLEMENTADO"
    await _sin_cambios(db, orden_id, P)


async def test_el_admin_cancela_una_aprobada_todavia_responde_501(client, db, crear_usuario):
    # Se reemplaza en T2.9
    ana = await crear_usuario(E, USH)
    orden_id = await _orden_aprobada(db, ana)
    admin = await crear_usuario(A, USH)
    r = await _patch(client, admin, orden_id, {"estado": "cancelada", "motivo": "Rota"})
    assert r.status_code == 501
