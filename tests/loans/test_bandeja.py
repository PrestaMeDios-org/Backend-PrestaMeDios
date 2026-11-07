"""Bandeja y detalle de órdenes para administradores (SPEC-05 Fase 2; AC-L16, L17, L18, L29).

El detalle (`GET /ordenes/{id}`) lo ven el dueño y los administradores con jurisdicción
sobre la sede de la orden. Para los administradores incluye nombre y apellido del
solicitante, nunca DNI, email ni teléfono (P6). Fuera de alcance, 404.
"""

import pytest

from app.core.enums import RolUsuario, SedeEnum
from app.modules.loans.enums import EstadoOrdenEnum
from app.modules.loans.models import OrdenPedido
from tests.conftest import auth

pytestmark = pytest.mark.integracion

BASE = "/api/v1/loans"
E, D = RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE
A, S = RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
CAMPOS_PRIVADOS = {"dni", "email", "telefono", "password_hash"}


async def _orden(db, usuario, sede=USH, estado=EstadoOrdenEnum.PENDIENTE) -> OrdenPedido:
    """Inserta una orden sin líneas: alcanza para probar alcance y respuesta."""
    orden = OrdenPedido(
        solicitante_id=usuario._cache_auth["id"],  # type: ignore[attr-defined]
        sede=sede,
        estado=estado,
    )
    db.add(orden)
    await db.commit()
    return orden


def _claves(valor) -> set[str]:
    """Todas las claves de un JSON, a cualquier profundidad."""
    if isinstance(valor, dict):
        return set(valor) | {c for v in valor.values() for c in _claves(v)}
    if isinstance(valor, list):
        return {c for v in valor for c in _claves(v)}
    return set()


# ── GET /ordenes/{id} para administradores ──────────────────────────────────


@pytest.mark.parametrize(("rol", "sede_admin"), [(A, USH), (S, None)])
async def test_el_admin_con_jurisdiccion_ve_el_detalle_con_el_solicitante(
    client, db, crear_usuario, rol, sede_admin
):  # AC-L29, PRE-10
    ana = await crear_usuario(E, USH, nombre="Ana", apellido="Pérez")
    orden = await _orden(db, ana)
    admin = await crear_usuario(rol, sede_admin)

    r = await client.get(f"{BASE}/ordenes/{orden.id}", headers=auth(admin))

    assert r.status_code == 200, r.json()
    cuerpo = r.json()
    assert cuerpo["id"] == orden.id
    assert cuerpo["solicitante"] == {
        "id": ana._cache_auth["id"],  # type: ignore[attr-defined]
        "nombre": "Ana",
        "apellido": "Pérez",
    }
    assert not _claves(cuerpo) & CAMPOS_PRIVADOS  # P6


async def test_el_superadmin_ve_ordenes_de_cualquier_sede(client, db, crear_usuario):
    ana = await crear_usuario(E, RG)
    orden = await _orden(db, ana, sede=RG)
    superadmin = await crear_usuario(S)
    r = await client.get(f"{BASE}/ordenes/{orden.id}", headers=auth(superadmin))
    assert r.status_code == 200


async def test_un_admin_de_otra_sede_recibe_404(client, db, crear_usuario):  # AC-L29
    ana = await crear_usuario(E, USH)
    orden = await _orden(db, ana)
    admin_rg = await crear_usuario(A, RG)
    r = await client.get(f"{BASE}/ordenes/{orden.id}", headers=auth(admin_rg))
    assert r.status_code == 404
    assert r.json()["code"] == "ORDEN_NO_ENCONTRADA"


@pytest.mark.parametrize("rol", [E, D])
async def test_otro_estudiante_o_docente_de_la_misma_sede_recibe_404(
    client, db, crear_usuario, rol
):  # AC-L16, RN-L25: la sede compartida no da acceso
    ana = await crear_usuario(E, USH)
    orden = await _orden(db, ana)
    otro = await crear_usuario(rol, USH)
    r = await client.get(f"{BASE}/ordenes/{orden.id}", headers=auth(otro))
    assert r.status_code == 404


async def test_el_dueño_sigue_viendo_su_orden_sin_su_resumen(client, db, crear_usuario):
    ana = await crear_usuario(E, USH)
    orden = await _orden(db, ana, estado=EstadoOrdenEnum.APROBADA)
    r = await client.get(f"{BASE}/ordenes/{orden.id}", headers=auth(ana))
    assert r.status_code == 200
    assert r.json()["solicitante"] is None
