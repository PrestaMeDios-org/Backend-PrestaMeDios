"""SPEC-03 §6.2 y §6.4 · Servicio interno de `files` (tasks B2-03).

Firmas (RN-55), tamaños en el borde (RN-56), nombres (RN-57), la foto (D-11) y la
cuota (RN-58). Los de esta primera parte no usan la base.
"""

import io

import pytest
from PIL import Image
from starlette.datastructures import UploadFile

from app.core.errors import AppError
from app.modules.files import service
from app.modules.files.enums import PropositoArchivo
from tests.files.conftest import imagen, jpeg_con_exif, pdf_minimo

MB = service.MB


def _upload(datos: bytes, nombre: str = "x") -> UploadFile:
    return UploadFile(io.BytesIO(datos), filename=nombre)


class TestDetectarTipo:  # RN-55
    @pytest.mark.parametrize(
        ("datos", "tipo"),
        [
            (imagen("JPEG"), "image/jpeg"),
            (imagen("PNG"), "image/png"),
            (imagen("WEBP"), "image/webp"),
            (pdf_minimo(), "application/pdf"),
        ],
    )
    def test_firmas(self, datos, tipo):
        assert service.detectar_tipo(datos) == tipo

    @pytest.mark.parametrize(
        "datos", [b"", b"GIF89a....", b"RIFF\x00\x00\x00\x00WAVE", b"<html>%PDF-", b"\xff\xd8"]
    )
    def test_desconocidos(self, datos):
        assert service.detectar_tipo(datos) is None

    def test_png_no_es_aval(self):  # AC-82
        with pytest.raises(AppError) as exc:
            service.validar_tipo(imagen("PNG"), PropositoArchivo.AVAL_PRESTAMO)
        assert exc.value.code == "TIPO_ARCHIVO_NO_PERMITIDO"

    def test_pdf_no_es_foto(self):
        with pytest.raises(AppError) as exc:
            service.validar_tipo(pdf_minimo(), PropositoArchivo.FOTO_PERFIL)
        assert exc.value.code == "TIPO_ARCHIVO_NO_PERMITIDO"


class TestLeerConLimite:  # RN-56
    async def test_justo_en_el_maximo(self, limite_mb):
        limite_mb(pdf=1)
        datos = await service.leer_con_limite(
            _upload(b"a" * MB), PropositoArchivo.AVAL_PRESTAMO, content_length=None
        )
        assert len(datos) == MB

    async def test_un_byte_de_mas(self, limite_mb):
        limite_mb(pdf=1)
        with pytest.raises(AppError) as exc:
            await service.leer_con_limite(
                _upload(b"a" * (MB + 1)), PropositoArchivo.AVAL_PRESTAMO, content_length=None
            )
        assert exc.value.code == "ARCHIVO_DEMASIADO_GRANDE"
        assert exc.value.extra == {"max_mb": 1}

    async def test_no_lee_mas_que_el_maximo(self, limite_mb):
        limite_mb(foto=1)
        archivo = _upload(b"a" * (3 * MB))
        with pytest.raises(AppError):
            await service.leer_con_limite(
                archivo, PropositoArchivo.FOTO_PERFIL, content_length=None
            )
        assert archivo.file.tell() == MB + 1

    async def test_content_length_excedido_no_lee(self, limite_mb):
        limite_mb(pdf=1)
        archivo = _upload(b"a")
        with pytest.raises(AppError) as exc:
            await service.leer_con_limite(
                archivo,
                PropositoArchivo.AVAL_PRESTAMO,
                content_length=MB + service.MARGEN_MULTIPART + 1,
            )
        assert exc.value.code == "ARCHIVO_DEMASIADO_GRANDE"
        assert archivo.file.tell() == 0

    async def test_content_length_con_margen_se_acepta(self, limite_mb):
        limite_mb(pdf=1)
        datos = await service.leer_con_limite(
            _upload(b"a" * 10),
            PropositoArchivo.AVAL_PRESTAMO,
            content_length=MB + service.MARGEN_MULTIPART,
        )
        assert datos == b"a" * 10


class TestSanearNombre:  # RN-57
    @pytest.mark.parametrize(
        ("entrada", "salida"),
        [
            ("resolución 056.pdf", "resolución 056.pdf"),
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\ana\\aval.pdf", "aval.pdf"),
            ("ava\x00l\r\n.pdf", "aval.pdf"),
            ("  .oculto.pdf ", "oculto.pdf"),
            ("", "archivo"),
            (None, "archivo"),
            ("../", "archivo"),
        ],
    )
    def test_saneado(self, entrada, salida):
        assert service.sanear_nombre(entrada) == salida

    def test_largo_maximo(self):
        assert len(service.sanear_nombre("a" * 400 + ".pdf")) == 255


class TestProcesarFoto:  # D-11
    async def test_quita_exif_y_reduce(self):  # AC-83 (parte de servicio)
        original = jpeg_con_exif(1200, 800)
        assert Image.open(io.BytesIO(original)).getexif()  # el original sí tiene EXIF

        procesada = await service.procesar_foto(original)
        resultado = Image.open(io.BytesIO(procesada))
        assert resultado.format == "JPEG"
        assert resultado.size == (512, 341)
        assert not resultado.getexif()
        assert b"Exif" not in procesada and b"Camara de prueba" not in procesada

    async def test_respeta_la_orientacion(self):
        procesada = await service.procesar_foto(jpeg_con_exif(1200, 800, orientacion=6))
        assert Image.open(io.BytesIO(procesada)).size == (341, 512)

    async def test_no_agranda(self):
        procesada = await service.procesar_foto(imagen("PNG", (100, 50)))
        assert Image.open(io.BytesIO(procesada)).size == (100, 50)

    async def test_png_con_transparencia_y_webp(self):
        for datos in (imagen("PNG", modo="RGBA"), imagen("WEBP")):
            procesada = await service.procesar_foto(datos)
            assert Image.open(io.BytesIO(procesada)).mode == "RGB"

    async def test_politglota_se_neutraliza(self):
        poliglota = imagen("JPEG") + b"<script>alert(1)</script>"
        procesada = await service.procesar_foto(poliglota)
        assert b"<script>" not in procesada

    @pytest.mark.parametrize(
        "datos", [b"\xff\xd8\xff\xe0basura", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40]
    )
    async def test_imagen_corrupta(self, datos):
        with pytest.raises(AppError) as exc:
            await service.procesar_foto(datos)
        assert exc.value.code == "IMAGEN_INVALIDA"

    async def test_imagen_bomba(self, monkeypatch):
        monkeypatch.setattr(service, "FOTO_MAX_PIXELES", 64 * 64 - 1)
        with pytest.raises(AppError) as exc:
            await service.procesar_foto(imagen("PNG", (64, 64)))
        assert exc.value.code == "IMAGEN_INVALIDA"

    async def test_preparar_foto_nombre_jpg(self):
        _, nombre = await service.preparar_foto(
            _upload(imagen("PNG"), "mi foto.png"), content_length=None
        )
        assert nombre == "mi foto.jpg"


class TestContentDisposition:  # RN-61
    def test_pdf_attachment_con_acentos(self):
        valor = service._content_disposition("application/pdf", 'Resolución "56".pdf')
        assert valor.startswith('attachment; filename="Resoluci_n _56_.pdf"')
        assert "filename*=UTF-8''Resoluci%C3%B3n%20%2256%22.pdf" in valor

    def test_foto_inline(self):
        assert service._content_disposition("image/jpeg", "foto.jpg").startswith("inline;")
