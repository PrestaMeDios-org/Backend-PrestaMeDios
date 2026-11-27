"""UC-08/UC-09 · Panel de Parámetros Globales (GLO-03) — AC-25…AC-30, EC-18…EC-20.

Los valores de la semilla los verifica ``test_semilla.py``; la edición concurrente (EC-19),
``test_sedes.py::test_ediciones_simultaneas_del_par``.
"""

from datetime import time

import pytest

from app.core.enums import RolUsuario, SedeEnum, TipoParametro
from app.core.errors import AppError
from app.modules.config.seed import PARAMETROS_SEMILLA
from app.modules.config.service import obtener_parametro, validar_valor
from tests.conftest import auth

pytestmark = pytest.mark.integracion

URL = "/api/v1/config/parametros"
R = RolUsuario


async def _put(client, actor, clave, **payload):
    return await client.put(f"{URL}/{clave}", json=payload, headers=auth(actor))


async def test_lectura_por_cualquier_usuario_activo(client, crear_usuario):  # AC-25, UC-08
    estudiante = await crear_usuario(R.ESTUDIANTE, SedeEnum.USHUAIA)
    r = await client.get(URL, headers=auth(estudiante))
    assert r.status_code == 200
    por_clave = {p["clave"]: p for p in r.json()}
    assert set(por_clave) == {p["clave"] for p in PARAMETROS_SEMILLA}

    uno = await client.get(f"{URL}/horario.cierre", headers=auth(estudiante))
    assert uno.status_code == 200 and uno.json()["tipo"] == "HORA"


async def test_lectura_requiere_sesion(client, db):
    assert (await client.get(URL)).status_code == 401


async def test_modificacion_exitosa_e_historial(client, crear_usuario):  # AC-26
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _put(client, sa, "prestamo.general.max_dias", valor=3, version=1, motivo="Temporada alta")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valor"] == 3 and body["version"] == 2 and body["actualizado_por_id"] == sa.id

    hist = await client.get(f"{URL}/prestamo.general.max_dias/historial", headers=auth(sa))
    assert hist.status_code == 200
    (h,) = hist.json()
    assert (h["valor_anterior"], h["valor_nuevo"], h["version"], h["actor_id"]) == (4, 3, 2, sa.id)
    assert h["motivo"] == "Temporada alta"


async def test_valor_identico_es_idempotente(client, crear_usuario):  # UC-09 FA-05
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _put(client, sa, "prestamo.general.max_dias", valor=4, version=1)
    assert r.status_code == 200 and r.json()["version"] == 1
    hist = await client.get(f"{URL}/prestamo.general.max_dias/historial", headers=auth(sa))
    assert hist.json() == []


async def test_bloqueo_optimista(client, crear_usuario):  # AC-27
    sa = await crear_usuario(R.SUPERADMIN)
    assert (await _put(client, sa, "prestamo.general.max_dias", valor=3, version=1)).status_code == 200
    r = await _put(client, sa, "prestamo.general.max_dias", valor=2, version=1)
    assert r.status_code == 409
    assert r.json()["code"] == "CONFLICTO_VERSION" and r.json()["version_actual"] == 2


@pytest.mark.parametrize(
    ("clave", "valor", "codigo"),
    [
        ("prestamo.general.max_dias", True, "VALOR_PARAMETRO_INVALIDO"),  # EC-20
        ("prestamo.general.max_dias", 4.0, "VALOR_PARAMETRO_INVALIDO"),
        ("prestamo.general.max_dias", "4", "VALOR_PARAMETRO_INVALIDO"),
        ("prestamo.general.max_dias", 0, "VALOR_PARAMETRO_INVALIDO"),
        ("prestamo.general.max_dias", 16, "VALOR_PARAMETRO_INVALIDO"),
        # Desde SPEC-09 el horario se edita por sede; las claves globales son obsoletas (RN-81).
        # Apertura antes del cierre (AC-105): test_sedes.py.
        ("horario.ushuaia.cierre", "25:00", "VALOR_PARAMETRO_INVALIDO"),
        ("horario.rio_grande.cierre", "9:00", "VALOR_PARAMETRO_INVALIDO"),
        ("prestamo.notebook.max_dias", 3, "PARAMETROS_INCONSISTENTES"),
        ("reserva_espacio.anticipacion_max_dias", 1, "PARAMETROS_INCONSISTENTES"),
    ],
)
async def test_validacion_tipo_rango_y_coherencia(client, crear_usuario, clave, valor, codigo):  # AC-28
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _put(client, sa, clave, valor=valor, version=1)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == codigo


