"""SPEC-09 Fase A · horario y correo de contacto por sede (GLO-02, GLO-03).

AC-103…AC-111; EC-53, EC-55 y EC-56. AC-102, AC-112 y la parte de migración de
AC-103 están en ``test_migracion_0017.py``; AC-109, en ``test_semilla.py``.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import time

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.enums import RolUsuario, SedeEnum
from app.core.errors import AppError
from app.modules.config import service
from app.modules.config.models import ParametroGlobal
from app.modules.config.service import DatosSede, datos_de_sede, datos_de_sedes, obtener_parametro
from tests.conftest import auth

pytestmark = pytest.mark.integracion

URL = "/api/v1/config/parametros"
URL_SEDES = "/api/v1/config/sedes"
R = RolUsuario


async def _put(client, actor, clave, **payload):
    return await client.put(f"{URL}/{clave}", json=payload, headers=auth(actor))


async def _version(db: AsyncSession, clave: str) -> int:
    db.expire_all()
    return (await db.get(ParametroGlobal, clave)).version


@pytest.fixture
async def sesion(
    db: AsyncSession, sessionmaker_: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncSession]:
    """Sesión limpia, distinta de ``db``, como la que recibe un servicio de otro módulo."""
    async with sessionmaker_() as session:
        yield session


@pytest.fixture
def consultas(engine: AsyncEngine) -> Iterator[list[str]]:
    emitidas: list[str] = []

    def _registrar(conn, cursor, statement, parameters, context, executemany) -> None:
        emitidas.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _registrar)
    yield emitidas
    event.remove(engine.sync_engine, "before_cursor_execute", _registrar)


# ── Escritura por el panel ───────────────────────────────────────────────────


async def test_globales_obsoletas_no_se_editan(client, db, crear_usuario):  # AC-103, RN-81
    sa = await crear_usuario(R.SUPERADMIN)
    for clave in ("horario.apertura", "horario.cierre"):
        r = await _put(client, sa, clave, valor="08:00", version=1)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "PARAMETRO_NO_EDITABLE"
    assert await obtener_parametro(db, "horario.apertura") == time(9, 0)


async def test_horario_de_una_sede_sin_tocar_la_otra(client, db, crear_usuario):  # AC-104
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _put(client, sa, "horario.rio_grande.apertura", valor="10:00", version=1)
    assert r.status_code == 200, r.text
    r = await _put(client, sa, "horario.rio_grande.cierre", valor="17:00", version=1, motivo="Horario de RG")
    assert r.status_code == 200, r.text

    for clave in ("horario.rio_grande.apertura", "horario.rio_grande.cierre"):
        hist = await client.get(f"{URL}/{clave}/historial", headers=auth(sa))
        assert len(hist.json()) == 1
    rg = await datos_de_sede(db, SedeEnum.RIO_GRANDE)
    ush = await datos_de_sede(db, SedeEnum.USHUAIA)
    assert (rg.horario_apertura, rg.horario_cierre) == (time(10, 0), time(17, 0))
    assert (ush.horario_apertura, ush.horario_cierre) == (time(9, 0), time(16, 0))


@pytest.mark.parametrize("apertura", ["16:00", "17:00"])
async def test_apertura_antes_del_cierre_en_cada_sede(client, crear_usuario, apertura):  # AC-105
    sa = await crear_usuario(R.SUPERADMIN)
    r = await _put(client, sa, "horario.ushuaia.apertura", valor=apertura, version=1)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "PARAMETROS_INCONSISTENTES"

    assert (await _put(client, sa, "horario.rio_grande.cierre", valor="18:00", version=1)).status_code == 200
    r = await _put(client, sa, "horario.rio_grande.apertura", valor=apertura, version=1)
    assert r.status_code == 200, r.text


@pytest.fixture
def validacion_en_paralelo(monkeypatch):
    """Retiene cada edición justo después de la validación cruzada, hasta que la otra
    también valide o pase medio segundo. Sin el bloqueo del par (G-5), las dos validan
    contra los valores viejos y las dos confirman; con el bloqueo, la segunda espera."""
    original = service.validar_reglas_cruzadas
    llegaron = 0
    ambas = asyncio.Event()

    async def _validar(*args, **kwargs):
        nonlocal llegaron
        await original(*args, **kwargs)
        llegaron += 1
        if llegaron == 2:
            ambas.set()
        try:
            await asyncio.wait_for(ambas.wait(), timeout=0.5)
        except TimeoutError:
            pass

    monkeypatch.setattr(service, "validar_reglas_cruzadas", _validar)


@pytest.mark.parametrize(
    ("a", "b", "par_valido"),
    [
        # Con 09:00–16:00, cada cambio solo es válido; juntos invierten el horario.
        (
            ("horario.ushuaia.apertura", "15:00"),
            ("horario.ushuaia.cierre", "14:00"),
            lambda v: v["horario.ushuaia.apertura"] < v["horario.ushuaia.cierre"],
        ),
        (
            ("horario.ushuaia.cierre", "14:00"),
            ("horario.ushuaia.apertura", "15:00"),
            lambda v: v["horario.ushuaia.apertura"] < v["horario.ushuaia.cierre"],
        ),
        # Un par global (RN-20 de SPEC-01): 4 ≤ 15 → 10 y 5 por separado, 10 > 5 juntos.
        (
            ("prestamo.general.max_dias", 10),
            ("prestamo.notebook.max_dias", 5),
            lambda v: v["prestamo.general.max_dias"] <= v["prestamo.notebook.max_dias"],
        ),
    ],
)
async def test_ediciones_simultaneas_del_par(  # AC-106, EC-53, G-5
    client, db, crear_usuario, validacion_en_paralelo, a, b, par_valido
):
    sa1 = await crear_usuario(R.SUPERADMIN)
    sa2 = await crear_usuario(R.SUPERADMIN)
    respuestas = await asyncio.gather(
        _put(client, sa1, a[0], valor=a[1], version=1),
        _put(client, sa2, b[0], valor=b[1], version=1),
    )
    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [200, 422], [r.text for r in respuestas]
    (rechazada,) = [r for r in respuestas if r.status_code == 422]
    assert rechazada.json()["code"] == "PARAMETROS_INCONSISTENTES"

    db.expire_all()
    filas = await db.scalars(select(ParametroGlobal).where(ParametroGlobal.clave.in_([a[0], b[0]])))
    valores = {p.clave: service.convertir(p.tipo, p.valor) for p in filas.all()}
    assert par_valido(valores)


async def test_correo_de_contacto(client, db, crear_usuario):  # AC-107, RN-80
    sa = await crear_usuario(R.SUPERADMIN)
    clave = "contacto.rio_grande.email"

    for invalido in ("no-es-un-correo", "a@b", "x" * 250 + "@example.com"):
        r = await _put(client, sa, clave, valor=invalido, version=1)
        assert r.status_code == 422, invalido
        assert r.json()["code"] == "VALOR_PARAMETRO_INVALIDO"

    r = await _put(client, sa, clave, valor=" Lab.RG@Example.com ", version=1)
    assert r.status_code == 200, r.text
    assert r.json()["valor"] == "lab.rg@example.com"

    # Idempotente con el valor normalizado (FA-05 de UC-09).
    r = await _put(client, sa, clave, valor="LAB.RG@example.com", version=2)
    assert r.status_code == 200 and r.json()["version"] == 2

    r = await _put(client, sa, clave, valor="", version=2)
    assert r.status_code == 422
    assert (await db.get(ParametroGlobal, clave)).valor == "lab.rg@example.com"


async def test_admin_local_no_edita_su_sede(client, crear_usuario):  # AC-111, RN-85, D-08
    admin = await crear_usuario(R.ADMIN_LOCAL, SedeEnum.USHUAIA)
    for clave, valor in (("horario.ushuaia.apertura", "08:00"), ("contacto.ushuaia.email", "a@example.com")):
        r = await _put(client, admin, clave, valor=valor, version=1)
        assert r.status_code == 403, clave


# ── Lectura para otros módulos (§4.4) ───────────────────────────────────────


async def test_datos_de_sede_tipados(sesion, set_parametro):  # AC-108, EC-55
    await set_parametro("contacto.ushuaia.email", "lab.ush@example.com")

    ush = await datos_de_sede(sesion, SedeEnum.USHUAIA)
    assert ush == DatosSede(SedeEnum.USHUAIA, time(9, 0), time(16, 0), "lab.ush@example.com")
    rg = await datos_de_sede(sesion, SedeEnum.RIO_GRANDE)
    assert rg.correo_contacto is None  # "" → None (EC-55)

    todas = await datos_de_sedes(sesion)
    assert list(todas) == list(SedeEnum)
    assert todas[SedeEnum.USHUAIA] == ush and todas[SedeEnum.RIO_GRANDE] == rg


async def test_datos_de_sede_una_consulta(sesion, consultas):  # AC-108, NFR-24
    await datos_de_sedes(sesion)
    assert len(consultas) == 1
    consultas.clear()
    await datos_de_sede(sesion, SedeEnum.RIO_GRANDE)
    assert len(consultas) == 1


async def test_datos_de_sede_no_confirma_la_transaccion(sesion, sessionmaker_):  # AC-108, RN-82
    parametro = await sesion.get(ParametroGlobal, "prestamo.general.max_dias")
    parametro.descripcion = "Cambio pendiente del llamador"

    await datos_de_sede(sesion, SedeEnum.USHUAIA)

    assert sesion.in_transaction()
    assert parametro in sesion.dirty
    await sesion.rollback()
    async with sessionmaker_() as otra:
        guardado = await otra.get(ParametroGlobal, "prestamo.general.max_dias")
        assert guardado.descripcion != "Cambio pendiente del llamador"


async def test_datos_de_sede_sin_una_clave(db, sesion):  # AC-108, RN-82
    await db.execute(text("DELETE FROM parametros_globales WHERE clave = 'contacto.rio_grande.email'"))
    await db.commit()
    with pytest.raises(AppError) as exc:
        await datos_de_sedes(sesion)
    assert exc.value.status_code == 500 and exc.value.code == "PARAMETRO_NO_CONFIGURADO"
    assert (await datos_de_sede(sesion, SedeEnum.USHUAIA)).sede == SedeEnum.USHUAIA


# ── Lectura por la API (§4.5) ────────────────────────────────────────────────


@pytest.mark.parametrize("rol", list(R))
async def test_get_sedes_para_cualquier_rol(client, crear_usuario, set_parametro, rol):  # AC-110, EC-56
    await set_parametro("contacto.rio_grande.email", "lab.rg@example.com")
    sede = None if rol == R.SUPERADMIN else SedeEnum.USHUAIA
    usuario = await crear_usuario(rol, sede)

    r = await client.get(URL_SEDES, headers=auth(usuario))
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"sede": "Ushuaia", "horario_apertura": "09:00:00", "horario_cierre": "16:00:00",
         "correo_contacto": None},
        {"sede": "Río Grande", "horario_apertura": "09:00:00", "horario_cierre": "16:00:00",
         "correo_contacto": "lab.rg@example.com"},
    ]


async def test_get_sedes_requiere_sesion(client, db):  # AC-110, RN-83
    assert (await client.get(URL_SEDES)).status_code == 401
