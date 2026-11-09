"""SPEC-03 §6.3 · Subida del aval y descarga — AC-81, AC-82, AC-85, AC-87, EC-43, EC-44, EC-48."""

import uuid

import pytest
from sqlalchemy import select, update

from app.core.enums import RolUsuario, SedeEnum
from app.modules.files.models import Archivo, ArchivoDatos
from app.modules.users.models import Usuario
from tests.conftest import auth
from tests.files.conftest import ARCHIVOS, imagen, jpeg_con_exif, pdf_minimo, subir_aval, subir_foto

pytestmark = pytest.mark.integracion

E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
ADMIN, SUPER = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _contenido(archivo_id) -> str:
    return f"{ARCHIVOS}/{archivo_id}/contenido"


class TestSubirAval:
    @pytest.mark.parametrize("rol", [E, D])
    async def test_estudiante_y_docente(self, client, db, crear_usuario, rol):  # AC-81, EC-47
        u = await crear_usuario(rol, USH)
        uid = u.id
        pdf = pdf_minimo(100)
        r = await subir_aval(client, u, pdf, nombre="Resolución 056.pdf")
        assert r.status_code == 201, r.text
        cuerpo = r.json()
        assert uuid.UUID(cuerpo["id"]).version == 4
        assert cuerpo["proposito"] == "AVAL_PRESTAMO"
        assert cuerpo["tipo_mime"] == "application/pdf"
        assert cuerpo["tamano_bytes"] == len(pdf)
        assert len(cuerpo["sha256"]) == 64
        assert cuerpo["nombre_original"] == "Resolución 056.pdf"

        archivo = await db.get(Archivo, uuid.UUID(cuerpo["id"]))
        assert archivo.vinculado_en is None
        assert archivo.propietario_id == uid and archivo.sede == USH
        datos = await db.scalar(
            select(ArchivoDatos.datos).where(ArchivoDatos.archivo_id == archivo.id)
        )
        assert datos == pdf

    async def test_png_disfrazado_de_pdf(self, client, crear_usuario):  # AC-82, RN-55
        u = await crear_usuario(E)
        r = await subir_aval(client, u, imagen("PNG"), nombre="aval.pdf")
        assert r.status_code == 422 and r.json()["code"] == "TIPO_ARCHIVO_NO_PERMITIDO"

    async def test_content_type_del_cliente_se_ignora(self, client, crear_usuario):  # RN-55
        u = await crear_usuario(E)
        r = await subir_aval(client, u, pdf_minimo(), nombre="aval.png", content_type="image/png")
        assert r.status_code == 201 and r.json()["tipo_mime"] == "application/pdf"

    async def test_demasiado_grande(self, client, crear_usuario, limite_mb):  # AC-82, RN-56
        limite_mb(pdf=1)
        u = await crear_usuario(E)
        r = await subir_aval(client, u, pdf_minimo(1024 * 1024))
        assert r.status_code == 422 and r.json()["code"] == "ARCHIVO_DEMASIADO_GRANDE"

    @pytest.mark.parametrize("proposito", ["FOTO_PERFIL", "OTRO", "aval_prestamo"])
    async def test_proposito_invalido(self, client, crear_usuario, proposito):  # AC-82
        u = await crear_usuario(E)
        r = await subir_aval(client, u, proposito=proposito)
        assert r.status_code == 422 and r.json()["code"] == "PROPOSITO_INVALIDO"

    @pytest.mark.parametrize("rol", [ADMIN, SUPER])
    async def test_administradores_no_suben(self, client, crear_usuario, rol):  # EC-43
        u = await crear_usuario(rol, USH)
        r = await subir_aval(client, u)
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"

    async def test_sin_sesion(self, client):
        r = await client.post(
            ARCHIVOS,
            files={"archivo": ("a.pdf", pdf_minimo(), "application/pdf")},
            data={"proposito": "AVAL_PRESTAMO"},
        )
        assert r.status_code == 401

    async def test_sexto_pendiente(self, client, db, crear_usuario):  # AC-87, RN-58
        u = await crear_usuario(E)
        uid = u.id
        for _ in range(5):
            assert (await subir_aval(client, u)).status_code == 201
        r = await subir_aval(client, u)
        assert r.status_code == 409 and r.json()["code"] == "DEMASIADOS_ARCHIVOS_PENDIENTES"

        # Vincular uno libera un lugar; la cuota es por usuario.
        await db.execute(
            update(Archivo)
            .where(Archivo.id == select(Archivo.id).where(Archivo.propietario_id == uid).limit(1)
                   .scalar_subquery())
            .values(vinculado_en=Archivo.created_at)
        )
        await db.commit()
        assert (await subir_aval(client, u)).status_code == 201
        otro = await crear_usuario(E)
        assert (await subir_aval(client, otro)).status_code == 201


