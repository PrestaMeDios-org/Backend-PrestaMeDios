"""Fábricas de los tests de `notifications` (SPEC-06)."""

from datetime import datetime, timedelta

import pytest

from app.core.enums import SedeEnum
from app.core.settings import ahora_lab
from app.modules.notifications.enums import EstadoComunicado
from app.modules.notifications.models import Comunicado


@pytest.fixture
def crear_comunicado(db):
    """Fábrica: inserta un comunicado directamente en la base.

    ``sede=None`` crea uno global. ``vencido=True`` lo publica hace dos días con
    vencimiento ayer (el ``CHECK`` exige ``vence_en > publicado_en``).
    """

    async def _crear(
        sede: SedeEnum | None = SedeEnum.USHUAIA,
        *,
        titulo: str = "Aviso",
        estado: EstadoComunicado = EstadoComunicado.PUBLICADO,
        vencido: bool = False,
        vence_en: datetime | None = None,
        autor=None,
        publicado_hace: timedelta = timedelta(hours=1),
    ) -> Comunicado:
        ahora = ahora_lab()
        publicado_en = ahora - (timedelta(days=2) if vencido else publicado_hace)
        comunicado = Comunicado(
            titulo=titulo,
            contenido=f"Contenido de {titulo}",
            sede=sede,
            es_global=sede is None,
            estado=estado,
            autor_id=autor._cache_auth["id"] if autor is not None else None,
            publicado_en=publicado_en,
            vence_en=ahora - timedelta(days=1) if vencido else vence_en,
            actualizado_en=publicado_en,
        )
        db.add(comunicado)
        await db.commit()
        return comunicado

    return _crear


def datos_de_ejemplo(tipo) -> dict[str, str]:
    """``datos`` válidos para ``tipo``: cada clave de su plantilla con un valor de prueba."""
    from app.modules.notifications.plantillas import PLANTILLAS

    return {clave: f"<{clave}>" for clave in sorted(PLANTILLAS[tipo].claves)}


@pytest.fixture
def notificar(db):
    """Fábrica (Fase B): crea una notificación con el contrato público y la confirma.

    Cada llamada es una transacción propia, así `creada_en` (``now()``) crece.
    """
    from app.modules.notifications.enums import TipoNotificacion
    from app.modules.notifications.service import crear_notificacion

    async def _notificar(usuario, tipo=TipoNotificacion.ORDEN_APROBADA, **kwargs):
        notificacion = await crear_notificacion(
            db, usuario._cache_auth["id"], tipo, datos_de_ejemplo(tipo), **kwargs
        )
        await db.commit()
        return notificacion

    return _notificar
