"""`POST /ordenes`: crear una orden (SPEC-05 RN-L01…L10; AC-L02…L12, AC-L56, AC-L57).

Todo corre contra la base real: los datos de los ítems salen de
`inventory.datos_equipamiento_por_ids` (C8) y la disponibilidad de
`inventory.unidades_asignables`.

Primera versión: sin aval (la alta gama responde `422 AVAL_REQUERIDO`) y sin renovación
(responde 501). Las fechas son relativas a hoy para cumplir la anticipación mínima.
"""

from datetime import datetime, time
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB
from app.modules.inventory.enums import EstadoUnidadEnum as E
from app.modules.loans.enums import EstadoDetalleEnum as D
from app.modules.loans import service
from app.modules.loans.models import DetallePrestamo, OrdenPedido
from app.modules.loans.schemas import OrdenPedidoCreate
from tests.conftest import auth, dia

pytestmark = pytest.mark.integracion

URL = "/api/v1/loans/ordenes"
ESTUDIANTE, DOCENTE = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
AVAL = "3f2b6c1e-8a4d-4f7e-9b1a-2c5d7e9f0a1b"


def _a(dias: int, hora: int, minuto: int = 0) -> datetime:
    """Instante en la zona del laboratorio, ``dias`` días después de hoy."""
    return datetime.combine(dia(dias), time(hora, minuto), tzinfo=ZONA_HORARIA_LAB)


# Retiro dentro de 3 días y devolución 2 días después: 3 días corridos (plazo general 4).
RETIRO, DEVOLUCION = _a(3, 10), _a(5, 15)


def _pedido(*equipamientos, retiro=RETIRO, devolucion=DEVOLUCION, asignatura_id=7, **extra):
    return {
        "asignatura_id": asignatura_id,
        "retiro": retiro.isoformat(),
        "devolucion": devolucion.isoformat(),
        "items": [{"equipamiento_id": eq.id} for eq in equipamientos],
        "acepta_normativa": True,
        **extra,
    }


@pytest.fixture
def equipo(crear_equipamiento):
    """Alias corto de la fábrica de equipamiento."""
    return crear_equipamiento


async def _cantidad_de_ordenes(db) -> int:
    return await db.scalar(select(func.count()).select_from(OrdenPedido))


# ── Camino feliz ─────────────────────────────────────────────────────────────


async def test_crea_la_orden_pendiente_con_sus_lineas(client, db, crear_usuario, equipo):
    # AC-L02, AC-L03, RN-L01, RN-L03
    ana = await crear_usuario(ESTUDIANTE, SedeEnum.RIO_GRANDE)
    camara = await equipo(sede=SedeEnum.RIO_GRANDE, estados=(E.DISPONIBLE,) * 2)

    r = await client.post(URL, json=_pedido(camara, camara), headers=auth(ana))

    assert r.status_code == 201, r.json()
    orden = r.json()
    assert orden["estado"] == "pendiente"
    assert orden["solicitante_id"] == ana._cache_auth["id"]
    assert orden["sede"] == SedeEnum.RIO_GRANDE.value
    assert orden["asignatura_id"] == 7
    assert orden["es_renovado"] is False
    assert orden["situacion"] == "en_curso"  # AC-L61
    assert orden["resuelto_en"] is None
    assert len(orden["detalles"]) == 2
    for linea in orden["detalles"]:
        assert linea["equipamiento_id"] == camara.id
        assert linea["estado"] == "pendiente"
        assert linea["unidad_fisica_id"] is None
        assert datetime.fromisoformat(linea["retiro_pactado"]) == RETIRO
        assert datetime.fromisoformat(linea["devolucion_pactada"]) == DEVOLUCION
        assert datetime.fromisoformat(linea["fin_ocupacion"]) == DEVOLUCION

    lineas = (await db.scalars(select(DetallePrestamo))).all()
    assert [linea.orden_id for linea in lineas] == [orden["id"]] * 2


async def test_un_docente_no_necesita_asignatura(client, crear_usuario, equipo):  # AC-L05
    docente = await crear_usuario(DOCENTE)
    camara = await equipo()
    r = await client.post(URL, json=_pedido(camara, asignatura_id=None), headers=auth(docente))
    assert r.status_code == 201, r.json()
    assert r.json()["asignatura_id"] is None


