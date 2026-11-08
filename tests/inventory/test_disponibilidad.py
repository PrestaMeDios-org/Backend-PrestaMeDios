"""SPEC-04 §5.4 — Disponibilidad por fechas (PRE-01, RN-I14, RN-I15) - INV-26, INV-30."""

from datetime import datetime, time, timedelta

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB, ahora_lab
from app.modules.inventory.disponibilidad import (
    MAX_DIAS_DISPONIBILIDAD,
    contar_libres_por_dia,
    validar_rango,
)
from app.modules.inventory.enums import EstadoUnidadEnum as E
from app.modules.loans.enums import EstadoDetalleEnum as D
from app.modules.loans.service import PeriodoOcupado
from tests.conftest import auth, dia

pytestmark = pytest.mark.integracion

B = "/api/v1/inventory"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _url(equipamiento_id: int) -> str:
    return f"{B}/equipamiento/{equipamiento_id}/disponibilidad"


def _rango(desde: int, hasta: int, **extra) -> dict[str, str]:
    return {"desde": dia(desde).isoformat(), "hasta": dia(hasta).isoformat(), **extra}


def _retiro(offset: int, hora: int = 10) -> datetime:
    return datetime.combine(dia(offset), time(hora), tzinfo=ZONA_HORARIA_LAB)


def _libres(cuerpo: dict) -> list[int]:
    return [d["unidades_libres"] for d in cuerpo["dias"]]


# ── validar_rango (unidad) ───────────────────────────────────────────────────

HOY = ahora_lab().date()


def _mensaje_invalido(desde, hasta) -> str:
    with pytest.raises(AppError) as exc:
        validar_rango(desde, hasta, HOY)
    assert exc.value.status_code == 422 and exc.value.code == "RANGO_FECHAS_INVALIDO"
    return exc.value.detail


def test_rango_valido_incluye_hoy_y_el_tope():  # INV-30
    validar_rango(HOY, HOY, HOY)
    validar_rango(HOY, HOY + timedelta(days=MAX_DIAS_DISPONIBILIDAD - 1), HOY)


def test_rango_invertido():  # INV-30
    assert "anterior" in _mensaje_invalido(HOY + timedelta(days=3), HOY + timedelta(days=2))


def test_rango_que_empieza_antes_de_hoy():  # INV-30
    assert "antes de hoy" in _mensaje_invalido(HOY - timedelta(days=1), HOY + timedelta(days=3))


def test_rango_de_mas_de_62_dias():  # INV-30
    detalle = _mensaje_invalido(HOY, HOY + timedelta(days=MAX_DIAS_DISPONIBILIDAD))
    assert str(MAX_DIAS_DISPONIBILIDAD) in detalle


# ── contar_libres_por_dia (unidad) ───────────────────────────────────────────


def test_una_linea_que_termina_a_mediodia_ocupa_ese_dia():  # INV-26 (d)
    periodo = PeriodoOcupado(desde=_retiro(1, 9), hasta=_retiro(2, 12))
    dias = contar_libres_por_dia(dia(0), dia(3), {1: [periodo], 2: []})
    assert dias == [(dia(0), 2), (dia(1), 1), (dia(2), 1), (dia(3), 2)]


def test_el_periodo_que_termina_a_medianoche_no_ocupa_el_dia_siguiente():  # INV-26 (d)
    periodo = PeriodoOcupado(desde=_retiro(1, 9), hasta=_retiro(2, 0))
    dias = contar_libres_por_dia(dia(1), dia(2), {1: [periodo]})
    assert dias == [(dia(1), 0), (dia(2), 1)]


# ── Endpoint ─────────────────────────────────────────────────────────────────


async def test_exige_sesion(client, crear_equipo):  # INV-30
    eq = await crear_equipo(unidades=((USH,),))
    r = await client.get(_url(eq.id), params=_rango(0, 1))
    assert r.status_code == 401


