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
from app.modules.users.service import DatosPublicosUsuario

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


def test_orden_sin_aval_ni_renovacion_por_defecto():
    orden = _orden()
    assert orden.pdf_aval_id is None
    assert orden.renueva_detalle_id is None


def test_orden_acepta_un_aval_uuid():  # PRE-05, SPEC-03 (archivos.id es UUID)
    orden = _orden(pdf_aval_id="3f2b6c1e-8a4d-4f7e-9b1a-2c5d7e9f0a1b")
    assert str(orden.pdf_aval_id) == "3f2b6c1e-8a4d-4f7e-9b1a-2c5d7e9f0a1b"


@pytest.mark.parametrize("aval", ["no-es-un-uuid", 12])
def test_orden_rechaza_un_aval_que_no_es_uuid(aval):
    with pytest.raises(ValidationError):
        _orden(pdf_aval_id=aval)


def test_orden_de_renovacion_con_una_linea():  # RN-L24
    assert _orden(renueva_detalle_id=42).renueva_detalle_id == 42


def test_orden_de_renovacion_admite_una_sola_linea():  # RN-L24
    with pytest.raises(ValidationError):
        _orden(renueva_detalle_id=42, items=[{"equipamiento_id": 1}] * 2)


@pytest.mark.parametrize("detalle", [0, -1])
def test_orden_de_renovacion_exige_un_id_positivo(detalle):
    with pytest.raises(ValidationError):
        _orden(renueva_detalle_id=detalle)


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


def _respuesta(*estados: D, **extra) -> OrdenPedidoResponse:
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
        **extra,
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


def test_la_situacion_viaja_en_el_json():
    assert _respuesta(D.PENDIENTE).model_dump(mode="json")["situacion"] == "en_curso"


def test_sin_solicitante_ni_resolucion_por_defecto():
    respuesta = _respuesta(D.PENDIENTE)  # el modelo ORM no tiene `solicitante`
    assert respuesta.solicitante is None
    assert respuesta.resuelto_en is None


def test_el_solicitante_sale_de_users_y_solo_tiene_id_nombre_y_apellido():  # P6
    datos = DatosPublicosUsuario(id=7, nombre="Ana", apellido="Pérez")
    respuesta = _respuesta(D.PENDIENTE, solicitante=datos)
    assert respuesta.model_dump(mode="json")["solicitante"] == {
        "id": 7,
        "nombre": "Ana",
        "apellido": "Pérez",
    }