async def test_dos_pedidos_pendientes_del_mismo_equipo_conviven(client, crear_usuario, equipo):
    # RN-L03: las líneas pendientes no ocupan; la garantía llega al aprobar
    camara = await equipo()  # una sola unidad
    for _ in range(2):
        usuario = await crear_usuario(ESTUDIANTE)
        r = await client.post(URL, json=_pedido(camara), headers=auth(usuario))
        assert r.status_code == 201, r.json()


# ── Solicitante ──────────────────────────────────────────────────────────────


async def test_un_estudiante_sin_asignatura_se_rechaza(client, db, crear_usuario, equipo):
    # AC-L05, RN-L07
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo()
    r = await client.post(URL, json=_pedido(camara, asignatura_id=None), headers=auth(ana))
    assert r.status_code == 422
    assert r.json()["code"] == "ASIGNATURA_REQUERIDA"
    assert await _cantidad_de_ordenes(db) == 0


async def test_la_renovacion_todavia_no_esta_disponible(client, crear_usuario, equipo):
    notebook = await equipo(es_notebook=True)
    ana = await crear_usuario(ESTUDIANTE)
    r = await client.post(URL, json=_pedido(notebook, renueva_detalle_id=1), headers=auth(ana))
    assert r.status_code == 501
    assert r.json()["code"] == "NO_IMPLEMENTADO"


async def test_un_solicitante_sin_sede_recibe_403_y_no_un_500():
    # O2: antes era un `assert`, que con `python -O` desaparece. La base ya impide este
    # caso (CHECK sede_segun_rol), así que se prueba el servicio con un actor armado a mano.
    actor = SimpleNamespace(id=1, rol=ESTUDIANTE, sede=None)
    pedido = OrdenPedidoCreate.model_validate(_pedido(SimpleNamespace(id=1)))
    with pytest.raises(AppError) as exc:
        await service.crear_orden(None, actor, pedido)  # falla antes de tocar la base
    assert (exc.value.status_code, exc.value.code) == (403, "ROL_NO_AUTORIZADO")


# ── Horario ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("retiro", "devolucion", "campo"),
    [(_a(3, 8, 59), DEVOLUCION, "retiro"), (RETIRO, _a(5, 16, 1), "devolucion")],
)
async def test_fuera_de_la_franja_se_rechaza(
    client, crear_usuario, equipo, retiro, devolucion, campo
):  # AC-L07, RN-L04
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo()
    pedido = _pedido(camara, retiro=retiro, devolucion=devolucion)
    r = await client.post(URL, json=pedido, headers=auth(ana))
    assert r.status_code == 422
    assert r.json()["code"] == "FRANJA_FUERA_DE_HORARIO"
    assert r.json()["campo"] == campo


async def test_sin_anticipacion_minima_se_rechaza(client, crear_usuario, equipo, set_parametro):
    # AC-L08, RN-L05, RN-L28: el retiro (en 3 días, < 72 h) queda antes de ahora + 100 h
    await set_parametro("solicitud.anticipacion_min_horas", 100)
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo()
    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))
    assert r.status_code == 422
    assert r.json()["code"] == "ANTICIPACION_INSUFICIENTE"
    assert r.json()["anticipacion_min_horas"] == 100


# ── Ítems ────────────────────────────────────────────────────────────────────


async def test_un_equipo_inexistente_responde_404(client, crear_usuario, equipo):
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo()
    pedido = _pedido(camara)
    pedido["items"].append({"equipamiento_id": 999_999})
    r = await client.post(URL, json=pedido, headers=auth(ana))
    assert r.status_code == 404
    assert r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"
    assert r.json()["equipamiento_id"] == 999_999


async def test_un_equipo_inactivo_responde_404(client, crear_usuario, equipo):
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo(activo=False)
    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))
    assert r.status_code == 404
    assert r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"


