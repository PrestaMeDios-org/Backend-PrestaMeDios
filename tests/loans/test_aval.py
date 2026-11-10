"""Aval de alta gama (SPEC-05 T1.12; RN-L09, AC-L14, AC-L60; K3 y RN-60 de SPEC-03).

El PDF se sube por la API real de `files` (`POST /api/v1/files/archivos`), como lo
hará el frontend, y la orden lo referencia con `pdf_aval_id`. `loans` lo vincula con
`files.vincular_archivo` en la misma transacción que crea la orden.
"""

import uuid
from datetime import datetime, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RolUsuario, SedeEnum
from app.core.settings import ZONA_HORARIA_LAB
from app.modules.files.models import Archivo
from app.modules.loans.models import OrdenPedido
from tests.conftest import auth, dia
from tests.files.conftest import pdf_minimo, subir_aval

pytestmark = pytest.mark.integracion

URL = "/api/v1/loans/ordenes"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _a(dias: int, hora: int) -> datetime:
    return datetime.combine(dia(dias), time(hora), tzinfo=ZONA_HORARIA_LAB)


def _pedido(*equipamientos, **extra) -> dict:
    return {
        "asignatura_id": 7,
        "retiro": _a(3, 10).isoformat(),
        "devolucion": _a(5, 15).isoformat(),
        "items": [{"equipamiento_id": eq.id} for eq in equipamientos],
        "acepta_normativa": True,
        **extra,
    }


async def _aval(client, usuario) -> str:
    r = await subir_aval(client, usuario)
    assert r.status_code == 201, r.json()
    return r.json()["id"]


async def _vinculado_en(db: AsyncSession, archivo_id: str):
    return await db.scalar(
        select(Archivo.vinculado_en)
        .where(Archivo.id == uuid.UUID(archivo_id))
        .execution_options(populate_existing=True)
    )


async def _cantidad_de_ordenes(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(OrdenPedido))


# ── Crear con aval (AC-L14) ──────────────────────────────────────────────────


@pytest.mark.parametrize("rol", [E, D])
async def test_con_aval_valido_se_crea_y_el_archivo_queda_vinculado(
    client, db, crear_usuario, crear_equipamiento, rol
):  # AC-L14; también el docente (ADR-022 i, K3)
    usuario = await crear_usuario(rol)
    camara = await crear_equipamiento(alta_gama=True)
    aval = await _aval(client, usuario)

    r = await client.post(URL, json=_pedido(camara, pdf_aval_id=aval), headers=auth(usuario))

    assert r.status_code == 201, r.json()
    assert r.json()["aval_archivo_id"] == aval
    assert await _vinculado_en(db, aval) is not None


async def test_un_aval_ajeno_se_rechaza_sin_crear_nada(
    client, db, crear_usuario, crear_equipamiento
):  # D-19 de SPEC-03: un solo código, sin revelar por qué
    ana = await crear_usuario(E)
    beto = await crear_usuario(E)
    camara = await crear_equipamiento(alta_gama=True)
    aval_de_beto = await _aval(client, beto)

    r = await client.post(
        URL, json=_pedido(camara, pdf_aval_id=aval_de_beto), headers=auth(ana)
    )

    assert r.status_code == 422
    assert r.json()["code"] == "ARCHIVO_INVALIDO"
    assert await _cantidad_de_ordenes(db) == 0
    assert await _vinculado_en(db, aval_de_beto) is None


async def test_un_aval_inexistente_se_rechaza(client, db, crear_usuario, crear_equipamiento):
    ana = await crear_usuario(E)
    camara = await crear_equipamiento(alta_gama=True)
    r = await client.post(
        URL, json=_pedido(camara, pdf_aval_id=str(uuid.uuid4())), headers=auth(ana)
    )
    assert r.status_code == 422
    assert r.json()["code"] == "ARCHIVO_INVALIDO"
    assert await _cantidad_de_ordenes(db) == 0


async def test_un_aval_ya_usado_en_otra_orden_se_rechaza(
    client, db, crear_usuario, crear_equipamiento
):  # cada orden lleva su propio aval (D-19 de SPEC-03, reutilizar queda abierto)
    ana = await crear_usuario(E)
    camara = await crear_equipamiento(alta_gama=True, estados=("disponible",) * 2)
    aval = await _aval(client, ana)
    primera = await client.post(URL, json=_pedido(camara, pdf_aval_id=aval), headers=auth(ana))
    assert primera.status_code == 201, primera.json()

    segunda = await client.post(URL, json=_pedido(camara, pdf_aval_id=aval), headers=auth(ana))

    assert segunda.status_code == 422
    assert segunda.json()["code"] == "ARCHIVO_INVALIDO"
    assert await _cantidad_de_ordenes(db) == 1


