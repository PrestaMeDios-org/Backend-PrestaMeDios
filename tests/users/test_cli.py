"""T-17 · Bootstrap idempotente del Superadministrador (SPEC-01 §11.1)."""

import pytest
from sqlalchemy import func, select

from app.core.enums import EstadoCuenta, RolUsuario
from app.modules.users.cli import crear_superadmin
from app.modules.users.models import Usuario, UsuarioHistorialEstado
from app.modules.users.schemas import UsuarioAdminCreate

pytestmark = pytest.mark.integracion

DATOS = UsuarioAdminCreate(
    email="Natalia.Ader@untdf.edu.ar",
    password="Laboratorio2026",
    nombre="Natalia",
    apellido="Ader",
    dni="30111222",
    rol=RolUsuario.SUPERADMIN,
    sede=None,
)


async def test_crea_superadmin_activo_y_es_idempotente(db):
    usuario, creado = await crear_superadmin(db, DATOS)
    assert creado is True
    assert usuario.email == "natalia.ader@untdf.edu.ar"
    assert usuario.rol == RolUsuario.SUPERADMIN and usuario.sede is None
    assert usuario.estado == EstadoCuenta.ACTIVO
    assert usuario.password_hash.startswith("$argon2id$")

    otra_vez, creado_2 = await crear_superadmin(db, DATOS)
    assert creado_2 is False and otra_vez.id == usuario.id
    assert await db.scalar(select(func.count()).select_from(Usuario)) == 1
    assert await db.scalar(select(func.count()).select_from(UsuarioHistorialEstado)) == 1


async def test_superadmin_creado_puede_iniciar_sesion(client, db):
    await crear_superadmin(db, DATOS)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "natalia.ader@untdf.edu.ar", "password": "Laboratorio2026"},
    )
    assert r.status_code == 200
    assert r.json()["usuario"]["rol"] == "SUPERADMIN" and r.json()["usuario"]["sede"] is None
