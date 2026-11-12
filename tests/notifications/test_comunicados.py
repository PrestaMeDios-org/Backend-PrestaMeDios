"""SPEC-06 Fase A · Comunicados (NOV-02, GLO-01) — NTF-01…NTF-03, NTF-05…NTF-12."""

from datetime import datetime, timedelta

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.core.settings import ahora_lab
from app.modules.notifications.enums import EstadoComunicado
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/notifications/comunicados"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
ARCH = EstadoComunicado.ARCHIVADO

AVISO = {"titulo": "Cierre por feriado", "contenido": "El lunes el laboratorio está cerrado."}


def _futuro(dias: int = 3) -> str:
    return (ahora_lab() + timedelta(days=dias)).isoformat()


def _titulos(r) -> set[str]:
    assert r.status_code == 200, r.text
    return {c["titulo"] for c in r.json()["items"]}


@pytest.fixture
async def tres_comunicados(crear_comunicado):
    """Uno de Ushuaia, uno de Río Grande y uno global."""
    await crear_comunicado(USH, titulo="Ushuaia")
    await crear_comunicado(RG, titulo="Río Grande")
    await crear_comunicado(None, titulo="Global")


# ── NTF-01 · Sesión ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("get", "", None),
        ("get", "/1", None),
        ("post", "", AVISO),
        ("patch", "/1", {"titulo": "Otro"}),
        ("patch", "/1/estado", {"estado": "ARCHIVADO"}),
    ],
)
async def test_exige_sesion(client, metodo, ruta, cuerpo):  # NTF-01
    kwargs = {"json": cuerpo} if cuerpo is not None else {}
    r = await getattr(client, metodo)(f"{B}{ruta}", **kwargs)
    assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"


# ── NTF-02, NTF-03 · Alcance al publicar (RN-N2) ─────────────────────────────


async def test_admin_local_publica_en_su_sede(client, crear_usuario):  # NTF-02
    admin = await crear_usuario(R.ADMIN_LOCAL, USH, nombre="Natalia", apellido="Ader")
    r = await client.post(B, json=AVISO, headers=auth(admin))
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["sede"] == "Ushuaia" and cuerpo["es_global"] is False
    assert cuerpo["estado"] == "PUBLICADO" and cuerpo["vigente"] is True
    assert cuerpo["autor"] == {"id": admin._cache_auth["id"], "nombre": "Natalia", "apellido": "Ader"}


async def test_admin_local_puede_repetir_su_propia_sede(client, crear_usuario):  # NTF-02
    admin = await crear_usuario(R.ADMIN_LOCAL, RG)
    r = await client.post(B, json={**AVISO, "sede": "Río Grande"}, headers=auth(admin))
    assert r.status_code == 201 and r.json()["sede"] == "Río Grande"


@pytest.mark.parametrize(
    "extra", [{"sede": "Río Grande"}, {"es_global": True}], ids=["otra-sede", "global"]
)
async def test_admin_local_no_publica_fuera_de_su_sede(client, crear_usuario, extra):  # NTF-02
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.post(B, json={**AVISO, **extra}, headers=auth(admin))
    assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"


async def test_superadmin_tiene_que_elegir_alcance(client, crear_usuario):  # NTF-03
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.post(B, json=AVISO, headers=auth(sa))
    assert r.status_code == 422 and r.json()["code"] == "SEDE_REQUERIDA"


async def test_superadmin_no_puede_indicar_sede_y_global(client, crear_usuario):  # NTF-03
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.post(B, json={**AVISO, "sede": "Ushuaia", "es_global": True}, headers=auth(sa))
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("extra", "sede", "es_global"),
    [({"sede": "Río Grande"}, "Río Grande", False), ({"es_global": True}, None, True)],
    ids=["sede", "global"],
)
async def test_superadmin_publica_segun_lo_indicado(
    client, crear_usuario, extra, sede, es_global
):  # NTF-03
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.post(B, json={**AVISO, **extra}, headers=auth(sa))
    assert r.status_code == 201, r.text
    assert r.json()["sede"] == sede and r.json()["es_global"] is es_global


@pytest.mark.parametrize(
    "cambio",
    [{"titulo": "ab"}, {"contenido": ""}, {"contenido": "x" * 5001}, {"otro": 1}],
    ids=["titulo-corto", "contenido-vacio", "contenido-largo", "campo-desconocido"],
)
async def test_valida_el_cuerpo_del_alta(client, crear_usuario, cambio):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.post(B, json={**AVISO, **cambio}, headers=auth(admin))
    assert r.status_code == 422


