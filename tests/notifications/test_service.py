"""SPEC-06 Fase B · Contrato público `crear_notificacion` (§6.1) — NTF-13, NTF-14, NTF-21, NTF-22."""

import pytest
from sqlalchemy import func, select

from app.core.enums import EstadoCuenta, RolUsuario
from app.modules.notifications.enums import Severidad, TipoNotificacion
from app.modules.notifications.models import Notificacion
from app.modules.notifications.schemas import ReferenciaNotificacion
from app.modules.notifications.service import crear_notificacion, crear_notificaciones
from tests.notifications.conftest import datos_de_ejemplo

pytestmark = pytest.mark.integracion

T = TipoNotificacion


async def _cantidad(db) -> int:
    return await db.scalar(select(func.count()).select_from(Notificacion))


async def test_queda_en_la_transaccion_del_llamador(db, crear_usuario):  # NTF-13 (RN-N10)
    u = await crear_usuario(RolUsuario.ESTUDIANTE)
    uid = u._cache_auth["id"]

    await crear_notificacion(db, uid, T.ORDEN_APROBADA, datos_de_ejemplo(T.ORDEN_APROBADA))
    await db.rollback()
    assert await _cantidad(db) == 0  # el llamador deshizo: no se avisa nada

    ref = ReferenciaNotificacion(modulo="loans", id=42)
    n = await crear_notificacion(
        db, uid, T.ORDEN_HORARIO_AJUSTADO, datos_de_ejemplo(T.ORDEN_HORARIO_AJUSTADO), referencia=ref
    )
    await db.commit()
    assert await _cantidad(db) == 1
    assert (n.tipo, n.severidad) == ("ORDEN_HORARIO_AJUSTADO", Severidad.CRITICA)
    assert (n.referencia_modulo, n.referencia_id) == ("loans", 42)
    assert n.leida_en is None


async def test_no_hace_flush(db, crear_usuario):  # NTF-13 (RN-N10)
    u = await crear_usuario(RolUsuario.ESTUDIANTE)
    n = await crear_notificacion(
        db, u._cache_auth["id"], T.ORDEN_APROBADA, datos_de_ejemplo(T.ORDEN_APROBADA)
    )
    assert n.id is None and n in db.new  # agregada, todavía sin enviar a la base
    await db.rollback()


async def test_datos_invalidos_no_agregan_nada(db, crear_usuario):  # NTF-14
    u = await crear_usuario(RolUsuario.ESTUDIANTE)
    with pytest.raises(ValueError):
        await crear_notificacion(db, u._cache_auth["id"], T.ORDEN_APROBADA, {"numero_orden": "1"})
    assert not db.new


async def test_varios_destinatarios_una_vez_cada_uno(db, crear_usuario):  # NTF-21
    a = (await crear_usuario(RolUsuario.ESTUDIANTE))._cache_auth["id"]
    b = (await crear_usuario(RolUsuario.DOCENTE))._cache_auth["id"]
    creadas = await crear_notificaciones(
        db, [a, b, a, b, a], T.RESERVA_RECHAZADA, datos_de_ejemplo(T.RESERVA_RECHAZADA)
    )
    await db.commit()
    assert [n.usuario_id for n in creadas] == [a, b]
    assert await _cantidad(db) == 2


async def test_lista_vacia_no_hace_nada(db):  # NTF-21
    assert await crear_notificaciones(db, [], T.ORDEN_APROBADA, {}) == []
    assert not db.new


async def test_se_notifica_a_una_cuenta_suspendida(client, db, crear_usuario):  # NTF-22 (RN-N12)
    u = await crear_usuario(RolUsuario.ESTUDIANTE, estado=EstadoCuenta.SUSPENDIDO)
    await crear_notificacion(
        db, u._cache_auth["id"], T.ORDEN_CANCELADA, datos_de_ejemplo(T.ORDEN_CANCELADA)
    )
    await db.commit()
    assert await _cantidad(db) == 1
