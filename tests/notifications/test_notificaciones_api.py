"""SPEC-06 Fase B · API de notificaciones personales (NOV-04) — NTF-01, NTF-17…NTF-20."""

import asyncio

import pytest

from app.core.enums import RolUsuario
from app.modules.notifications.enums import TipoNotificacion
from app.modules.notifications.schemas import ReferenciaNotificacion
from tests.conftest import auth

pytestmark = pytest.mark.integracion

B = "/api/v1/notifications/notificaciones"
T = TipoNotificacion
NORMAL, CRITICA = T.ORDEN_APROBADA, T.ORDEN_CANCELACION_FORZADA


@pytest.fixture
async def ana(crear_usuario):
    return await crear_usuario(RolUsuario.ESTUDIANTE)


# ── NTF-01 · Sesión ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [("get", ""), ("get", "/resumen"), ("patch", "/1/leida"), ("post", "/leer-todas")],
)
async def test_exige_sesion(client, metodo, ruta):  # NTF-01
    r = await getattr(client, metodo)(f"{B}{ruta}")
    assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"


async def test_no_se_pueden_crear_por_la_api(client, ana):  # §5.2
    r = await client.post(B, json={"tipo": "ORDEN_APROBADA"}, headers=auth(ana))
    assert r.status_code == 405


# ── NTF-17 · Sólo las propias (RN-N6) ────────────────────────────────────────


async def test_cada_uno_ve_solo_las_suyas(client, crear_usuario, notificar, ana):  # NTF-17
    otro = await crear_usuario(RolUsuario.ADMIN_LOCAL)
    mia = await notificar(ana)
    ajena = await notificar(otro)

    r = await client.get(B, headers=auth(ana))
    assert r.status_code == 200, r.text
    assert [n["id"] for n in r.json()["items"]] == [mia.id] and r.json()["total"] == 1

    r = await client.patch(f"{B}/{ajena.id}/leida", headers=auth(ana))
    assert r.status_code == 404 and r.json()["code"] == "NOTIFICACION_NO_ENCONTRADA"
    r = await client.patch(f"{B}/999999/leida", headers=auth(ana))
    assert r.status_code == 404


async def test_forma_de_la_respuesta(client, notificar, ana):  # NTF-17
    await notificar(ana, T.ORDEN_HORARIO_AJUSTADO, referencia=ReferenciaNotificacion(modulo="loans", id=7))
    n = (await client.get(B, headers=auth(ana))).json()["items"][0]
    assert n["tipo"] == "ORDEN_HORARIO_AJUSTADO" and n["severidad"] == "CRITICA"
    assert n["titulo"] == "Aprobada con horario modificado"
    assert "<numero_orden>" in n["mensaje"]
    assert n["referencia"] == {"modulo": "loans", "id": 7}
    assert n["leida_en"] is None and n["creada_en"].endswith("-03:00")


async def test_orden_criticas_sin_leer_primero(client, notificar, ana):  # §5.2
    vieja = await notificar(ana)
    critica = await notificar(ana, CRITICA)
    nueva = await notificar(ana)
    ids = [n["id"] for n in (await client.get(B, headers=auth(ana))).json()["items"]]
    assert ids == [critica.id, nueva.id, vieja.id]

    await client.patch(f"{B}/{critica.id}/leida", headers=auth(ana))
    ids = [n["id"] for n in (await client.get(B, headers=auth(ana))).json()["items"]]
    assert ids == [nueva.id, critica.id, vieja.id]  # leída: vuelve al orden por fecha


async def test_solo_no_leidas_y_paginacion(client, notificar, ana):  # §5.2
    for _ in range(3):
        await notificar(ana)
    leida = await notificar(ana)
    await client.patch(f"{B}/{leida.id}/leida", headers=auth(ana))

    r = await client.get(B, params={"solo_no_leidas": True}, headers=auth(ana))
    assert r.json()["total"] == 3 and leida.id not in [n["id"] for n in r.json()["items"]]
    r = await client.get(B, params={"limit": 2, "offset": 2}, headers=auth(ana))
    assert len(r.json()["items"]) == 2 and r.json()["total"] == 4
    r = await client.get(B, params={"limit": 101}, headers=auth(ana))
    assert r.status_code == 422


# ── NTF-18 · Resumen ─────────────────────────────────────────────────────────


async def test_resumen(client, crear_usuario, notificar, ana):  # NTF-18
    otro = await crear_usuario(RolUsuario.DOCENTE)
    await notificar(otro, CRITICA)  # no cuenta para Ana
    r = await client.get(f"{B}/resumen", headers=auth(ana))
    assert r.json() == {"no_leidas": 0, "criticas_no_leidas": 0}

    normal = await notificar(ana)
    critica = await notificar(ana, CRITICA)
    r = await client.get(f"{B}/resumen", headers=auth(ana))
    assert r.json() == {"no_leidas": 2, "criticas_no_leidas": 1}

    await client.patch(f"{B}/{critica.id}/leida", headers=auth(ana))
    await client.patch(f"{B}/{normal.id}/leida", headers=auth(ana))
    r = await client.get(f"{B}/resumen", headers=auth(ana))
    assert r.json() == {"no_leidas": 0, "criticas_no_leidas": 0}


# ── NTF-19 · Marcar como leída (RN-N11) ──────────────────────────────────────


async def test_marcar_es_idempotente(client, notificar, ana):  # NTF-19
    n = await notificar(ana)
    primera = await client.patch(f"{B}/{n.id}/leida", headers=auth(ana))
    assert primera.status_code == 200 and primera.json()["leida_en"] is not None
    await asyncio.sleep(0.05)
    segunda = await client.patch(f"{B}/{n.id}/leida", headers=auth(ana))
    assert segunda.status_code == 200
    assert segunda.json()["leida_en"] == primera.json()["leida_en"]


async def test_marcados_simultaneos_no_se_pisan(client, notificar, ana):  # NTF-19
    n = await notificar(ana)
    respuestas = await asyncio.gather(
        *(client.patch(f"{B}/{n.id}/leida", headers=auth(ana)) for _ in range(5))
    )
    assert {r.status_code for r in respuestas} == {200}
    assert len({r.json()["leida_en"] for r in respuestas}) == 1


# ── NTF-20 · Leer todas (RN-N9, RN-N14) ──────────────────────────────────────


async def test_leer_todas_deja_las_criticas(client, crear_usuario, notificar, ana):  # NTF-20
    otro = await crear_usuario(RolUsuario.DOCENTE)
    await notificar(ana)
    await notificar(ana)
    critica = await notificar(ana, CRITICA)
    await notificar(otro)

    r = await client.post(f"{B}/leer-todas", headers=auth(ana))
    assert r.status_code == 200 and r.json() == {"marcadas": 2}
    r = await client.get(f"{B}/resumen", headers=auth(ana))
    assert r.json() == {"no_leidas": 1, "criticas_no_leidas": 1}
    r = await client.get(B, params={"solo_no_leidas": True}, headers=auth(ana))
    assert [n["id"] for n in r.json()["items"]] == [critica.id]

    r = await client.get(f"{B}/resumen", headers=auth(otro))
    assert r.json()["no_leidas"] == 1  # las de otro usuario no se tocan
    r = await client.post(f"{B}/leer-todas", headers=auth(ana))
    assert r.json() == {"marcadas": 0}