async def test_dias_libres_y_ocupados(client, crear_equipo, crear_linea, crear_usuario):  # INV-26 (a, b)
    eq = await crear_equipo(unidades=((USH,), (USH,), (USH,)))
    u1, u2, _ = sorted(eq.unidades, key=lambda u: u.codigo_inventario)
    # u1 ocupa los días +1, +2 y +3 (hasta las 15:00); u2 los días +2, +3 y +4.
    await crear_linea(eq, u1, D.RESERVADO, retiro=_retiro(1))
    await crear_linea(eq, u2, D.ENTREGADO, retiro=_retiro(2))
    # Estados que no ocupan.
    for estado in (D.PENDIENTE, D.DEVUELTO, D.CANCELADO, D.RECHAZADO, D.NO_RETIRADO):
        await crear_linea(eq, u2, estado, retiro=_retiro(0))
    alumno = await crear_usuario(R.ESTUDIANTE, USH)

    r = await client.get(_url(eq.id), params=_rango(0, 5), headers=auth(alumno))

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["equipamiento_id"] == eq.id and cuerpo["sede"] == "Ushuaia"
    assert cuerpo["unidades_asignables"] == 3
    assert [d["fecha"] for d in cuerpo["dias"]] == [dia(i).isoformat() for i in range(6)]
    assert _libres(cuerpo) == [3, 2, 1, 1, 2, 3]
    assert [d["disponible"] for d in cuerpo["dias"]] == [True] * 6


async def test_una_linea_previa_al_rango_ocupa_sus_dias(  # INV-26 (a)
    client, crear_equipo, crear_linea, crear_usuario
):
    eq = await crear_equipo(unidades=((USH,),))
    await crear_linea(eq, eq.unidades[0], D.ENTREGADO, retiro=_retiro(0))
    alumno = await crear_usuario(R.ESTUDIANTE, USH)

    cuerpo = (await client.get(_url(eq.id), params=_rango(1, 4), headers=auth(alumno))).json()

    assert _libres(cuerpo) == [0, 0, 1, 1]
    assert [d["disponible"] for d in cuerpo["dias"]] == [False, False, True, True]


async def test_unidades_que_no_cuentan(client, crear_equipo, crear_usuario):  # INV-26 (c, e)
    eq = await crear_equipo(
        unidades=((USH, E.DISPONIBLE), (USH, E.PRESTADO), (USH, E.MANTENIMIENTO), (USH, E.BAJA), (RG,))
    )
    alumno = await crear_usuario(R.ESTUDIANTE, USH)

    cuerpo = (await client.get(_url(eq.id), params=_rango(0, 1), headers=auth(alumno))).json()

    assert cuerpo["unidades_asignables"] == 1
    assert _libres(cuerpo) == [1, 1]


async def test_la_respuesta_no_expone_identidades(  # INV-26 (f)
    client, crear_equipo, crear_linea, crear_usuario
):
    eq = await crear_equipo(codigo="PRIV-1", unidades=((USH,),))
    solicitante = await crear_usuario(R.ESTUDIANTE, USH, apellido="Reservadora")
    await crear_linea(eq, eq.unidades[0], D.RESERVADO, retiro=_retiro(1), solicitante=solicitante)
    docente = await crear_usuario(R.DOCENTE, USH)

    r = await client.get(_url(eq.id), params=_rango(0, 3), headers=auth(docente))

    assert set(r.json()) == {"equipamiento_id", "sede", "desde", "hasta", "unidades_asignables", "dias"}
    assert all(set(d) == {"fecha", "unidades_libres", "disponible"} for d in r.json()["dias"])
    assert "PRIV-1" not in r.text and "Reservadora" not in r.text


async def test_el_alcance_de_sede_aisla_la_disponibilidad(  # INV-30
    client, crear_equipo, crear_linea, crear_usuario
):
    eq = await crear_equipo(unidades=((USH,), (RG,), (RG,)))
    admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG)
    admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH)

    en_rg = (await client.get(_url(eq.id), params=_rango(0, 0), headers=auth(admin_rg))).json()
    en_ush = (await client.get(_url(eq.id), params=_rango(0, 0), headers=auth(admin_ush))).json()

    assert (en_rg["sede"], en_rg["unidades_asignables"]) == ("Río Grande", 2)
    assert (en_ush["sede"], en_ush["unidades_asignables"]) == ("Ushuaia", 1)


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE, R.ADMIN_LOCAL])
async def test_rol_local_con_otra_sede_es_403(client, crear_equipo, crear_usuario, rol):  # INV-30
    eq = await crear_equipo(unidades=((USH,), (RG,)))
    usuario = await crear_usuario(rol, USH)

    r = await client.get(_url(eq.id), params=_rango(0, 1, sede="Río Grande"), headers=auth(usuario))

    assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"


