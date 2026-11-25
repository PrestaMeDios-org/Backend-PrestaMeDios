"""Mostrador: entregar, recibir la devolución y cancelación forzada (SPEC-05 Fase 3).

`PATCH /ordenes/{id}/detalles/{detalle_id}/estado` (PRE-13, PRE-17; plan §9.4.1):
AC-L34…L39, L59 y la parte de AC-L62 que no depende del no retiro (Fase 4). También el
filtro `situacion` de la bandeja (spec v1.0.3) y el historial de la unidad con los
datos reales (T3.8).
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.enums import RolUsuario, SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum
from app.modules.inventory.models import UnidadFisica
from app.modules.loans import service
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum
from app.modules.loans.models import DetallePrestamo, OrdenHistorialEstado, OrdenPedido
from tests.conftest import TZ, auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
L, U = EstadoDetalleEnum, EstadoUnidadEnum

# La unidad que corresponde a cada estado de la línea: una reservada está en el estante
# y una entregada, prestada.
UNIDAD_SEGUN_LINEA = {
    L.RESERVADO: U.DISPONIBLE,
    L.ENTREGADO: U.PRESTADO,
    L.DEVUELTO: U.DISPONIBLE,
    L.CANCELADO: U.DISPONIBLE,
    L.NO_RETIRADO: U.DISPONIBLE,
}
ENTREGAR = {"estado": "entregado"}
DEVOLVER = {"estado": "devuelto"}
FORZADA = {"estado": "cancelado", "motivo": "La unidad se dañó en otro préstamo"}


@pytest.fixture
def orden_aprobada(db, crear_usuario, crear_equipamiento):
    """Fábrica: una orden ``aprobada`` con una línea por estado, cada una con su unidad.

    ``unidades`` reemplaza el estado de las unidades (por defecto, el que corresponde a
    la línea). Devuelve ``(orden_id, [detalle_id, ...], [unidad_id, ...])``.
    """

    async def _crear(*estados: EstadoDetalleEnum, unidades=None, sede=USH, solicitante=None):
        solicitante = solicitante or await crear_usuario(E, sede)
        unidades = unidades or tuple(UNIDAD_SEGUN_LINEA[e] for e in estados)
        eq = await crear_equipamiento(sede=sede, estados=unidades)
        retiro = datetime(2026, 12, 1, 10, tzinfo=TZ)
        devolucion = retiro + timedelta(days=2, hours=5)
        detalles = [
            DetallePrestamo(
                equipamiento_id=eq.id,
                unidad_fisica_id=unidad.id,
                estado=estado,
                retiro_pactado=retiro,
                devolucion_pactada=devolucion,
                fin_ocupacion=devolucion,
                entregado_en=retiro if estado in (L.ENTREGADO, L.DEVUELTO) else None,
                devuelto_en=devolucion if estado is L.DEVUELTO else None,
            )
            for estado, unidad in zip(estados, eq.unidades, strict=True)
        ]
        orden = OrdenPedido(
            solicitante_id=solicitante._cache_auth["id"],
            sede=sede,
            estado=EstadoOrdenEnum.APROBADA,
            detalles=detalles,
        )
        db.add(orden)
        await db.commit()
        return orden.id, [d.id for d in detalles], [u.id for u in eq.unidades]

    return _crear


async def _patch(client, usuario, orden_id: int, detalle_id: int, cuerpo: dict):
    return await client.patch(
        f"{BASE}/ordenes/{orden_id}/detalles/{detalle_id}/estado",
        json=cuerpo,
        headers=auth(usuario),
    )


async def _linea(db, detalle_id: int) -> DetallePrestamo:
    stmt = (
        select(DetallePrestamo)
        .where(DetallePrestamo.id == detalle_id)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one()


async def _orden(db, orden_id: int) -> OrdenPedido:
    stmt = (
        select(OrdenPedido)
        .where(OrdenPedido.id == orden_id)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one()


async def _estado_unidad(db, unidad_id: int) -> EstadoUnidadEnum:
    stmt = (
        select(UnidadFisica)
        .where(UnidadFisica.id == unidad_id)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one().estado


async def _historial(db, orden_id: int) -> list[OrdenHistorialEstado]:
    stmt = select(OrdenHistorialEstado).where(OrdenHistorialEstado.orden_id == orden_id)
    return list((await db.scalars(stmt)).all())


@pytest.fixture
async def admin(crear_usuario):
    return await crear_usuario(A, USH)


# ── Entregar (RN-L19) ────────────────────────────────────────────────────────


async def test_entregar_deja_la_linea_entregada_y_la_unidad_prestada(
    client, db, admin, orden_aprobada
):  # AC-L36
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(L.RESERVADO)

    r = await _patch(client, admin, orden_id, detalle_id, ENTREGAR)

    assert r.status_code == 200
    (linea,) = r.json()["detalles"]
    assert linea["estado"] == "entregado" and linea["entregado_en"] is not None
    assert r.json()["estado"] == "aprobada"
    assert (await _linea(db, detalle_id)).entregado_en is not None
    assert await _estado_unidad(db, unidad_id) is U.PRESTADO
    assert await _historial(db, orden_id) == []  # entregar no cambia la orden


@pytest.mark.parametrize("estado_unidad", [U.MANTENIMIENTO, U.PRESTADO, U.BAJA])
async def test_si_la_unidad_no_esta_en_el_estante_la_entrega_falla_sin_cambios(
    client, db, admin, orden_aprobada, estado_unidad
):  # AC-L37, EC-L06, EC-L07
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(
        L.RESERVADO, unidades=(estado_unidad,)
    )

    r = await _patch(client, admin, orden_id, detalle_id, ENTREGAR)

    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_ESTADO_INVALIDA"
    linea = await _linea(db, detalle_id)
    assert linea.estado is L.RESERVADO and linea.entregado_en is None
    assert await _estado_unidad(db, unidad_id) is estado_unidad


@pytest.mark.parametrize("estado", [L.ENTREGADO, L.DEVUELTO, L.CANCELADO, L.NO_RETIRADO])
async def test_solo_se_entrega_una_linea_reservada(
    client, admin, orden_aprobada, estado
):  # AC-L39
    orden_id, (detalle_id,), _ = await orden_aprobada(estado)
    r = await _patch(client, admin, orden_id, detalle_id, ENTREGAR)
    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"


# ── Devolver (RN-L20) ────────────────────────────────────────────────────────


async def test_devolver_registra_la_fecha_y_la_observacion_y_libera_la_unidad(
    client, db, admin, orden_aprobada
):  # AC-L38
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(L.ENTREGADO)
    cuerpo = {**DEVOLVER, "observacion": "Vuelve con la tapa rayada"}

    r = await _patch(client, admin, orden_id, detalle_id, cuerpo)

    assert r.status_code == 200
    (linea,) = r.json()["detalles"]
    assert linea["estado"] == "devuelto"
    assert linea["devuelto_en"] is not None
    assert linea["observacion_devolucion"] == "Vuelve con la tapa rayada"
    assert await _estado_unidad(db, unidad_id) is U.DISPONIBLE
    # Sigue aprobada (RN-L30) y su situación pasa a finalizada (RN-L31).
    assert r.json()["estado"] == "aprobada" and r.json()["situacion"] == "finalizada"


async def test_devolver_sin_observacion(client, admin, orden_aprobada):
    orden_id, (detalle_id,), _ = await orden_aprobada(L.ENTREGADO)
    r = await _patch(client, admin, orden_id, detalle_id, DEVOLVER)
    assert r.status_code == 200
    assert r.json()["detalles"][0]["observacion_devolucion"] is None


async def test_devolver_con_dano_deja_la_unidad_en_mantenimiento(
    client, admin, orden_aprobada, sessionmaker_
):  # AC-L59, EC-L15
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(L.ENTREGADO)
    cuerpo = {**DEVOLVER, "observacion": "Pantalla rota", "a_mantenimiento": True}

    r = await _patch(client, admin, orden_id, detalle_id, cuerpo)

    assert r.status_code == 200
    assert r.json()["detalles"][0]["estado"] == "devuelto"
    # Leída desde otra sesión: lo que quedó en la base, no lo que tiene en memoria.
    async with sessionmaker_() as otra:
        assert (await otra.get(UnidadFisica, unidad_id)).estado is U.MANTENIMIENTO


@pytest.mark.parametrize("estado", [L.RESERVADO, L.DEVUELTO, L.CANCELADO])
async def test_solo_se_devuelve_una_linea_entregada(
    client, admin, orden_aprobada, estado
):  # AC-L39
    orden_id, (detalle_id,), _ = await orden_aprobada(estado)
    r = await _patch(client, admin, orden_id, detalle_id, DEVOLVER)
    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"


# ── Cancelación forzada (RN-L17) y cierre de la orden (RN-L30) ───────────────


async def test_la_cancelacion_forzada_exige_motivo(client, db, admin, orden_aprobada):  # AC-L35
    orden_id, (detalle_id,), _ = await orden_aprobada(L.RESERVADO)
    r = await _patch(client, admin, orden_id, detalle_id, {"estado": "cancelado"})
    assert r.status_code == 422
    assert r.json()["code"] == "MOTIVO_REQUERIDO"
    assert (await _linea(db, detalle_id)).estado is L.RESERVADO


async def test_la_ultima_linea_vigente_cierra_la_orden(
    client, db, admin, orden_aprobada
):  # AC-L35, RN-L30
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(L.RESERVADO)

    r = await _patch(client, admin, orden_id, detalle_id, FORZADA)

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "cancelada"
    assert cuerpo["motivo_resolucion"] == FORZADA["motivo"]
    assert cuerpo["resuelto_en"] is not None
    (linea,) = cuerpo["detalles"]
    assert linea["estado"] == "cancelado" and linea["motivo_cancelacion"] == FORZADA["motivo"]
    (fila,) = await _historial(db, orden_id)
    assert (fila.estado_anterior, fila.estado_nuevo) == (
        EstadoOrdenEnum.APROBADA,
        EstadoOrdenEnum.CANCELADA,
    )
    assert fila.actor_id == admin._cache_auth["id"] and fila.motivo == FORZADA["motivo"]
    # No toca el estado físico de la unidad: eso es de inventory.
    assert await _estado_unidad(db, unidad_id) is U.DISPONIBLE


async def test_la_cancelacion_forzada_no_toca_una_unidad_en_mantenimiento(
    client, db, admin, orden_aprobada
):  # EC-L06
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(
        L.RESERVADO, unidades=(U.MANTENIMIENTO,)
    )
    r = await _patch(client, admin, orden_id, detalle_id, FORZADA)
    assert r.status_code == 200
    assert await _estado_unidad(db, unidad_id) is U.MANTENIMIENTO


async def test_con_otra_linea_reservada_la_orden_sigue_aprobada_hasta_la_ultima(
    client, db, admin, orden_aprobada
):  # AC-L62 (parte forzada), RN-L30
    orden_id, (primera, segunda), _ = await orden_aprobada(L.RESERVADO, L.RESERVADO)

    r = await _patch(client, admin, orden_id, primera, FORZADA)
    assert r.status_code == 200 and r.json()["estado"] == "aprobada"
    assert await _historial(db, orden_id) == []

    r = await _patch(client, admin, orden_id, segunda, FORZADA)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"


@pytest.mark.parametrize("otra", [L.DEVUELTO, L.ENTREGADO])
async def test_si_algo_se_entrego_la_orden_no_se_cancela(
    client, db, admin, orden_aprobada, otra
):  # RN-L30
    orden_id, (detalle_id, _), _ = await orden_aprobada(L.RESERVADO, otra)
    r = await _patch(client, admin, orden_id, detalle_id, FORZADA)
    assert r.status_code == 200
    assert r.json()["estado"] == "aprobada"
    assert (await _orden(db, orden_id)).resuelto_en is None


@pytest.mark.parametrize("estado", [L.ENTREGADO, L.DEVUELTO, L.CANCELADO])
async def test_solo_se_cancela_a_la_fuerza_una_linea_reservada(
    client, admin, orden_aprobada, estado
):
    orden_id, (detalle_id,), _ = await orden_aprobada(estado)
    r = await _patch(client, admin, orden_id, detalle_id, FORZADA)
    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"


# ── Cancelar la orden completa con algo entregado (RN-L16, spec v1.0.3) ──────


@pytest.mark.parametrize("otra", [L.DEVUELTO, L.ENTREGADO])
async def test_no_se_cancela_una_orden_con_lineas_ya_entregadas(
    client, db, admin, orden_aprobada, otra
):  # AC-L34
    orden_id, (reservada, _), _ = await orden_aprobada(L.RESERVADO, otra)
    r = await client.patch(
        f"{BASE}/ordenes/{orden_id}/estado",
        json={"estado": "cancelada", "motivo": "Se suspende la cursada"},
        headers=auth(admin),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "TRANSICION_INVALIDA"
    assert (await _linea(db, reservada)).estado is L.RESERVADO


# ── Permisos, alcance y forma del pedido ─────────────────────────────────────


@pytest.mark.parametrize("rol", [E, D])
async def test_estudiantes_y_docentes_no_operan_el_mostrador(
    client, crear_usuario, orden_aprobada, rol
):  # AC-L52
    dueño = await crear_usuario(rol, USH)
    orden_id, (detalle_id,), _ = await orden_aprobada(L.RESERVADO, solicitante=dueño)
    r = await _patch(client, dueño, orden_id, detalle_id, ENTREGAR)
    assert r.status_code == 403


async def test_el_admin_de_otra_sede_recibe_404(client, crear_usuario, orden_aprobada):
    orden_id, (detalle_id,), _ = await orden_aprobada(L.RESERVADO)
    r = await _patch(client, await crear_usuario(A, RG), orden_id, detalle_id, ENTREGAR)
    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"


async def test_el_superadmin_opera_cualquier_sede(client, crear_usuario, orden_aprobada):
    orden_id, (detalle_id,), _ = await orden_aprobada(L.RESERVADO, sede=RG)
    r = await _patch(client, await crear_usuario(S), orden_id, detalle_id, ENTREGAR)
    assert r.status_code == 200


async def test_una_linea_de_otra_orden_responde_404(client, admin, orden_aprobada):
    # spec v1.0.3, §6.3: no se distingue de una orden inexistente
    orden_id, _, _ = await orden_aprobada(L.RESERVADO)
    _, (ajena,), _ = await orden_aprobada(L.RESERVADO)
    r = await _patch(client, admin, orden_id, ajena, ENTREGAR)
    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"


async def test_orden_inexistente_responde_404(client, admin):
    r = await _patch(client, admin, 999_999, 1, ENTREGAR)
    assert r.status_code == 404


async def test_sin_sesion_responde_401(client):  # AC-L52
    r = await client.patch(f"{BASE}/ordenes/1/detalles/1/estado", json=ENTREGAR)
    assert r.status_code == 401


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"estado": "entregado", "observacion": "x"},
        {"estado": "entregado", "a_mantenimiento": True},
        {"estado": "cancelado", "motivo": "x", "observacion": "x"},
        {"estado": "devuelto", "motivo": "x"},
        {"estado": "entregado", "motivo": "x"},
        {"estado": "pendiente"},
        {"estado": "devuelto", "observacion": "x" * 501},
        {"estado": "entregado", "otro": 1},
    ],
)
async def test_campos_que_no_corresponden_al_estado_responden_422(
    client, admin, orden_aprobada, cuerpo
):
    orden_id, (detalle_id,), _ = await orden_aprobada(L.RESERVADO)
    r = await _patch(client, admin, orden_id, detalle_id, cuerpo)
    assert r.status_code == 422


# ── Lista del mostrador: `situacion` en la bandeja (spec v1.0.3) ─────────────


async def test_la_bandeja_filtra_por_situacion(client, admin, orden_aprobada):
    en_curso, _, _ = await orden_aprobada(L.RESERVADO, L.DEVUELTO)
    prestada, _, _ = await orden_aprobada(L.ENTREGADO)
    terminada, _, _ = await orden_aprobada(L.DEVUELTO, L.CANCELADO)

    async def ids(**params) -> set[int]:
        r = await client.get(
            f"{BASE}/ordenes", params={"estado": "aprobada", **params}, headers=auth(admin)
        )
        assert r.status_code == 200
        return {o["id"] for o in r.json()}

    assert await ids(situacion="en_curso") == {en_curso, prestada}
    assert await ids(situacion="finalizada") == {terminada}
    assert await ids() == {en_curso, prestada, terminada}  # sin filtro, como antes


# ── Historial de la unidad con los datos del mostrador (T3.8) ────────────────


async def test_el_historial_de_la_unidad_trae_la_entrega_y_la_devolucion(
    client, db, admin, orden_aprobada
):  # PRE-12
    orden_id, (detalle_id,), (unidad_id,) = await orden_aprobada(L.RESERVADO)
    await _patch(client, admin, orden_id, detalle_id, ENTREGAR)
    await _patch(
        client, admin, orden_id, detalle_id, {**DEVOLVER, "observacion": "Sin novedades"}
    )

    (movimiento,) = await service.historial_de_unidad(db, unidad_id, admin)

    assert movimiento.estado is L.DEVUELTO
    assert movimiento.entregado_en is not None and movimiento.devuelto_en is not None
    assert movimiento.devuelto_en >= movimiento.entregado_en
    assert movimiento.observacion_devolucion == "Sin novedades"
