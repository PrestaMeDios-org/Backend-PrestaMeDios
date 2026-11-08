"""SPEC-03 §6.5 · API pública de `files` para `loans` — AC-86, EC-42.

``vincular_archivo`` se prueba sin `loans`: lo que importa es su contrato.
"""

import dataclasses
import uuid

import pytest
from sqlalchemy import select

from app.core.enums import RolUsuario
from app.core.errors import AppError
from app.modules.files.enums import PropositoArchivo
from app.modules.files.models import Archivo
from app.modules.files.service import (
    ArchivoContenido,
    abrir_archivo,
    respuesta_descarga,
    vincular_archivo,
)
from tests.files.conftest import jpeg_con_exif, pdf_minimo, subir_aval, subir_foto

pytestmark = pytest.mark.integracion

AVAL = PropositoArchivo.AVAL_PRESTAMO


async def _aval(client, usuario) -> uuid.UUID:
    r = await subir_aval(client, usuario)
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


async def _vinculado_en(sessionmaker_, archivo_id):
    async with sessionmaker_() as otra:
        return await otra.scalar(select(Archivo.vinculado_en).where(Archivo.id == archivo_id))


class TestVincularArchivo:  # AC-86
    async def test_vincula_sin_commit(self, client, db, sessionmaker_, crear_usuario):
        u = await crear_usuario(RolUsuario.ESTUDIANTE)
        uid = u.id
        archivo_id = await _aval(client, u)

        await vincular_archivo(db, archivo_id, propietario_id=uid, proposito=AVAL)
        assert await _vinculado_en(sessionmaker_, archivo_id) is None  # sin commit
        await db.commit()
        assert await _vinculado_en(sessionmaker_, archivo_id) is not None

    async def test_docente_tambien(self, client, db, crear_usuario):  # EC-47
        u = await crear_usuario(RolUsuario.DOCENTE)
        uid = u.id
        archivo_id = await _aval(client, u)
        await vincular_archivo(db, archivo_id, propietario_id=uid, proposito=AVAL)

    async def test_casos_invalidos_mismo_codigo(self, client, db, crear_usuario):  # D-19
        dueno = await crear_usuario(RolUsuario.ESTUDIANTE)
        otro = await crear_usuario(RolUsuario.ESTUDIANTE)
        uid, otro_id = dueno.id, otro.id
        archivo_id = await _aval(client, dueno)
        r = await subir_foto(client, dueno, jpeg_con_exif(32, 32))
        foto_id = uuid.UUID(r.json()["foto_id"])

        casos = [
            (archivo_id, otro_id, AVAL),  # otro propietario
            (archivo_id, uid, PropositoArchivo.FOTO_PERFIL),  # otro propósito
            (uuid.uuid4(), uid, AVAL),  # inexistente
            (foto_id, uid, AVAL),  # la foto ya está vinculada y es otro propósito
        ]
        for aid, pid, proposito in casos:
            with pytest.raises(AppError) as exc:
                await vincular_archivo(db, aid, propietario_id=pid, proposito=proposito)
            assert (exc.value.status_code, exc.value.code) == (422, "ARCHIVO_INVALIDO")
            await db.rollback()

        await vincular_archivo(db, archivo_id, propietario_id=uid, proposito=AVAL)
        await db.commit()
        with pytest.raises(AppError) as exc:  # ya vinculado
            await vincular_archivo(db, archivo_id, propietario_id=uid, proposito=AVAL)
        assert exc.value.code == "ARCHIVO_INVALIDO"


class TestAbrirYServir:
    async def test_abrir_archivo(self, client, db, crear_usuario):
        u = await crear_usuario(RolUsuario.ESTUDIANTE)
        archivo_id = await _aval(client, u)
        contenido = await abrir_archivo(db, archivo_id)
        assert isinstance(contenido, ArchivoContenido)
        assert contenido.id == archivo_id and contenido.datos == pdf_minimo()
        assert contenido.tipo_mime == "application/pdf"
        assert contenido.nombre_original == "resolucion.pdf"
        with pytest.raises(dataclasses.FrozenInstanceError):
            contenido.datos = b""  # type: ignore[misc]

    async def test_abrir_inexistente(self, db):
        assert await abrir_archivo(db, uuid.uuid4()) is None

    def test_respuesta_descarga(self):  # RN-61
        r = respuesta_descarga(
            ArchivoContenido(uuid.uuid4(), "application/pdf", "aval.pdf", b"%PDF-1.4")
        )
        assert r.body == b"%PDF-1.4" and r.media_type == "application/pdf"
        assert r.headers["content-disposition"].startswith("attachment;")
        assert r.headers["cache-control"] == "private, no-store"
