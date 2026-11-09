"""SPEC-03 §6.3 · Foto de perfil — AC-83, AC-84, AC-89, EC-41."""

import asyncio
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.core.enums import RolUsuario, SedeEnum
from app.modules.files.models import Archivo, ArchivoDatos
from app.modules.users.models import Usuario, UsuarioHistorialCambios
from tests.conftest import auth
from tests.files.conftest import (  # noqa: F401 (`limite_mb` es una fixture)
    FOTO,
    imagen,
    jpeg_con_exif,
    limite_mb,
    pdf_minimo,
    subir_foto,
)

pytestmark = pytest.mark.integracion

E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
ADMIN, SUPER = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _quitar_de(usuario_id: int) -> str:
    return f"/api/v1/users/{usuario_id}/foto"


async def _historial(db, usuario_id):
    db.expire_all()
    return (
        await db.scalars(
            select(UsuarioHistorialCambios.cambios)
            .where(UsuarioHistorialCambios.usuario_id == usuario_id)
            .order_by(UsuarioHistorialCambios.id)
        )
    ).all()


async def _datos(db, archivo_id: str) -> bytes | None:
    return await db.scalar(
        select(ArchivoDatos.datos).where(ArchivoDatos.archivo_id == uuid.UUID(archivo_id))
    )


async def _cantidad_archivos(db) -> int:
    return await db.scalar(select(func.count()).select_from(Archivo))


class TestSubirFoto:
    async def test_jpeg_con_exif(self, client, db, crear_usuario):  # AC-83, D-11
        u = await crear_usuario(E)
        r = await subir_foto(client, u, jpeg_con_exif(1600, 1200))
        assert r.status_code == 200, r.text
        foto_id = r.json()["foto_id"]
        assert uuid.UUID(foto_id)

        guardada = await _datos(db, foto_id)
        img = Image.open(io.BytesIO(guardada))
        assert img.format == "JPEG" and max(img.size) == 512
        assert not img.getexif() and b"Exif" not in guardada
        archivo = await db.get(Archivo, uuid.UUID(foto_id))
        assert archivo.proposito == "FOTO_PERFIL" and archivo.vinculado_en is not None
        assert archivo.tipo_mime == "image/jpeg" and archivo.nombre_original == "foto.jpg"

    async def test_aparece_en_me(self, client, crear_usuario):
        u = await crear_usuario(E)
        foto_id = (await subir_foto(client, u, imagen("PNG"))).json()["foto_id"]
        r = await client.get("/api/v1/auth/me", headers=auth(u))
        assert r.json()["foto_id"] == foto_id

    @pytest.mark.parametrize(
        ("datos", "code"),
        [
            (pdf_minimo(), "TIPO_ARCHIVO_NO_PERMITIDO"),
            (b"GIF89a" + b"\x00" * 20, "TIPO_ARCHIVO_NO_PERMITIDO"),
            (b"\xff\xd8\xff\xe0 no es una imagen", "IMAGEN_INVALIDA"),
        ],
    )
    async def test_rechazos(self, client, db, crear_usuario, datos, code):  # RN-55, D-11
        u = await crear_usuario(E)
        r = await subir_foto(client, u, datos)
        assert r.status_code == 422 and r.json()["code"] == code
        assert await _cantidad_archivos(db) == 0

    async def test_demasiado_grande(self, client, crear_usuario, limite_mb):  # RN-56
        limite_mb(foto=1)
        u = await crear_usuario(E)
        r = await subir_foto(client, u, imagen("JPEG") + b"\x00" * (1024 * 1024))
        assert r.status_code == 422 and r.json()["code"] == "ARCHIVO_DEMASIADO_GRANDE"

    @pytest.mark.parametrize("rol", [D, ADMIN, SUPER])
    async def test_todos_los_roles(self, client, crear_usuario, rol):
        u = await crear_usuario(rol, USH)
        assert (await subir_foto(client, u, imagen("WEBP"))).status_code == 200

    async def test_cambio_de_password_pendiente(self, client, db, crear_usuario):
        u = await crear_usuario(E)
        u.debe_cambiar_password = True
        await db.commit()
        r = await subir_foto(client, u, imagen("PNG"))
        assert r.status_code == 403 and r.json()["code"] == "CAMBIO_PASSWORD_REQUERIDO"

    async def test_no_cuenta_para_la_cuota(self, client, crear_usuario, monkeypatch):  # RN-58
        from app.core.settings import get_settings

        monkeypatch.setattr(get_settings(), "archivo_max_pendientes", 1)
        u = await crear_usuario(E)
        for _ in range(3):
            assert (await subir_foto(client, u, imagen("PNG"))).status_code == 200


