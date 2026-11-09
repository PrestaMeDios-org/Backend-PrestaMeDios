"""Helpers de `files` (SPEC-03 §9.3): generadores de imágenes y PDF, y subida del aval."""

import io

import httpx
import pytest
from PIL import ExifTags, Image

from tests.conftest import auth

ARCHIVOS = "/api/v1/files/archivos"
FOTO = "/api/v1/auth/me/foto"


def pdf_minimo(relleno: int = 0) -> bytes:
    """Un PDF de una página válido; ``relleno`` agrega bytes en un comentario."""
    cuerpo = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    )
    return cuerpo + b"%" + b"x" * relleno + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def jpeg_con_exif(ancho: int = 1200, alto: int = 800, *, orientacion: int | None = None) -> bytes:
    """JPEG con EXIF de cámara y de ubicación (GPS), como el de un celular."""
    imagen = Image.new("RGB", (ancho, alto), (200, 30, 30))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "Camara de prueba"
    if orientacion is not None:
        exif[ExifTags.Base.Orientation] = orientacion
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "S"
    gps[ExifTags.GPS.GPSLatitude] = (54.0, 48.0, 0.0)
    gps[ExifTags.GPS.GPSLongitudeRef] = "W"
    gps[ExifTags.GPS.GPSLongitude] = (68.0, 18.0, 0.0)
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", exif=exif)
    return salida.getvalue()


def imagen(formato: str, tamano: tuple[int, int] = (64, 64), modo: str = "RGB") -> bytes:
    salida = io.BytesIO()
    Image.new(modo, tamano, (10, 120, 200) if modo == "RGB" else (10, 120, 200, 0)).save(
        salida, format=formato
    )
    return salida.getvalue()


async def subir_aval(
    client: httpx.AsyncClient,
    usuario,
    datos: bytes | None = None,
    *,
    nombre: str = "resolucion.pdf",
    proposito: str = "AVAL_PRESTAMO",
    content_type: str = "application/pdf",
) -> httpx.Response:
    return await client.post(
        ARCHIVOS,
        files={"archivo": (nombre, datos if datos is not None else pdf_minimo(), content_type)},
        data={"proposito": proposito},
        headers=auth(usuario),
    )


async def subir_foto(
    client: httpx.AsyncClient, usuario, datos: bytes, *, nombre: str = "foto.jpg"
) -> httpx.Response:
    return await client.put(
        FOTO, files={"archivo": (nombre, datos, "image/jpeg")}, headers=auth(usuario)
    )


@pytest.fixture
def limite_mb(monkeypatch):
    """Baja los máximos de tamaño para probar los bordes sin subir 10 MB."""
    from app.core.settings import get_settings

    def _fijar(*, foto: int | None = None, pdf: int | None = None) -> None:
        settings = get_settings()
        if foto is not None:
            monkeypatch.setattr(settings, "archivo_foto_max_mb", foto)
        if pdf is not None:
            monkeypatch.setattr(settings, "archivo_pdf_max_mb", pdf)

    return _fijar