async def test_si_falla_otra_validacion_el_aval_no_se_vincula(
    client, db, crear_usuario, crear_equipamiento
):  # las validaciones van antes de escribir: un 409 no deja el archivo usado
    ana = await crear_usuario(E)
    sin_unidades = await crear_equipamiento(alta_gama=True, estados=())
    aval = await _aval(client, ana)

    r = await client.post(
        URL, json=_pedido(sin_unidades, pdf_aval_id=aval), headers=auth(ana)
    )

    assert r.status_code == 409
    assert await _vinculado_en(db, aval) is None


async def test_si_falla_el_commit_el_aval_no_queda_vinculado(
    client, db, crear_usuario, crear_equipamiento, monkeypatch
):  # AC-L14: vincular y crear la orden son una sola transacción
    ana = await crear_usuario(E)
    camara = await crear_equipamiento(alta_gama=True)
    aval = await _aval(client, ana)

    async def _commit_que_falla(self):
        raise RuntimeError("la base se cayó")

    monkeypatch.setattr(AsyncSession, "commit", _commit_que_falla)
    with pytest.raises(RuntimeError):
        await client.post(URL, json=_pedido(camara, pdf_aval_id=aval), headers=auth(ana))
    monkeypatch.undo()

    assert await _cantidad_de_ordenes(db) == 0
    assert await _vinculado_en(db, aval) is None


async def test_sin_alta_gama_el_aval_se_ignora(client, db, crear_usuario, crear_equipamiento):
    ana = await crear_usuario(E)
    camara = await crear_equipamiento()
    aval = await _aval(client, ana)

    r = await client.post(URL, json=_pedido(camara, pdf_aval_id=aval), headers=auth(ana))

    assert r.status_code == 201, r.json()
    assert r.json()["aval_archivo_id"] is None
    assert await _vinculado_en(db, aval) is None  # queda huérfano y lo limpia `files`


# ── Descargar el aval (AC-L60) ───────────────────────────────────────────────


async def _orden_con_aval(client, crear_usuario, crear_equipamiento, sede=USH):
    ana = await crear_usuario(E, sede)
    camara = await crear_equipamiento(alta_gama=True, sede=sede)
    aval = await _aval(client, ana)
    r = await client.post(URL, json=_pedido(camara, pdf_aval_id=aval), headers=auth(ana))
    assert r.status_code == 201, r.json()
    return ana, r.json()["id"]


async def test_el_solicitante_descarga_su_aval(client, crear_usuario, crear_equipamiento):
    ana, orden_id = await _orden_con_aval(client, crear_usuario, crear_equipamiento)

    r = await client.get(f"{URL}/{orden_id}/aval", headers=auth(ana))

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == pdf_minimo()


@pytest.mark.parametrize(("rol", "sede"), [(A, USH), (S, None)])
async def test_el_admin_con_jurisdiccion_descarga_el_aval(
    client, crear_usuario, crear_equipamiento, rol, sede
):  # RN-60: lo revisa antes de aprobar
    _, orden_id = await _orden_con_aval(client, crear_usuario, crear_equipamiento)
    admin = await crear_usuario(rol, sede)
    r = await client.get(f"{URL}/{orden_id}/aval", headers=auth(admin))
    assert r.status_code == 200
    assert r.content == pdf_minimo()


@pytest.mark.parametrize(("rol", "sede"), [(A, RG), (E, USH), (D, USH)])
async def test_sin_alcance_responde_404(client, crear_usuario, crear_equipamiento, rol, sede):
    # AC-L60: ni el admin de otra sede, ni otro estudiante, ni un docente (aunque sea el
    # de la asignatura, RN-60 de SPEC-03)
    _, orden_id = await _orden_con_aval(client, crear_usuario, crear_equipamiento)
    otro = await crear_usuario(rol, sede)
    r = await client.get(f"{URL}/{orden_id}/aval", headers=auth(otro))
    assert r.status_code == 404


async def test_una_orden_sin_aval_responde_404(client, crear_usuario, crear_equipamiento):
    ana = await crear_usuario(E)
    camara = await crear_equipamiento()
    r = await client.post(URL, json=_pedido(camara), headers=auth(ana))
    r = await client.get(f"{URL}/{r.json()['id']}/aval", headers=auth(ana))
    assert r.status_code == 404
    assert r.json()["code"] == "ARCHIVO_NO_ENCONTRADO"


async def test_descargar_exige_sesion(client):  # AC-L52
    r = await client.get(f"{URL}/1/aval")
    assert r.status_code == 401