class TestReemplazarYQuitar:  # AC-84, RN-59
    async def test_reemplazar_borra_la_anterior(self, client, db, crear_usuario):
        u = await crear_usuario(E)
        uid = u.id
        primera = (await subir_foto(client, u, imagen("PNG"))).json()["foto_id"]
        segunda = (await subir_foto(client, u, imagen("JPEG"))).json()["foto_id"]
        assert primera != segunda
        assert await db.get(Archivo, uuid.UUID(primera)) is None
        assert await _datos(db, primera) is None
        assert await _cantidad_archivos(db) == 1
        assert await _historial(db, uid) == [
            {"foto_id": [None, primera]},
            {"foto_id": [primera, segunda]},
        ]

    async def test_quitar(self, client, db, crear_usuario):
        u = await crear_usuario(E)
        uid = u.id
        foto = (await subir_foto(client, u, imagen("PNG"))).json()["foto_id"]
        r = await client.delete(FOTO, headers=auth(u))
        assert r.status_code == 200 and r.json()["foto_id"] is None
        assert await _cantidad_archivos(db) == 0
        assert (await _historial(db, uid))[-1] == {"foto_id": [foto, None]}

    async def test_quitar_sin_foto(self, client, db, crear_usuario):
        u = await crear_usuario(E)
        uid = u.id
        r = await client.delete(FOTO, headers=auth(u))
        assert r.status_code == 200 and r.json()["foto_id"] is None
        assert await _historial(db, uid) == []

    async def test_dos_pestanas_a_la_vez(self, client, db, crear_usuario):  # EC-41
        u = await crear_usuario(E)
        uid = u.id
        r1, r2 = await asyncio.gather(
            subir_foto(client, u, imagen("PNG")), subir_foto(client, u, imagen("JPEG"))
        )
        assert r1.status_code == r2.status_code == 200
        db.expire_all()
        vigente = await db.scalar(select(Usuario.foto_id).where(Usuario.id == uid))
        assert vigente is not None
        assert {str(i) for i in await db.scalars(select(Archivo.id))} == {str(vigente)}


class TestQuitarPorAdmin:  # AC-89, RN-64
    async def _con_foto(self, client, crear_usuario, rol=E, sede=USH):
        u = await crear_usuario(rol, sede)
        assert (await subir_foto(client, u, imagen("PNG"))).status_code == 200
        return u

    async def test_admin_local_de_la_sede(self, client, db, crear_usuario):
        objetivo = await self._con_foto(client, crear_usuario)
        oid = objetivo.id
        admin = await crear_usuario(ADMIN, USH)
        aid = admin.id
        r = await client.delete(_quitar_de(oid), headers=auth(admin))
        assert r.status_code == 200, r.text
        assert r.json()["foto_id"] is None and "updated_at" in r.json()
        assert await _cantidad_archivos(db) == 0
        db.expire_all()
        actor = await db.scalar(
            select(UsuarioHistorialCambios.actor_id)
            .where(UsuarioHistorialCambios.usuario_id == oid)
            .order_by(UsuarioHistorialCambios.id.desc())
            .limit(1)
        )
        assert actor == aid

    async def test_admin_local_de_otra_sede(self, client, db, crear_usuario):
        objetivo = await self._con_foto(client, crear_usuario)
        admin = await crear_usuario(ADMIN, RG)
        r = await client.delete(_quitar_de(objetivo.id), headers=auth(admin))
        assert r.status_code == 404 and r.json()["code"] == "USUARIO_NO_ENCONTRADO"
        assert await _cantidad_archivos(db) == 1

    async def test_admin_local_sobre_un_administrador(self, client, db, crear_usuario):
        objetivo = await self._con_foto(client, crear_usuario, ADMIN, USH)
        admin = await crear_usuario(ADMIN, USH)
        r = await client.delete(_quitar_de(objetivo.id), headers=auth(admin))
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"
        assert await _cantidad_archivos(db) == 1

    async def test_superadmin_sobre_un_administrador(self, client, crear_usuario):
        objetivo = await self._con_foto(client, crear_usuario, ADMIN, RG)
        sa = await crear_usuario(SUPER)
        assert (await client.delete(_quitar_de(objetivo.id), headers=auth(sa))).status_code == 200

    async def test_inexistente_y_no_admin(self, client, crear_usuario):
        sa = await crear_usuario(SUPER)
        assert (await client.delete(_quitar_de(9999), headers=auth(sa))).status_code == 404
        e = await crear_usuario(E)
        assert (await client.delete(_quitar_de(e.id), headers=auth(e))).status_code == 403
