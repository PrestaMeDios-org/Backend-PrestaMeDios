"""MOMENTÁNEO (SPEC-10 M-02, §4.7) · Portada elegible de los comunicados.

Se borra junto con ``app/modules/notifications/portada.py`` (SPEC-10 §1.4).
"""

import io

import pytest
from PIL import Image

from app.core.enums import RolUsuario, SedeEnum
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/notifications/comunicados"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _png(ancho: int = 40, alto: int = 20) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (ancho, alto), (200, 20, 40)).save(buf, format="PNG")
    return buf.getvalue()


async def test_elegir_tema_y_listar(client, crear_usuario, crear_comunicado):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    estudiante = await crear_usuario(R.ESTUDIANTE, USH, email="e@untdf.edu.ar")
    c = await crear_comunicado(USH)

    r = await client.put(f"{B}/{c.id}/portada", json={"tema": "verde"}, headers=auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["tema"] == "verde" and r.json()["tiene_imagen"] is False

    r = await client.get(f"{B}/portadas", params={"ids": str(c.id)}, headers=auth(estudiante))
    assert r.status_code == 200
    assert [(p["comunicado_id"], p["tema"]) for p in r.json()] == [(c.id, "verde")]


async def test_subir_foto_reemplaza_tema_y_se_sirve(client, crear_usuario, crear_comunicado):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    estudiante = await crear_usuario(R.ESTUDIANTE, USH, email="e@untdf.edu.ar")
    c = await crear_comunicado(USH)
    await client.put(f"{B}/{c.id}/portada", json={"tema": "rojo"}, headers=auth(admin))

    r = await client.put(
        f"{B}/{c.id}/portada/imagen",
        files={"archivo": ("portada.png", _png(), "image/png")},
        headers=auth(admin),
    )
    assert r.status_code == 200, r.text
    assert r.json()["tema"] is None and r.json()["tiene_imagen"] is True

    r = await client.get(f"{B}/{c.id}/portada/imagen", headers=auth(estudiante))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"  # se re-codifica como JPEG
    assert r.content.startswith(b"\xff\xd8\xff")


async def test_rechaza_lo_que_no_es_imagen(client, crear_usuario, crear_comunicado):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    c = await crear_comunicado(USH)
    r = await client.put(
        f"{B}/{c.id}/portada/imagen",
        files={"archivo": ("x.png", b"%PDF-1.4 no soy una imagen", "image/png")},
        headers=auth(admin),
    )
    assert r.status_code == 422 and r.json()["code"] == "TIPO_ARCHIVO_NO_PERMITIDO"


async def test_quitar_vuelve_a_automatica(client, crear_usuario, crear_comunicado):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    c = await crear_comunicado(USH)
    await client.put(f"{B}/{c.id}/portada", json={"tema": "azul"}, headers=auth(admin))
    r = await client.delete(f"{B}/{c.id}/portada", headers=auth(admin))
    assert r.status_code == 204
    r = await client.get(f"{B}/portadas", params={"ids": str(c.id)}, headers=auth(admin))
    assert r.json() == []


async def test_mismo_permiso_que_editar(client, crear_usuario, crear_comunicado):
    """Un ADMIN_LOCAL no toca comunicados de otra sede ni globales; un estudiante, ninguno."""
    admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG, email="rg@untdf.edu.ar")
    admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH)
    estudiante = await crear_usuario(R.ESTUDIANTE, USH, email="e@untdf.edu.ar")
    de_ush = await crear_comunicado(USH)
    global_ = await crear_comunicado(None, titulo="Global")

    r = await client.put(f"{B}/{de_ush.id}/portada", json={"tema": "rojo"}, headers=auth(admin_rg))
    assert r.status_code == 404
    r = await client.put(f"{B}/{global_.id}/portada", json={"tema": "rojo"}, headers=auth(admin_ush))
    assert r.status_code == 404
    r = await client.put(f"{B}/{de_ush.id}/portada", json={"tema": "rojo"}, headers=auth(estudiante))
    assert r.status_code == 403


async def test_no_revela_portadas_fuera_de_alcance(client, crear_usuario, crear_comunicado):
    admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH)
    estudiante_rg = await crear_usuario(R.ESTUDIANTE, RG, email="e@untdf.edu.ar")
    estudiante_ush = await crear_usuario(R.ESTUDIANTE, USH, email="e-ush@untdf.edu.ar")
    c = await crear_comunicado(USH)
    # Con foto: así el 404 de la imagen sale por las reglas de lectura y no por falta de foto.
    r = await client.put(
        f"{B}/{c.id}/portada/imagen",
        files={"archivo": ("portada.png", _png(), "image/png")},
        headers=auth(admin_ush),
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"{B}/portadas", params={"ids": str(c.id)}, headers=auth(estudiante_rg))
    assert r.status_code == 200 and r.json() == []
    r = await client.get(f"{B}/{c.id}/portada/imagen", headers=auth(estudiante_rg))
    assert r.status_code == 404 and r.json()["code"] == "COMUNICADO_NO_ENCONTRADO"
    r = await client.get(f"{B}/{c.id}/portada/imagen", headers=auth(estudiante_ush))
    assert r.status_code == 200


@pytest.mark.parametrize("ids", ["a,b", "99999999999", "0", "-3", "1,2147483648"])
async def test_ids_fuera_de_rango(client, crear_usuario, ids):
    """Un id que no es entero o no entra en `integer` no llega a PostgreSQL: 422, no 500 (revisión del PR #39)."""
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.get(f"{B}/portadas", params={"ids": ids}, headers=auth(admin))
    assert r.status_code == 422 and r.json()["code"] == "IDS_INVALIDOS"


async def test_varios_ids_con_las_reglas_de_lectura(client, crear_usuario, crear_comunicado):
    """En una sola consulta: la sede propia y los globales sí; otra sede e ids inexistentes, no."""
    superadmin = await crear_usuario(R.SUPERADMIN, None, email="sa@untdf.edu.ar")
    estudiante = await crear_usuario(R.ESTUDIANTE, USH, email="e@untdf.edu.ar")
    de_ush = await crear_comunicado(USH)
    de_rg = await crear_comunicado(RG, titulo="De Río Grande")
    global_ = await crear_comunicado(None, titulo="Global")
    sin_portada = await crear_comunicado(USH, titulo="Sin portada")
    vencido = await crear_comunicado(USH, titulo="Vencido", vencido=True)
    for c, tema in ((de_ush, "azul"), (de_rg, "verde"), (global_, "rojo"), (vencido, "amarillo")):
        r = await client.put(f"{B}/{c.id}/portada", json={"tema": tema}, headers=auth(superadmin))
        assert r.status_code == 200, r.text

    ids = f"{de_ush.id},{de_rg.id},{global_.id},{sin_portada.id},{vencido.id},999999"
    r = await client.get(f"{B}/portadas", params={"ids": ids}, headers=auth(estudiante))
    assert r.status_code == 200
    # El estudiante no ve otra sede ni lo vencido (RN-N3), igual que en `obtener_comunicado`.
    assert sorted((p["comunicado_id"], p["tema"]) for p in r.json()) == sorted(
        [(de_ush.id, "azul"), (global_.id, "rojo")]
    )
    r = await client.get(f"{B}/portadas", params={"ids": ids}, headers=auth(superadmin))
    assert {p["comunicado_id"] for p in r.json()} == {de_ush.id, de_rg.id, global_.id, vencido.id}
