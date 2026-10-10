"""SPEC-02 UC-12 · Edición administrativa de perfiles (USR-04) — AC-49."""

import pytest
from sqlalchemy import select

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.modules.users.models import Usuario, UsuarioHistorialCambios
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.integracion

R, E = RolUsuario, EstadoCuenta
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


async def _editar(client, actor, objetivo_id, **payload):
    return await client.patch(f"/api/v1/users/{objetivo_id}", json=payload, headers=auth(actor))


async def test_admin_local_edita_datos(client, db, crear_usuario):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    est = await crear_usuario(R.ESTUDIANTE, USH, nombre="Ana")
    est_id = est.id
    r = await _editar(client, admin, est_id, nombre="Analía", telefono="+54 2901 444555")
    assert r.status_code == 200, r.text
    assert r.json()["nombre"] == "Analía"
    hist = (
        await db.scalars(select(UsuarioHistorialCambios).where(UsuarioHistorialCambios.usuario_id == est_id))
    ).all()
    assert hist[0].cambios["nombre"] == ["Ana", "Analía"] and hist[0].actor_id == admin.id


async def test_admin_local_cambia_rol_y_revoca_sesion(client, crear_usuario):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    est = await crear_usuario(R.ESTUDIANTE, USH)
    sesion = auth(est)
    r = await _editar(client, admin, est.id, rol="DOCENTE")
    assert r.status_code == 200 and r.json()["rol"] == "DOCENTE"
    assert (await client.get("/api/v1/auth/me", headers=sesion)).json()["code"] == "TOKEN_REVOCADO"


async def test_cambio_de_datos_no_revoca(client, crear_usuario):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    est = await crear_usuario(R.ESTUDIANTE, USH)
    sesion = auth(est)
    assert (await _editar(client, admin, est.id, apellido="Gomez")).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=sesion)).status_code == 200


@pytest.mark.parametrize(
    ("payload", "codigo"),
    [
        ({"rol": "ADMIN_LOCAL"}, "PERMISO_INSUFICIENTE"),
        ({"rol": "SUPERADMIN", "sede": None}, "PERMISO_INSUFICIENTE"),
        ({"sede": "Río Grande"}, "SEDE_FUERA_DE_ALCANCE"),
    ],
)
async def test_limites_del_admin_local(client, crear_usuario, payload, codigo):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    est = await crear_usuario(R.ESTUDIANTE, USH)
    r = await _editar(client, admin, est.id, **payload)
    assert r.status_code == 403 and r.json()["code"] == codigo


async def test_admin_local_sobre_otra_sede_y_sobre_admins(client, crear_usuario):
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    ajeno = await crear_usuario(R.ESTUDIANTE, RG)
    otro_admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    assert (await _editar(client, admin, ajeno.id, nombre="X")).status_code == 404
    r = await _editar(client, admin, otro_admin.id, nombre="X")
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


async def test_superadmin_corrige_sede_de_pendiente(client, crear_usuario):  # EC-21 de SPEC-01
    sa = await crear_usuario(R.SUPERADMIN)
    pend = await crear_usuario(R.ESTUDIANTE, USH, E.PENDIENTE_APROBACION)
    r = await _editar(client, sa, pend.id, sede="Río Grande")
    assert r.status_code == 200 and r.json()["sede"] == "Río Grande"


async def test_alcance_incoherente(client, crear_usuario):
    sa = await crear_usuario(R.SUPERADMIN)
    est = await crear_usuario(R.ESTUDIANTE, USH)
    assert (await _editar(client, sa, est.id, rol="SUPERADMIN")).status_code == 422
    r = await _editar(client, sa, est.id, rol="SUPERADMIN", sede=None)
    assert r.status_code == 200 and r.json()["sede"] is None


async def test_propio_rol_o_sede(client, crear_usuario):
    sa = await crear_usuario(R.SUPERADMIN)
    await crear_usuario(R.SUPERADMIN)
    r = await _editar(client, sa, sa.id, rol="ADMIN_LOCAL", sede="Ushuaia")
    assert r.status_code == 403 and r.json()["code"] == "OPERACION_SOBRE_SI_MISMO"


async def test_superadmin_degrada_a_otro_si_queda_uno(client, crear_usuario):
    actor = await crear_usuario(R.SUPERADMIN)
    otro = await crear_usuario(R.SUPERADMIN)
    r = await _editar(client, actor, otro.id, rol="ADMIN_LOCAL", sede="Ushuaia")
    assert r.status_code == 200 and r.json()["rol"] == "ADMIN_LOCAL"


async def test_reseteo_de_password(client, db, crear_usuario):
    sa = await crear_usuario(R.SUPERADMIN)
    est = await crear_usuario(R.ESTUDIANTE, RG)
    est_id = est.id
    r = await _editar(client, sa, est_id, password_nueva="Reseteada2026")
    assert r.status_code == 200 and r.json()["debe_cambiar_password"] is True
    assert (await client.post("/api/v1/auth/login", json={"email": est.email, "password": PASSWORD})).status_code == 401
    login = await client.post("/api/v1/auth/login", json={"email": est.email, "password": "Reseteada2026"})
    assert login.status_code == 200 and login.json()["usuario"]["debe_cambiar_password"] is True
    db.expire_all()
    hist = (
        await db.scalars(select(UsuarioHistorialCambios).where(UsuarioHistorialCambios.usuario_id == est_id))
    ).all()
    assert hist[-1].cambios == {"password": ["***", "***"]}


async def test_duplicados(client, crear_usuario):
    sa = await crear_usuario(R.SUPERADMIN)
    a = await crear_usuario(email="a@untdf.edu.ar")
    b = await crear_usuario()
    r = await _editar(client, sa, b.id, dni=a.dni)
    assert r.status_code == 409 and r.json()["code"] == "DNI_YA_REGISTRADO"
    r = await _editar(client, sa, b.id, email="A@untdf.edu.ar")
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_YA_REGISTRADO"


async def test_payload_vacio_o_null(client, crear_usuario):
    sa = await crear_usuario(R.SUPERADMIN)
    est = await crear_usuario()
    assert (await _editar(client, sa, est.id)).status_code == 422
    assert (await _editar(client, sa, est.id, nombre=None)).status_code == 422


async def test_ultimo_superadmin_no_puede_perder_rol(db, crear_usuario):
    """El actor es otro SUPERADMIN inactivo: se verifica la salvaguarda del servicio."""
    from app.core.errors import AppError
    from app.modules.users import service
    from app.modules.users.schemas import UsuarioAdminUpdate

    unico = await crear_usuario(R.SUPERADMIN)
    unico_id = unico.id
    actor = await crear_usuario(R.SUPERADMIN, estado=E.INACTIVO)
    with pytest.raises(AppError) as exc:
        await service.editar_por_admin(
            db, actor, unico_id, UsuarioAdminUpdate(rol="ADMIN_LOCAL", sede="Ushuaia")
        )
    assert exc.value.code == "ULTIMO_SUPERADMIN"
    db.expire_all()
    assert (await db.get(Usuario, unico_id)).rol == R.SUPERADMIN
