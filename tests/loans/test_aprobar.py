"""Aprobar una orden (SPEC-05 Fase 2, T2.5, T2.7 y T2.10).

- `GET /ordenes/{id}/unidades-libres` (RN-L12; AC-L47, AC-L58): por cada línea, las
  unidades del modelo en la sede de la orden que están `disponible` y sin otra línea
  `reservado` o `entregado` que se solape con su período.
- `PATCH /ordenes/{id}/estado` con `aprobada` (RN-L11…L14, RN-L18, RN-L27; AC-L19…L23,
  L25, L26, L30, L47, L53): una unidad por línea, todo o nada, con ajuste horario opcional.

Las órdenes de estos tests piden de `RETIRO` (dentro de una semana, 10:00) a
`DEVOLUCION` (dos días después, 15:00). `crear_linea(..., retiro=r)` ocupa de `r` a dos
días después a las 15:00, así que `RETIRO - 1 día` se solapa y `RETIRO + 10 días` no.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.enums import RolUsuario, SedeEnum
from app.core.settings import ahora_lab
from app.modules.inventory.enums import EstadoUnidadEnum as U
from app.modules.inventory.models import UnidadFisica
from app.modules.loans import service
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum
from app.modules.loans.models import DetallePrestamo, OrdenHistorialEstado, OrdenPedido
from tests.conftest import auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
RETIRO = (ahora_lab() + timedelta(days=7)).replace(hour=10, minute=0, second=0, microsecond=0)
DEVOLUCION = RETIRO + timedelta(days=2, hours=5)
SOLAPADO = RETIRO - timedelta(days=1)
EN_OTRAS_FECHAS = RETIRO + timedelta(days=10)


@pytest.fixture
def crear_orden(db, crear_usuario):
    """Fábrica: una orden ``pendiente`` con una línea por cada equipamiento indicado."""

    async def _crear(
        *equipamientos, sede: SedeEnum = USH, solicitante=None, retiro: datetime = RETIRO
    ) -> OrdenPedido:
        solicitante = solicitante or await crear_usuario(E, sede)
        devolucion = retiro + (DEVOLUCION - RETIRO)
        orden = OrdenPedido(
            solicitante_id=solicitante._cache_auth["id"],
            sede=sede,
            estado=EstadoOrdenEnum.PENDIENTE,
            detalles=[
                DetallePrestamo(
                    equipamiento_id=eq.id,
                    estado=EstadoDetalleEnum.PENDIENTE,
                    retiro_pactado=retiro,
                    devolucion_pactada=devolucion,
                    fin_ocupacion=devolucion,
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
    await crear_linea(camara, unidad, EstadoDetalleEnum.RESERVADO, retiro=SOLAPADO)
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    assert await _por_linea(client, admin, orden.id) == {orden.detalles[0].id: [libre]}


async def test_una_reserva_en_otras_fechas_no_excluye_la_unidad(
    client, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # AC-L47: criterio por fechas (D-L17 descartada)
    camara = await crear_equipamiento()
    await crear_linea(
        camara, camara.unidades[0], EstadoDetalleEnum.RESERVADO, retiro=EN_OTRAS_FECHAS
    )
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
    await crear_linea(camara, camara.unidades[0], estado, retiro=SOLAPADO)
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


# ── PATCH /ordenes/{id}/estado: aprobar ──────────────────────────────────────


async def _aprobar(client, usuario, orden: OrdenPedido, unidades: list[int], **extra):
    cuerpo = {
        "estado": "aprobada",
        "asignaciones": [
            {"detalle_id": d.id, "unidad_fisica_id": u}
            for d, u in zip(orden.detalles, unidades, strict=False)
        ],
        **extra,
    }
    return await client.patch(
        f"{BASE}/ordenes/{orden.id}/estado", json=cuerpo, headers=auth(usuario)
    )


async def _en_base(db, orden_id: int) -> OrdenPedido:
    stmt = (
        select(OrdenPedido)
        .where(OrdenPedido.id == orden_id)
        .execution_options(populate_existing=True)
    )
    return (await db.scalars(stmt)).one()


async def _historial(db, orden_id: int) -> list[OrdenHistorialEstado]:
    stmt = select(OrdenHistorialEstado).where(OrdenHistorialEstado.orden_id == orden_id)
    return list((await db.scalars(stmt)).all())


async def _sigue_pendiente(db, orden_id: int) -> None:
    """Sin cambios parciales (RN-L13): ni estado, ni unidades, ni resolución, ni historial."""
    orden = await _en_base(db, orden_id)
    assert orden.estado is EstadoOrdenEnum.PENDIENTE
    assert orden.resuelto_por_id is None and orden.resuelto_en is None
    assert all(d.estado is EstadoDetalleEnum.PENDIENTE for d in orden.detalles)
    assert all(d.unidad_fisica_id is None for d in orden.detalles)
    assert await _historial(db, orden_id) == []


def _codigo(r) -> str:
    return r.json().get("code")


@pytest.mark.parametrize(("rol", "sede_admin"), [(A, USH), (S, None)])
async def test_aprobar_reserva_una_unidad_por_linea(
    client, db, crear_usuario, crear_equipamiento, crear_orden, rol, sede_admin
):  # AC-L19, RN-L11
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    tripode = await crear_equipamiento()
    orden = await crear_orden(camara, camara, tripode)
    admin = await crear_usuario(rol, sede_admin)
    unidades = [*_ids(camara), *_ids(tripode)]

    r = await _aprobar(client, admin, orden, unidades)

    assert r.status_code == 200, r.json()
    cuerpo = r.json()
    assert cuerpo["estado"] == "aprobada"
    assert [(d["estado"], d["unidad_fisica_id"]) for d in cuerpo["detalles"]] == [
        ("reservado", u) for u in unidades
    ]
    assert cuerpo["resuelto_en"] is not None
    assert cuerpo["situacion"] == "en_curso"
    assert cuerpo["solicitante"] is not None
    en_base = await _en_base(db, orden.id)
    assert en_base.resuelto_por_id == admin._cache_auth["id"]
    [fila] = await _historial(db, orden.id)
    assert (fila.estado_anterior, fila.estado_nuevo) == (
        EstadoOrdenEnum.PENDIENTE,
        EstadoOrdenEnum.APROBADA,
    )
    assert fila.actor_id == admin._cache_auth["id"]


async def test_aprobar_no_cambia_el_estado_de_la_unidad(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # DT-20: la unidad pasa a prestado recién al entregar (Fase 3)
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    await _aprobar(client, admin, orden, _ids(camara))

    unidad = await db.get(UnidadFisica, _ids(camara)[0], populate_existing=True)
    assert unidad.estado is U.DISPONIBLE


async def test_aprobar_guarda_el_motivo_si_viene(
    client, crear_usuario, crear_equipamiento, crear_orden
):
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    r = await _aprobar(client, admin, orden, _ids(camara), motivo="Retira en el mostrador 2")
    assert r.json()["motivo_resolucion"] == "Retira en el mostrador 2"


async def test_la_unidad_aprobada_deja_de_estar_libre_para_otra_orden(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L58, RN-L12
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    primera, segunda = await crear_orden(camara), await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    reservada, otra = _ids(camara)

    await _aprobar(client, admin, primera, [reservada])

    assert await _por_linea(client, admin, segunda.id) == {segunda.detalles[0].id: [otra]}


@pytest.mark.parametrize("estado", [U.PRESTADO, U.MANTENIMIENTO, U.BAJA])
async def test_una_unidad_que_no_esta_disponible_no_se_asigna(
    client, db, crear_usuario, crear_equipamiento, crear_orden, estado
):  # AC-L20, AC-L26 (prestado, aunque la devolución esté vencida)
    camara = await crear_equipamiento(estados=(estado,))
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara))

    assert r.status_code == 422
    assert _codigo(r) == "UNIDAD_NO_ASIGNABLE"
    assert r.json()["detalle_id"] == orden.detalles[0].id
    assert r.json()["unidad_fisica_id"] == _ids(camara)[0]
    await _sigue_pendiente(db, orden.id)


async def test_una_unidad_de_otra_sede_no_se_asigna(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L21, P5
    camara = await crear_equipamiento()
    de_rio_grande = await crear_equipamiento(sede=RG)
    # Se pasa la unidad de Río Grande al mismo modelo para que solo difiera la sede.
    unidad_rg = de_rio_grande.unidades[0]
    unidad_rg.equipamiento_id = camara.id
    await db.commit()
    orden = await crear_orden(camara)
    admin = await crear_usuario(S)

    r = await _aprobar(client, admin, orden, [unidad_rg.id])

    assert r.status_code == 422
    assert _codigo(r) == "UNIDAD_NO_ASIGNABLE"
    await _sigue_pendiente(db, orden.id)


async def test_una_unidad_de_otro_modelo_no_se_asigna(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L21
    camara = await crear_equipamiento()
    tripode = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(tripode))

    assert r.status_code == 422
    assert _codigo(r) == "UNIDAD_NO_ASIGNABLE"
    await _sigue_pendiente(db, orden.id)


async def test_una_unidad_inexistente_no_se_asigna(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, [9999])

    assert r.status_code == 422
    assert _codigo(r) == "UNIDAD_NO_ASIGNABLE"
    await _sigue_pendiente(db, orden.id)


async def test_la_unidad_de_un_item_dado_de_baja_no_se_asigna(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # EC-L08
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    camara.activo = False
    await db.commit()
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara))

    assert r.status_code == 422
    assert _codigo(r) == "UNIDAD_NO_ASIGNABLE"
    await _sigue_pendiente(db, orden.id)


async def test_faltan_asignaciones(client, db, crear_usuario, crear_equipamiento, crear_orden):
    # AC-L22
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    orden = await crear_orden(camara, camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara)[:1])

    assert r.status_code == 422
    assert _codigo(r) == "ASIGNACIONES_INVALIDAS"
    await _sigue_pendiente(db, orden.id)


async def test_una_unidad_repetida_en_dos_lineas(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L22
    camara = await crear_equipamiento()
    orden = await crear_orden(camara, camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara) * 2)

    assert r.status_code == 422
    assert _codigo(r) == "ASIGNACIONES_INVALIDAS"
    await _sigue_pendiente(db, orden.id)


async def test_una_asignacion_para_una_linea_ajena(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L22
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    orden, ajena = await crear_orden(camara), await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    primera, segunda = _ids(camara)
    cuerpo = {
        "estado": "aprobada",
        "asignaciones": [
            {"detalle_id": orden.detalles[0].id, "unidad_fisica_id": primera},
            {"detalle_id": ajena.detalles[0].id, "unidad_fisica_id": segunda},
        ],
    }

    r = await client.patch(f"{BASE}/ordenes/{orden.id}/estado", json=cuerpo, headers=auth(admin))

    assert r.status_code == 422
    assert _codigo(r) == "ASIGNACIONES_INVALIDAS"
    await _sigue_pendiente(db, orden.id)
    await _sigue_pendiente(db, ajena.id)


async def test_no_se_aprueba_una_orden_con_el_retiro_vencido(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L30, RN-L27, EC-L05
    camara = await crear_equipamiento()
    orden = await crear_orden(camara, retiro=ahora_lab() - timedelta(hours=1))
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara))

    assert r.status_code == 422
    assert _codigo(r) == "RETIRO_VENCIDO"
    await _sigue_pendiente(db, orden.id)


def _ajuste(retiro: datetime, devolucion: datetime) -> dict:
    return {"nuevo_retiro": retiro.isoformat(), "nueva_devolucion": devolucion.isoformat()}


def _a_las(dia: datetime, hora: int) -> datetime:
    return dia.replace(hour=hora, minute=0, second=0, microsecond=0)


async def test_el_ajuste_horario_cambia_todas_las_lineas(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L25, RN-L18, PRE-18
    camara = await crear_equipamiento(estados=(U.DISPONIBLE,) * 2)
    orden = await crear_orden(camara, camara)
    admin = await crear_usuario(A, USH)
    retiro = _a_las(RETIRO + timedelta(days=1), 11)
    devolucion = _a_las(retiro + timedelta(days=1), 14)

    r = await _aprobar(client, admin, orden, _ids(camara), **_ajuste(retiro, devolucion))

    assert r.status_code == 200, r.json()
    en_base = await _en_base(db, orden.id)
    assert en_base.estado is EstadoOrdenEnum.APROBADA
    for linea in en_base.detalles:
        assert linea.retiro_pactado == retiro
        assert linea.devolucion_pactada == devolucion
        assert linea.fin_ocupacion == devolucion


@pytest.mark.parametrize(("hora_retiro", "hora_devolucion"), [(8, 14), (10, 17)])
async def test_el_ajuste_fuera_de_la_franja_responde_422(
    client, db, crear_usuario, crear_equipamiento, crear_orden, hora_retiro, hora_devolucion
):  # AC-L25, RN-L04: la franja sembrada es de 09:00 a 16:00
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    retiro = _a_las(RETIRO, hora_retiro)
    devolucion = _a_las(RETIRO + timedelta(days=1), hora_devolucion)

    r = await _aprobar(client, admin, orden, _ids(camara), **_ajuste(retiro, devolucion))

    assert r.status_code == 422
    assert _codigo(r) == "FRANJA_FUERA_DE_HORARIO"
    await _sigue_pendiente(db, orden.id)


async def test_el_ajuste_que_supera_el_plazo_responde_422(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L25, RN-L06: el ítem admite 4 días
    camara = await crear_equipamiento(max_dias_prestamo=4)
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    devolucion = RETIRO + timedelta(days=6)

    r = await _aprobar(client, admin, orden, _ids(camara), **_ajuste(RETIRO, devolucion))

    assert r.status_code == 422
    assert _codigo(r) == "LIMITE_DIAS_EXCEDIDO"
    await _sigue_pendiente(db, orden.id)


async def test_el_ajuste_con_un_retiro_pasado_responde_422(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # RN-L18: el retiro nuevo tiene que ser futuro
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    retiro = ahora_lab() - timedelta(hours=1)

    r = await _aprobar(
        client, admin, orden, _ids(camara), **_ajuste(retiro, retiro + timedelta(hours=2))
    )

    assert r.status_code == 422
    assert _codigo(r) == "RETIRO_VENCIDO"
    assert r.json()["campo"] == "nuevo_retiro"
    await _sigue_pendiente(db, orden.id)


async def test_una_orden_con_el_retiro_vencido_se_aprueba_ajustando_el_horario(
    client, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L30, EC-L05
    camara = await crear_equipamiento()
    orden = await crear_orden(camara, retiro=ahora_lab() - timedelta(hours=1))
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara), **_ajuste(RETIRO, DEVOLUCION))

    assert r.status_code == 200, r.json()


async def test_el_ajuste_no_exige_la_anticipacion_minima(
    client, set_parametro, crear_usuario, crear_equipamiento, crear_orden
):  # RN-L18: el administrador acuerda el horario con el solicitante
    await set_parametro("solicitud.anticipacion_min_horas", 168)
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    retiro = _a_las(ahora_lab() + timedelta(days=1), 10)  # menos de 168 horas

    r = await _aprobar(client, admin, orden, _ids(camara), **_ajuste(retiro, _a_las(retiro, 15)))

    assert r.status_code == 200, r.json()


async def test_el_ajuste_se_controla_contra_las_reservas_del_periodo_nuevo(
    client, db, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # AC-L23, RN-L12: el EXCLUDE mira el período ajustado, no el pedido
    camara = await crear_equipamiento()
    await crear_linea(
        camara, camara.unidades[0], EstadoDetalleEnum.RESERVADO, retiro=EN_OTRAS_FECHAS
    )
    orden = await crear_orden(camara)  # el período pedido está libre
    admin = await crear_usuario(A, USH)
    ajuste = _ajuste(EN_OTRAS_FECHAS, EN_OTRAS_FECHAS + timedelta(days=1, hours=5))

    r = await _aprobar(client, admin, orden, _ids(camara), **ajuste)

    assert r.status_code == 409
    assert _codigo(r) == "UNIDAD_NO_DISPONIBLE"
    await _sigue_pendiente(db, orden.id)
    assert (await _en_base(db, orden.id)).detalles[0].retiro_pactado == RETIRO


async def test_el_ajuste_puede_esquivar_una_reserva_que_se_solapaba(
    client, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # RN-L18: mover el horario a fechas libres permite aprobar
    camara = await crear_equipamiento()
    await crear_linea(camara, camara.unidades[0], EstadoDetalleEnum.RESERVADO, retiro=SOLAPADO)
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)
    ajuste = _ajuste(EN_OTRAS_FECHAS, EN_OTRAS_FECHAS + timedelta(days=1, hours=5))

    r = await _aprobar(client, admin, orden, _ids(camara), **ajuste)

    assert r.status_code == 200, r.json()


async def test_una_unidad_con_una_reserva_que_se_solapa_responde_409(
    client, db, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # AC-L23, AC-L47, RN-L12: lo rechaza el EXCLUDE de la base
    camara = await crear_equipamiento()
    tripode = await crear_equipamiento()
    await crear_linea(camara, camara.unidades[0], EstadoDetalleEnum.RESERVADO, retiro=SOLAPADO)
    orden = await crear_orden(tripode, camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, [*_ids(tripode), *_ids(camara)])

    assert r.status_code == 409
    assert _codigo(r) == "UNIDAD_NO_DISPONIBLE"
    await _sigue_pendiente(db, orden.id)  # tampoco quedó reservado el trípode (RN-L13)


async def test_una_reserva_en_otras_fechas_no_impide_aprobar(
    client, crear_usuario, crear_equipamiento, crear_linea, crear_orden
):  # AC-L47
    camara = await crear_equipamiento()
    await crear_linea(
        camara, camara.unidades[0], EstadoDetalleEnum.RESERVADO, retiro=EN_OTRAS_FECHAS
    )
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    r = await _aprobar(client, admin, orden, _ids(camara))

    assert r.status_code == 200, r.json()


async def test_no_se_aprueba_dos_veces(client, crear_usuario, crear_equipamiento, crear_orden):
    # AC-L28
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin = await crear_usuario(A, USH)

    await _aprobar(client, admin, orden, _ids(camara))
    r = await _aprobar(client, admin, orden, _ids(camara))

    assert r.status_code == 409
    assert _codigo(r) == "TRANSICION_INVALIDA"


async def test_un_admin_de_otra_sede_no_aprueba(
    client, db, crear_usuario, crear_equipamiento, crear_orden
):  # AC-L29
    camara = await crear_equipamiento()
    orden = await crear_orden(camara)
    admin_rg = await crear_usuario(A, RG)

    r = await _aprobar(client, admin_rg, orden, _ids(camara))

    assert r.status_code == 404
    await _sigue_pendiente(db, orden.id)


class _OrigConSqlstate(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "es_solapamiento"),
    [("23P01", True), ("23505", False), ("23503", False), ("23514", False)],
)
def test_solo_la_violacion_de_exclusion_se_traduce_a_409(sqlstate, es_solapamiento):
    # AC-L53: unicidad, FK y CHECK no se enmascaran como conflicto
    exc = IntegrityError("UPDATE ...", {}, _OrigConSqlstate(sqlstate))
    assert service._es_solapamiento(exc) is es_solapamiento