async def _aval_de(client, propietario) -> str:
    r = await subir_aval(client, propietario)
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestDescargaAval:  # AC-85, RN-60, D-18
    @pytest.mark.parametrize(
        ("rol_dueno", "lector", "esperado"),
        [
            (E, "dueno", 200),
            (D, "dueno", 200),
            (E, (ADMIN, USH), 200),
            (D, (ADMIN, USH), 200),
            (E, (ADMIN, RG), 404),
            (E, (E, USH), 404),
            (E, (D, USH), 404),  # el docente de la asignatura tampoco (EC-48)
            (D, (D, USH), 404),
            (E, (SUPER, None), 200),
        ],
    )
    async def test_matriz(self, client, crear_usuario, rol_dueno, lector, esperado):
        dueno = await crear_usuario(rol_dueno, USH)
        archivo_id = await _aval_de(client, dueno)
        quien = dueno if lector == "dueno" else await crear_usuario(*lector)
        r = await client.get(_contenido(archivo_id), headers=auth(quien))
        assert r.status_code == esperado, r.text
        if esperado == 404:
            assert r.json()["code"] == "ARCHIVO_NO_ENCONTRADO"

    async def test_encabezados(self, client, crear_usuario):  # RN-61
        dueno = await crear_usuario(E)
        pdf = pdf_minimo(10)
        r = await subir_aval(client, dueno, pdf, nombre="Resolución.pdf")
        r = await client.get(_contenido(r.json()["id"]), headers=auth(dueno))
        assert r.status_code == 200 and r.content == pdf
        assert r.headers["content-type"] == "application/pdf"
        assert r.headers["content-disposition"].startswith("attachment;")
        assert "filename*=UTF-8''Resoluci%C3%B3n.pdf" in r.headers["content-disposition"]
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert r.headers["cache-control"] == "private, no-store"

    async def test_sigue_en_la_sede_donde_se_subio(self, client, db, crear_usuario):  # EC-44
        dueno = await crear_usuario(E, USH)
        uid = dueno.id
        archivo_id = await _aval_de(client, dueno)
        await db.execute(update(Usuario).where(Usuario.id == uid).values(sede=RG))
        await db.commit()
        admin_ush = await crear_usuario(ADMIN, USH)
        admin_rg = await crear_usuario(ADMIN, RG)
        assert (await client.get(_contenido(archivo_id), headers=auth(admin_ush))).status_code == 200
        assert (await client.get(_contenido(archivo_id), headers=auth(admin_rg))).status_code == 404

    async def test_inexistente(self, client, crear_usuario):
        u = await crear_usuario(SUPER)
        r = await client.get(_contenido(uuid.uuid4()), headers=auth(u))
        assert r.status_code == 404 and r.json()["code"] == "ARCHIVO_NO_ENCONTRADO"

    async def test_sin_sesion(self, client, crear_usuario):
        archivo_id = await _aval_de(client, await crear_usuario(E))
        assert (await client.get(_contenido(archivo_id))).status_code == 401


class TestDescargaFoto:  # AC-85, RN-60
    async def _foto_de(self, client, dueno) -> str:
        r = await subir_foto(client, dueno, jpeg_con_exif(64, 64))
        assert r.status_code == 200, r.text
        return r.json()["foto_id"]

    @pytest.mark.parametrize(
        ("lector", "esperado"),
        [("dueno", 200), ((ADMIN, USH), 200), ((ADMIN, RG), 404), ((E, USH), 404),
         ((D, USH), 404), ((SUPER, None), 200)],
    )
    async def test_matriz(self, client, crear_usuario, lector, esperado):
        dueno = await crear_usuario(E, USH)
        foto_id = await self._foto_de(client, dueno)
        quien = dueno if lector == "dueno" else await crear_usuario(*lector)
        r = await client.get(_contenido(foto_id), headers=auth(quien))
        assert r.status_code == esperado
        if esperado == 200:
            assert r.headers["content-type"] == "image/jpeg"
            assert r.headers["content-disposition"].startswith("inline;")
            assert r.headers["x-content-type-options"] == "nosniff"

    async def test_sigue_la_sede_actual_del_dueno(self, client, db, crear_usuario):
        dueno = await crear_usuario(E, USH)
        uid = dueno.id
        foto_id = await self._foto_de(client, dueno)
        await db.execute(update(Usuario).where(Usuario.id == uid).values(sede=RG))
        await db.commit()
        admin_ush = await crear_usuario(ADMIN, USH)
        admin_rg = await crear_usuario(ADMIN, RG)
        assert (await client.get(_contenido(foto_id), headers=auth(admin_ush))).status_code == 404
        assert (await client.get(_contenido(foto_id), headers=auth(admin_rg))).status_code == 200
