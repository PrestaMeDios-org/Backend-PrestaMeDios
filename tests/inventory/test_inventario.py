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
    return {"camara": camara.id, "tripode": tripode.id, "nuevo": nuevo.id,
            "unidad_rg": camara.unidades[1].id}


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [("get", "/categorias"), ("post", "/categorias"), ("get", "/equipamiento"),
     ("get", "/equipamiento/1"), ("post", "/equipamiento"), ("post", "/equipamiento/1/unidades"),
     ("get", "/unidades"), ("patch", "/unidades/1/estado")],
)
async def test_exige_sesion(client, db, metodo, ruta):  # AC-40
    r = await getattr(client, metodo)(f"{B}{ruta}", **({"json": {}} if metodo != "get" else {}))
    assert r.status_code == 401


class TestAlcanceDeLectura:  # AC-41
    async def test_estudiante_ve_solo_su_sede(self, client, catalogo, crear_usuario):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        items = (await client.get(f"{B}/equipamiento", headers=auth(est))).json()
        assert [i["nombre"] for i in items] == ["Cámara"]
        assert [u["sede"] for u in items[0]["unidades"]] == ["Ushuaia"]
        assert items[0]["cantidad_total"] == 1

    async def test_admin_ve_items_sin_unidades(self, client, catalogo, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        nombres = {i["nombre"] for i in (await client.get(f"{B}/equipamiento", headers=auth(admin))).json()}
        assert nombres == {"Cámara", "Micrófono"}

    async def test_superadmin_y_filtro_por_sede(self, client, catalogo, crear_usuario):
        sa = await crear_usuario(R.SUPERADMIN)
        todos = (await client.get(f"{B}/equipamiento", headers=auth(sa))).json()
        assert {i["nombre"] for i in todos} == {"Cámara", "Trípode", "Micrófono"}
        rg = (await client.get(f"{B}/equipamiento", params={"sede": "Río Grande"}, headers=auth(sa))).json()
        camara = next(i for i in rg if i["nombre"] == "Cámara")
        assert [u["sede"] for u in camara["unidades"]] == ["Río Grande"]

    async def test_otra_sede_y_unidades(self, client, catalogo, crear_usuario):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        r = await client.get(f"{B}/equipamiento", params={"sede": "Río Grande"}, headers=auth(est))
        assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"
        r = await client.get(f"{B}/unidades", headers=auth(est))
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"

    async def test_detalle(self, client, catalogo, crear_usuario):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        r = await client.get(f"{B}/equipamiento/{catalogo['tripode']}", headers=auth(est))
        assert r.status_code == 404 and r.json()["code"] == "EQUIPAMIENTO_NO_ENCONTRADO"
        r = await client.get(f"{B}/equipamiento/{catalogo['camara']}", headers=auth(est))
        assert r.status_code == 200 and len(r.json()["unidades"]) == 1

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

    async def test_plazo_por_defecto_desde_config(self, client, db, crear_usuario, set_parametro):
        db.add(Categoria(id="cameras", nombre="Cámaras"))
        await db.commit()
        await set_parametro("prestamo.general.max_dias", 3)
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        r = await client.post(f"{B}/equipamiento", json=EQUIPO, headers=auth(admin))
        assert r.status_code == 201 and r.json()["max_dias_prestamo"] == 3
        r = await client.post(
            f"{B}/equipamiento", json={**EQUIPO, "codigo": "CAM-2", "max_dias_prestamo": 7}, headers=auth(admin)
        )
        assert r.json()["max_dias_prestamo"] == 7

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

    @pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
    async def test_no_admins_no_escriben(self, client, db, crear_usuario, rol):
        u = await crear_usuario(rol, USH)
        r = await client.post(f"{B}/categorias", json={"id": "x", "nombre": "X"}, headers=auth(u))
        assert r.status_code == 403


class TestEstadoDeUnidades:  # AC-43
    async def test_alcance(self, client, catalogo, crear_usuario):
        admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH)
        r = await client.patch(
            f"{B}/unidades/{catalogo['unidad_rg']}/estado", json={"estado": "mantenimiento"}, headers=auth(admin_ush)
        )
        assert r.status_code == 404 and r.json()["code"] == "UNIDAD_NO_ENCONTRADA"
        admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG)
        r = await client.patch(
            f"{B}/unidades/{catalogo['unidad_rg']}/estado", json={"estado": "mantenimiento"}, headers=auth(admin_rg)
        )
        assert r.status_code == 200 and r.json()["estado"] == "mantenimiento"

    async def test_docente_no_cambia_estado(self, client, catalogo, crear_usuario):
        doc = await crear_usuario(R.DOCENTE, RG)
        r = await client.patch(
            f"{B}/unidades/{catalogo['unidad_rg']}/estado", json={"estado": "mantenimiento"}, headers=auth(doc)
        )
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"
