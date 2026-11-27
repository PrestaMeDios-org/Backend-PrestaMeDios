"""Contratos Pydantic de `loans` (SPEC-05 §6.2). No usan base de datos.

Solo se prueba la forma del payload; las reglas que dependen de `config`, de
`inventory` o del rol (franja, plazos, motivo, permisos) se prueban en los tests
de integración de cada fase.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.loans.enums import EstadoDetalleEnum as D
from app.modules.loans.schemas import (
    OrdenPedidoCreate,
    OrdenPedidoEstadoUpdate,
    OrdenPedidoResponse,
)

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


def test_orden_de_renovacion_admite_una_sola_linea():  # RN-L24
    with pytest.raises(ValidationError):
        _orden(renueva_detalle_id=42, items=[{"equipamiento_id": 1}] * 2)


# ── OrdenPedidoEstadoUpdate ──────────────────────────────────────────────────


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


def test_estado_rechaza_estados_no_permitidos():  # una orden no vuelve a `pendiente`
    with pytest.raises(ValidationError):
        OrdenPedidoEstadoUpdate(estado="pendiente")


# ── OrdenPedidoResponse ──────────────────────────────────────────────────────


def _linea(estado: D, n: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=n,
        equipamiento_id=1,
        unidad_fisica_id=None if estado is D.PENDIENTE else 5,
        estado=estado,
        retiro_pactado=RETIRO,
        devolucion_pactada=DEVOLUCION,
        fin_ocupacion=DEVOLUCION,
    )


def _respuesta(*estados: D) -> OrdenPedidoResponse:
    """Valida un objeto con atributos, como hace FastAPI con el modelo ORM."""
    orden = SimpleNamespace(
        id=1,
        solicitante_id=7,
        sede="Ushuaia",
        asignatura_id=None,
        estado="aprobada",
        fecha_solicitud=RETIRO,
        observacion_docente=None,
        motivo_resolucion=None,
        es_renovado=False,
        resuelto_en=None,
        detalles=[_linea(e, n) for n, e in enumerate(estados, start=1)],
    )
    return OrdenPedidoResponse.model_validate(orden)


@pytest.mark.parametrize("estado", [D.PENDIENTE, D.RESERVADO, D.ENTREGADO])
def test_situacion_en_curso_si_alguna_linea_sigue_activa(estado):  # AC-L61, RN-L31
    assert _respuesta(D.DEVUELTO, estado).situacion == "en_curso"


@pytest.mark.parametrize(
    "estados",
    [
        (D.DEVUELTO,),
        (D.DEVUELTO, D.CANCELADO),
        (D.RECHAZADO, D.RECHAZADO),
        (D.NO_RETIRADO, D.CANCELADO),
    ],
)
def test_situacion_finalizada_si_ninguna_linea_sigue_activa(estados):  # AC-L61, RN-L31
    assert _respuesta(*estados).situacion == "finalizada"
