"""Contratos Pydantic de `loans` (SPEC-05 §6.2). No usan base de datos.

Solo se prueba la forma del payload; las reglas que dependen de `config`, de
`inventory` o del rol (franja, plazos, motivo, permisos) se prueban en los tests
de integración de cada fase.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.modules.loans.schemas import OrdenPedidoCreate, OrdenPedidoEstadoUpdate

TZ = timezone(timedelta(hours=-3))
RETIRO = datetime(2026, 12, 1, 10, 0, tzinfo=TZ)
DEVOLUCION = datetime(2026, 12, 3, 15, 0, tzinfo=TZ)
ASIGNACION = {"detalle_id": 1, "unidad_fisica_id": 5}


def _orden(**cambios):
    datos = {
        "retiro": RETIRO,
        "devolucion": DEVOLUCION,
        "items": [{"equipamiento_id": 1}],
        "acepta_normativa": True,
    }
    datos.update(cambios)
    return OrdenPedidoCreate(**datos)


# ── OrdenPedidoCreate ────────────────────────────────────────────────────────


def test_orden_valida_sin_asignatura():  # AC-L05 (el docente no la necesita)
    assert _orden().asignatura_id is None


def test_orden_admite_el_mismo_modelo_repetido():  # AC-L03
    orden = _orden(items=[{"equipamiento_id": 1}, {"equipamiento_id": 1}])
    assert len(orden.items) == 2


@pytest.mark.parametrize("campo", ["solicitante_id", "sede", "estado"])
def test_orden_rechaza_campos_que_decide_el_sistema(campo):  # AC-L04
    with pytest.raises(ValidationError):
        _orden(**{campo: "x"})


def test_orden_exige_aceptar_la_normativa():  # AC-L06
    with pytest.raises(ValidationError):
        _orden(acepta_normativa=False)


@pytest.mark.parametrize("devolucion", [RETIRO, RETIRO - timedelta(hours=1)])
def test_orden_exige_devolucion_posterior_al_retiro(devolucion):  # AC-L09
    with pytest.raises(ValidationError):
        _orden(devolucion=devolucion)


def test_orden_exige_fechas_con_zona_horaria():
    with pytest.raises(ValidationError):
        _orden(retiro=datetime(2026, 12, 1, 10, 0))


@pytest.mark.parametrize("items", [[], [{"equipamiento_id": 1}] * 21])
def test_orden_limita_la_cantidad_de_lineas(items):
    with pytest.raises(ValidationError):
        _orden(items=items)


# ── OrdenPedidoEstadoUpdate ──────────────────────────────────────────────────


def test_estado_aprobar_con_asignaciones():  # AC-L19
    assert OrdenPedidoEstadoUpdate(estado="aprobada", asignaciones=[ASIGNACION])


def test_estado_aprobar_con_ajuste_horario():  # AC-L25
    cambio = OrdenPedidoEstadoUpdate(
        estado="aprobada",
        asignaciones=[ASIGNACION],
        nuevo_retiro=RETIRO,
        nueva_devolucion=DEVOLUCION,
    )
    assert cambio.nuevo_retiro == RETIRO


def test_estado_aprobar_exige_asignaciones():  # AC-L22
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado="aprobada")


def test_estado_no_admite_dos_asignaciones_para_la_misma_linea():  # AC-L22
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(
            estado="aprobada",
            asignaciones=[ASIGNACION, {"detalle_id": 1, "unidad_fisica_id": 6}],
        )


def test_estado_el_ajuste_horario_va_completo():  # AC-L25
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado="aprobada", asignaciones=[ASIGNACION], nuevo_retiro=RETIRO)


def test_estado_el_ajuste_horario_respeta_el_orden():  # AC-L25
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(
            estado="aprobada",
            asignaciones=[ASIGNACION],
            nuevo_retiro=DEVOLUCION,
            nueva_devolucion=RETIRO,
        )


@pytest.mark.parametrize("estado", ["rechazada", "cancelada"])
def test_estado_solo_aprobar_admite_asignaciones_y_ajuste(estado):
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado=estado, asignaciones=[ASIGNACION])
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado=estado, nuevo_retiro=RETIRO, nueva_devolucion=DEVOLUCION)


@pytest.mark.parametrize("estado", ["rechazada", "cancelada"])
def test_estado_el_motivo_lo_exige_el_servicio(estado):  # AC-L27
    """El esquema no lo exige: lo valida el servicio con MOTIVO_REQUERIDO."""
    assert OrdenPedidoEstadoUpdate(estado=estado).motivo is None


@pytest.mark.parametrize("estado", ["pendiente", "inexistente"])
def test_estado_rechaza_estados_no_permitidos(estado):
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado=estado)


def test_estado_rechaza_campos_desconocidos():
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado="cancelada", sede="Ushuaia")