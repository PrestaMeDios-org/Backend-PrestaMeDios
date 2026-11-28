"""SPEC-02 §4 · Integración de seguridad en `inventory` — AC-40…AC-45."""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.modules.inventory.models import Categoria, Equipamiento, UnidadFisica
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/inventory"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE

EQUIPO = {
    "codigo": "CAM-001",
    "nombre": "Cámara Sony A7 III",
    "marca": "Sony",
    "modelo": "ILCE-7M3",
    "categoria_id": "cameras",
}


@pytest.fixture
async def catalogo(db):
    """Cámara con una unidad por sede, trípode sólo en Río Grande y un ítem sin unidades."""
    db.add(Categoria(id="cameras", nombre="Cámaras"))
    await db.flush()
    camara = Equipamiento(codigo="CAM-1", nombre="Cámara", marca="Sony", modelo="A7", categoria_id="cameras")
    camara.unidades = [
        UnidadFisica(numero_serie="S1", codigo_inventario="CAM-U-01", sede=USH),
        UnidadFisica(numero_serie="S2", codigo_inventario="CAM-R-01", sede=RG),
    ]
    tripode = Equipamiento(codigo="TRI-1", nombre="Trípode", marca="Manfrotto", modelo="X", categoria_id="cameras")
    tripode.unidades = [UnidadFisica(numero_serie="S3", codigo_inventario="TRI-R-01", sede=RG)]
    nuevo = Equipamiento(codigo="MIC-1", nombre="Micrófono", marca="Rode", modelo="NTG", categoria_id="cameras")
    db.add_all([camara, tripode, nuevo])
    await db.commit()
    return {"camara": camara.id, "tripode": tripode.id, "nuevo": nuevo.id}


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [("get", "/categorias"), ("post", "/categorias"), ("get", "/equipamiento"),
     ("get", "/equipamiento/1"), ("post", "/equipamiento"), ("post", "/equipamiento/1/unidades"),
     ("get", "/unidades"), ("patch", "/unidades/1/estado"), ("patch", "/unidades/1"),
     ("patch", "/equipamiento/1"), ("patch", "/equipamiento/1/estado"),
     ("get", "/equipamiento/1/disponibilidad?desde=2099-01-01&hasta=2099-01-02")],
)
async def test_exige_sesion(client, db, metodo, ruta):  # AC-40, INV-01, INV-30
    r = await getattr(client, metodo)(f"{B}{ruta}", **({"json": {}} if metodo != "get" else {}))
    assert r.status_code == 401


# El alcance de lectura de estudiantes, docentes y superadmin lo cubre `test_catalogo.py` (INV-02, 03, 07).
class TestAlcanceDeLectura:  # AC-41
    async def test_admin_ve_items_sin_unidades(self, client, catalogo, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        nombres = {i["nombre"] for i in (await client.get(f"{B}/equipamiento", headers=auth(admin))).json()}
        assert nombres == {"Cámara", "Micrófono"}

    async def test_stock_de_admin_local(self, client, catalogo, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, RG)
        codigos = [u["codigo_inventario"] for u in (await client.get(f"{B}/unidades", headers=auth(admin))).json()]
        assert codigos == ["CAM-R-01", "TRI-R-01"]


class TestAltas:  # AC-42, AC-44, AC-45
    async def test_admin_local_asigna_su_sede(self, client, db, crear_usuario):
        db.add(Categoria(id="cameras", nombre="Cámaras"))
        await db.commit()
        admin = await crear_usuario(R.ADMIN_LOCAL, RG)
        r = await client.post(
            f"{B}/equipamiento", headers=auth(admin),
            json={**EQUIPO, "unidades": [{"numero_serie": "A", "codigo_inventario": "CAM-R-09"}]},
        )
        assert r.status_code == 201, r.text
        assert [u["sede"] for u in r.json()["unidades"]] == ["Río Grande"]
        r = await client.post(
            f"{B}/equipamiento/{r.json()['id']}/unidades", headers=auth(admin),
            json={"numero_serie": "B", "codigo_inventario": "CAM-U-09", "sede": "Ushuaia"},
        )
        assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"

    async def test_superadmin_debe_indicar_sede(self, client, catalogo, crear_usuario):
        sa = await crear_usuario(R.SUPERADMIN)
        r = await client.post(
            f"{B}/equipamiento/{catalogo['nuevo']}/unidades", headers=auth(sa),
            json={"numero_serie": "C", "codigo_inventario": "MIC-01"},
        )
        assert r.status_code == 422 and r.json()["code"] == "SEDE_REQUERIDA"
        r = await client.post(
            f"{B}/equipamiento/{catalogo['nuevo']}/unidades", headers=auth(sa),
            json={"numero_serie": "C", "codigo_inventario": "MIC-01", "sede": "Ushuaia"},
        )
        assert r.status_code == 201 and r.json()["sede"] == "Ushuaia"

    # El plazo por defecto (AC-44) lo cubre `test_gestion.py::test_plazo_de_notebooks_desde_config` (INV-13).

    async def test_errores_homogeneos(self, client, catalogo, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        r = await client.post(f"{B}/categorias", json={"id": "cameras", "nombre": "Otra"}, headers=auth(admin))
        assert r.status_code == 409 and r.json()["code"] == "CATEGORIA_DUPLICADA"
        r = await client.post(f"{B}/equipamiento", json={**EQUIPO, "categoria_id": "nada"}, headers=auth(admin))
        assert r.status_code == 422 and r.json()["code"] == "CATEGORIA_INEXISTENTE"
        r = await client.post(
            f"{B}/equipamiento/{catalogo['camara']}/unidades", headers=auth(admin),
            json={"numero_serie": "S1", "codigo_inventario": "OTRO"},
        )
        assert r.status_code == 409 and r.json()["code"] == "INVENTARIO_DUPLICADO"
        r = await client.post(
            f"{B}/equipamiento/999/unidades", headers=auth(admin),
            json={"numero_serie": "Z", "codigo_inventario": "Z"},
        )
        assert r.status_code == 404 and r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"


# AC-43 (roles y alcance en el cambio de estado de unidades) lo cubre `test_gestion.py`:
# `test_no_admins_no_gestionan` (INV-11) y `test_unidad_de_otra_sede` (INV-20).