# ── NTF-05…NTF-07 · Lectura (RN-N3, RN-N4) ───────────────────────────────────


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
async def test_ve_su_sede_y_los_globales(client, crear_usuario, tres_comunicados, rol):  # NTF-05
    u = await crear_usuario(rol, USH)
    r = await client.get(B, headers=auth(u))
    assert _titulos(r) == {"Ushuaia", "Global"}
    assert r.json()["total"] == 2


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE, R.ADMIN_LOCAL])
async def test_no_puede_pedir_otra_sede(client, crear_usuario, rol):  # NTF-05
    u = await crear_usuario(rol, USH)
    r = await client.get(B, params={"sede": "Río Grande"}, headers=auth(u))
    assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"


async def test_vencidos_y_archivados_no_se_ven_para_estudiantes(
    client, crear_usuario, crear_comunicado
):  # NTF-06
    await crear_comunicado(USH, titulo="Vigente")
    vencido = await crear_comunicado(USH, titulo="Vencido", vencido=True)
    archivado = await crear_comunicado(USH, titulo="Archivado", estado=ARCH)
    u = await crear_usuario(R.ESTUDIANTE, USH)

    r = await client.get(B, params={"incluir_archivados": True}, headers=auth(u))
    assert _titulos(r) == {"Vigente"}  # el flag se ignora para no administradores
    for c in (vencido, archivado):
        r = await client.get(f"{B}/{c.id}", headers=auth(u))
        assert r.status_code == 404 and r.json()["code"] == "COMUNICADO_NO_ENCONTRADO"


async def test_admin_ve_vencidos_y_pide_los_archivados(
    client, crear_usuario, crear_comunicado
):  # NTF-06
    await crear_comunicado(USH, titulo="Vigente")
    await crear_comunicado(USH, titulo="Vencido", vencido=True)
    archivado = await crear_comunicado(USH, titulo="Archivado", estado=ARCH)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)

    r = await client.get(B, headers=auth(admin))
    assert _titulos(r) == {"Vigente", "Vencido"}
    vigencia = {c["titulo"]: c["vigente"] for c in r.json()["items"]}
    assert vigencia == {"Vigente": True, "Vencido": False}

    r = await client.get(B, params={"incluir_archivados": True}, headers=auth(admin))
    assert _titulos(r) == {"Vigente", "Vencido", "Archivado"}
    r = await client.get(f"{B}/{archivado.id}", headers=auth(admin))
    assert r.status_code == 200 and r.json()["vigente"] is False


async def test_superadmin_ve_todo_o_filtra_por_sede(
    client, crear_usuario, tres_comunicados
):  # NTF-07
    sa = await crear_usuario(R.SUPERADMIN)
    assert _titulos(await client.get(B, headers=auth(sa))) == {"Ushuaia", "Río Grande", "Global"}
    r = await client.get(B, params={"sede": "Río Grande"}, headers=auth(sa))
    assert _titulos(r) == {"Río Grande", "Global"}


async def test_detalle_de_otra_sede_es_404(client, crear_usuario, crear_comunicado):  # NTF-05
    otro = await crear_comunicado(RG)
    u = await crear_usuario(R.ESTUDIANTE, USH)
    r = await client.get(f"{B}/{otro.id}", headers=auth(u))
    assert r.status_code == 404


async def test_orden_y_paginacion(client, crear_usuario, crear_comunicado):
    for i in range(3):
        await crear_comunicado(USH, titulo=f"C{i}", publicado_hace=timedelta(hours=10 - i))
    u = await crear_usuario(R.ESTUDIANTE, USH)
    r = await client.get(B, params={"limit": 2}, headers=auth(u))
    assert [c["titulo"] for c in r.json()["items"]] == ["C2", "C1"]
    assert r.json()["total"] == 3
    r = await client.get(B, params={"limit": 2, "offset": 2}, headers=auth(u))
    assert [c["titulo"] for c in r.json()["items"]] == ["C0"]
    r = await client.get(B, params={"limit": 101}, headers=auth(u))
    assert r.status_code == 422


# ── NTF-08 · Roles sin permiso ───────────────────────────────────────────────


@pytest.mark.parametrize("rol", [R.ESTUDIANTE, R.DOCENTE])
@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("post", "", AVISO),
        ("patch", "/1", {"titulo": "Otro"}),
        ("patch", "/1/estado", {"estado": "ARCHIVADO"}),
    ],
)
async def test_no_admins_no_escriben(client, crear_usuario, rol, metodo, ruta, cuerpo):  # NTF-08
    u = await crear_usuario(rol, USH)
    r = await getattr(client, metodo)(f"{B}{ruta}", json=cuerpo, headers=auth(u))
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


# ── NTF-09…NTF-11 · Edición y estado (RN-N4, RN-N5) ──────────────────────────