@pytest.mark.parametrize(
    ("rol", "clave", "valor"),
    [
        (R.ADMIN_LOCAL, "prestamo.general.max_dias", 3),
        (R.DOCENTE, "prestamo.general.max_dias", 3),
        (R.ESTUDIANTE, "prestamo.general.max_dias", 3),
        # El admin de Ushuaia tampoco edita el horario ni el correo de su sede (AC-111, RN-85, D-08).
        (R.ADMIN_LOCAL, "horario.ushuaia.apertura", "08:00"),
        (R.ADMIN_LOCAL, "contacto.ushuaia.email", "a@example.com"),
    ],
)
async def test_solo_superadmin_escribe(client, crear_usuario, rol, clave, valor):  # AC-29, D-05
    u = await crear_usuario(rol, SedeEnum.USHUAIA)
    r = await _put(client, u, clave, valor=valor, version=1)
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


async def test_historial_visible_para_admin_local_no_para_estudiante(client, crear_usuario):
    admin = await crear_usuario(R.ADMIN_LOCAL, SedeEnum.USHUAIA)
    est = await crear_usuario(R.ESTUDIANTE, SedeEnum.USHUAIA)
    assert (await client.get(f"{URL}/horario.apertura/historial", headers=auth(admin))).status_code == 200
    assert (await client.get(f"{URL}/horario.apertura/historial", headers=auth(est))).status_code == 403


async def test_catalogo_cerrado(client, crear_usuario):  # AC-30
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _put(client, sa, "clave.inexistente", valor=1, version=1)
    assert r.status_code == 404 and r.json()["code"] == "PARAMETRO_NO_ENCONTRADO"
    assert (await client.post(URL, json={}, headers=auth(sa))).status_code == 405
    assert (await client.delete(f"{URL}/horario.apertura", headers=auth(sa))).status_code == 405


async def test_obtener_parametro_tipado(db):  # §12.1
    assert await obtener_parametro(db, "horario.apertura") == time(9, 0)
    assert await obtener_parametro(db, "solicitud.anticipacion_min_horas") == 24
    with pytest.raises(AppError) as exc:
        await obtener_parametro(db, "no.existe")
    assert exc.value.code == "PARAMETRO_NO_CONFIGURADO"


class TestValidarValorUnitario:  # RN-19
    @pytest.mark.parametrize(
        ("tipo", "valor"),
        [
            (TipoParametro.DECIMAL, 1.5),
            (TipoParametro.DECIMAL, 2),
            (TipoParametro.BOOLEANO, False),
            (TipoParametro.TEXTO, "hola"),
            (TipoParametro.HORA, "23:59"),
        ],
    )
    def test_validos(self, tipo, valor):
        validar_valor(tipo, valor)

    @pytest.mark.parametrize(
        ("tipo", "valor"),
        [
            (TipoParametro.DECIMAL, True),
            (TipoParametro.BOOLEANO, 1),
            (TipoParametro.TEXTO, ""),
            (TipoParametro.TEXTO, "x" * 301),
            (TipoParametro.HORA, "24:00"),
        ],
    )
    def test_invalidos(self, tipo, valor):
        with pytest.raises(AppError):
            validar_valor(tipo, valor)