async def test_superadmin_debe_elegir_sede(client, crear_equipo, crear_usuario):  # INV-30
    eq = await crear_equipo(unidades=((USH,), (RG,)))
    sa = await crear_usuario(R.SUPERADMIN)

    sin_sede = await client.get(_url(eq.id), params=_rango(0, 1), headers=auth(sa))
    con_sede = await client.get(_url(eq.id), params=_rango(0, 1, sede="Río Grande"), headers=auth(sa))

    assert sin_sede.status_code == 422 and sin_sede.json()["code"] == "SEDE_REQUERIDA"
    assert con_sede.status_code == 200 and con_sede.json()["sede"] == "Río Grande"


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
async def test_item_inactivo_es_404_para_no_admin(client, crear_equipo, crear_usuario, rol):  # INV-30
    eq = await crear_equipo(unidades=((USH,),), activo=False)
    usuario = await crear_usuario(rol, USH)

    r = await client.get(_url(eq.id), params=_rango(0, 1), headers=auth(usuario))

    assert r.status_code == 404 and r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"


async def test_item_inactivo_para_admin_devuelve_todo_en_cero(  # INV-30
    client, crear_equipo, crear_usuario
):
    eq = await crear_equipo(unidades=((USH,),), activo=False)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    r = await client.get(_url(eq.id), params=_rango(0, 2), headers=auth(admin))

    assert r.status_code == 200
    assert r.json()["unidades_asignables"] == 0 and _libres(r.json()) == [0, 0, 0]
    assert [d["disponible"] for d in r.json()["dias"]] == [False] * 3


async def test_item_sin_unidades_en_la_sede_es_404_para_estudiante_y_cero_para_admin(  # INV-30
    client, crear_equipo, crear_usuario
):
    eq = await crear_equipo(unidades=((RG,),))
    alumno = await crear_usuario(R.ESTUDIANTE, USH)
    sin_unidades = await crear_equipo("EQ-2", "Sin stock")
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    r_alumno = await client.get(_url(eq.id), params=_rango(0, 1), headers=auth(alumno))
    r_admin = await client.get(_url(sin_unidades.id), params=_rango(0, 1), headers=auth(admin))

    assert r_alumno.status_code == 404
    assert r_admin.status_code == 200 and _libres(r_admin.json()) == [0, 0]


async def test_item_inexistente_es_404(client, crear_usuario):  # INV-30
    alumno = await crear_usuario(R.ESTUDIANTE, USH)
    r = await client.get(_url(99_999), params=_rango(0, 1), headers=auth(alumno))
    assert r.status_code == 404


@pytest.mark.parametrize(
    ("desde", "hasta"),
    [
        (3, 2),  # invertido
        (-1, 2),  # antes de hoy
        (0, MAX_DIAS_DISPONIBILIDAD),  # 63 días
    ],
)
async def test_rangos_invalidos_son_422(client, crear_equipo, crear_usuario, desde, hasta):  # INV-30
    eq = await crear_equipo(unidades=((USH,),))
    alumno = await crear_usuario(R.ESTUDIANTE, USH)

    r = await client.get(_url(eq.id), params=_rango(desde, hasta), headers=auth(alumno))

    assert r.status_code == 422 and r.json()["code"] == "RANGO_FECHAS_INVALIDO"


async def test_el_tope_de_62_dias_es_valido(client, crear_equipo, crear_usuario):  # INV-30
    eq = await crear_equipo(unidades=((USH,),))
    alumno = await crear_usuario(R.ESTUDIANTE, USH)

    r = await client.get(
        _url(eq.id), params=_rango(0, MAX_DIAS_DISPONIBILIDAD - 1), headers=auth(alumno)
    )

    assert r.status_code == 200 and len(r.json()["dias"]) == MAX_DIAS_DISPONIBILIDAD