async def test_admin_local_edita_uno_de_su_sede_de_otro_autor(
    client, crear_usuario, crear_comunicado
):  # NTF-09
    autor = await crear_usuario(R.ADMIN_LOCAL, USH)
    c = await crear_comunicado(USH, autor=autor)
    otro_admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(
        f"{B}/{c.id}", json={"titulo": "Nuevo título"}, headers=auth(otro_admin)
    )
    assert r.status_code == 200, r.text
    assert r.json()["titulo"] == "Nuevo título"
    assert r.json()["autor"]["id"] == autor._cache_auth["id"]  # el autor no cambia
    publicado, actualizado = (
        datetime.fromisoformat(r.json()[k]) for k in ("publicado_en", "actualizado_en")
    )
    assert actualizado > publicado
    assert r.json()["publicado_en"].endswith("-03:00")  # zona del laboratorio


@pytest.mark.parametrize("sede", [RG, None], ids=["otra-sede", "global"])
async def test_admin_local_no_edita_fuera_de_su_alcance(
    client, crear_usuario, crear_comunicado, sede
):  # NTF-09
    c = await crear_comunicado(sede)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    for ruta, cuerpo in (("", {"titulo": "X" * 5}), ("/estado", {"estado": "ARCHIVADO"})):
        r = await client.patch(f"{B}/{c.id}{ruta}", json=cuerpo, headers=auth(admin))
        assert r.status_code == 404 and r.json()["code"] == "COMUNICADO_NO_ENCONTRADO"


async def test_superadmin_edita_uno_global(client, crear_usuario, crear_comunicado):  # NTF-09
    c = await crear_comunicado(None)
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.patch(f"{B}/{c.id}", json={"contenido": "Nuevo"}, headers=auth(sa))
    assert r.status_code == 200 and r.json()["contenido"] == "Nuevo"


@pytest.mark.parametrize(
    "cuerpo",
    [{}, {"sede": "Río Grande"}, {"es_global": True}, {"autor_id": 1}, {"titulo": None}],
    ids=["vacio", "sede", "es_global", "desconocido", "titulo-nulo"],
)
async def test_edicion_rechaza_campos_no_editables(
    client, crear_usuario, crear_comunicado, cuerpo
):  # NTF-10
    c = await crear_comunicado(USH)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/{c.id}", json=cuerpo, headers=auth(admin))
    assert r.status_code == 422


async def test_archivar_y_reactivar_es_idempotente(
    client, crear_usuario, crear_comunicado
):  # NTF-09
    c = await crear_comunicado(USH)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    for estado in ("ARCHIVADO", "ARCHIVADO", "PUBLICADO", "PUBLICADO"):
        r = await client.patch(f"{B}/{c.id}/estado", json={"estado": estado}, headers=auth(admin))
        assert r.status_code == 200 and r.json()["estado"] == estado


async def test_vencimiento_en_el_pasado_es_422(client, crear_usuario, crear_comunicado):  # NTF-11
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    pasado = (ahora_lab() - timedelta(minutes=1)).isoformat()
    r = await client.post(B, json={**AVISO, "vence_en": pasado}, headers=auth(admin))
    assert r.status_code == 422 and r.json()["code"] == "VENCIMIENTO_INVALIDO"

    c = await crear_comunicado(USH)
    r = await client.patch(f"{B}/{c.id}", json={"vence_en": pasado}, headers=auth(admin))
    assert r.status_code == 422 and r.json()["code"] == "VENCIMIENTO_INVALIDO"


async def test_vencimiento_sin_zona_horaria_es_422(client, crear_usuario):  # NTF-11
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.post(B, json={**AVISO, "vence_en": "2099-01-01T00:00:00"}, headers=auth(admin))
    assert r.status_code == 422


async def test_poner_y_quitar_el_vencimiento(client, crear_usuario, crear_comunicado):  # NTF-11
    c = await crear_comunicado(USH)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.patch(f"{B}/{c.id}", json={"vence_en": _futuro()}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["vence_en"] is not None
    r = await client.patch(f"{B}/{c.id}", json={"vence_en": None}, headers=auth(admin))
    assert r.status_code == 200 and r.json()["vence_en"] is None


# ── NTF-12 · Privacidad del autor (P6) ───────────────────────────────────────


async def test_autor_solo_con_datos_publicos(client, crear_usuario, crear_comunicado):  # NTF-12
    autor = await crear_usuario(R.ADMIN_LOCAL, USH)
    await crear_comunicado(USH, autor=autor)
    await crear_comunicado(USH, titulo="Sin autor")
    u = await crear_usuario(R.ESTUDIANTE, USH)
    items = (await client.get(B, headers=auth(u))).json()["items"]
    autores = {c["titulo"]: c["autor"] for c in items}
    assert set(autores["Aviso"]) == {"id", "nombre", "apellido"}
    assert autores["Sin autor"] is None