@pytest.mark.parametrize("extra", [{}, {"pdf_aval_id": AVAL}])
async def test_la_alta_gama_exige_aval(client, db, crear_usuario, equipo, extra):
    # RN-L09. Sin `files` en develop, se rechaza aunque traiga el aval.
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo(alta_gama=True)
    r = await client.post(URL, json=_pedido(camara, **extra), headers=auth(ana))
    assert r.status_code == 422
    assert r.json()["code"] == "AVAL_REQUERIDO"
    assert r.json()["equipamiento_id"] == camara.id
    assert await _cantidad_de_ordenes(db) == 0


# ── Plazo por línea (RN-L06) ─────────────────────────────────────────────────


async def test_el_plazo_general_se_respeta(client, crear_usuario, equipo):  # AC-L10
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo(max_dias_prestamo=15)  # el parámetro general (4) es menor
    r = await client.post(URL, json=_pedido(camara, devolucion=_a(7, 15)), headers=auth(ana))
    assert r.status_code == 422
    assert r.json()["code"] == "LIMITE_DIAS_EXCEDIDO"
    assert r.json()["max_dias"] == 4


async def test_el_maximo_del_item_puede_ser_menor(client, crear_usuario, equipo):  # AC-L11
    ana = await crear_usuario(ESTUDIANTE)
    camara = await equipo(max_dias_prestamo=2)
    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))  # 3 días
    assert r.status_code == 422
    assert r.json()["max_dias"] == 2


async def test_una_notebook_usa_su_propio_plazo(client, crear_usuario, equipo):  # AC-L11
    ana = await crear_usuario(ESTUDIANTE)
    notebook = await equipo(es_notebook=True, max_dias_prestamo=15)
    r = await client.post(URL, json=_pedido(notebook, devolucion=_a(12, 15)), headers=auth(ana))
    assert r.status_code == 201, r.json()  # 10 días: más que el general, menos que 15


async def test_cada_linea_cumple_su_limite(client, crear_usuario, equipo):  # D-L03
    ana = await crear_usuario(ESTUDIANTE)
    notebook = await equipo(es_notebook=True, max_dias_prestamo=15)
    camara = await equipo()
    pedido = _pedido(notebook, camara, devolucion=_a(9, 15))
    r = await client.post(URL, json=pedido, headers=auth(ana))
    assert r.status_code == 422
    assert r.json()["equipamiento_id"] == camara.id


# ── Disponibilidad (RN-L10) ──────────────────────────────────────────────────


async def test_sin_unidades_libres_en_el_periodo_responde_409(
    client, db, crear_usuario, equipo, crear_linea
):  # AC-L56
    camara = await equipo()
    await crear_linea(camara, camara.unidades[0], D.RESERVADO, retiro=_a(4, 10))
    ana = await crear_usuario(ESTUDIANTE)

    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))

    assert r.status_code == 409
    assert r.json()["code"] == "EQUIPAMIENTO_NO_DISPONIBLE"
    assert r.json()["libres"] == 0
    assert await _cantidad_de_ordenes(db) == 1  # solo la de la reserva previa


async def test_una_reserva_en_otras_fechas_no_impide_pedir(
    client, crear_usuario, equipo, crear_linea
):  # AC-L56, §15.3 (D-L17 descartada)
    camara = await equipo()
    await crear_linea(camara, camara.unidades[0], D.RESERVADO, retiro=_a(20, 10))
    ana = await crear_usuario(ESTUDIANTE)
    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))
    assert r.status_code == 201, r.json()


async def test_mas_lineas_que_unidades_libres_responde_409(client, crear_usuario, equipo):
    # AC-L57
    camara = await equipo(estados=(E.DISPONIBLE,) * 2)
    ana = await crear_usuario(ESTUDIANTE)
    r = await client.post(URL, json=_pedido(camara, camara, camara), headers=auth(ana))
    assert r.status_code == 409
    assert (r.json()["solicitadas"], r.json()["libres"]) == (3, 2)


async def test_solo_cuentan_las_unidades_de_la_sede_del_solicitante(
    client, crear_usuario, equipo
):  # P5, RN-L01
    camara = await equipo(sede=SedeEnum.RIO_GRANDE)
    ana = await crear_usuario(ESTUDIANTE, SedeEnum.USHUAIA)
    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))
    assert r.status_code == 409
    assert r.json()["code"] == "EQUIPAMIENTO_NO_DISPONIBLE"
