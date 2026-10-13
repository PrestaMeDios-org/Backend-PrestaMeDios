"""UC-02/UC-06/UC-07 · Aprobación, ciclo de vida y alta directa (USR-04, USR-05, GLO-01).

AC-07…AC-14, EC-04, EC-13, EC-17.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum
from app.core.errors import AppError
from app.modules.users import service
from app.modules.users.models import Usuario, UsuarioHistorialEstado
from app.modules.users.schemas import CambioEstadoRequest
from tests.conftest import PASSWORD, auth

pytestmark = pytest.mark.integracion

E = EstadoCuenta
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _url(usuario_id: int) -> str:
    return f"/api/v1/users/{usuario_id}/estado"


async def _cambiar(client, actor, objetivo_id, **payload):
    return await client.patch(_url(objetivo_id), json=payload, headers=auth(actor))


async def _recargar(db, usuario_id: int) -> Usuario:
    db.expire_all()
    return await db.get(Usuario, usuario_id)


async def test_admin_local_aprueba_cuenta_de_su_sede(client, db, crear_usuario):  # AC-07
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    pendiente = await crear_usuario(R.ESTUDIANTE, USH, E.PENDIENTE_APROBACION)

    r = await _cambiar(client, admin, pendiente.id, nuevo_estado="ACTIVO")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estado"] == "ACTIVO" and body["aprobado_por_id"] == admin.id
    assert body["aprobado_en"] is not None

    login = await client.post(
        "/api/v1/auth/login", json={"email": pendiente.email, "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_admin_local_no_ve_ni_actua_sobre_otra_sede(client, db, crear_usuario):  # AC-08, EC-08
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    ajeno = await crear_usuario(R.ESTUDIANTE, RG, E.PENDIENTE_APROBACION)

    r_get = await client.get(f"/api/v1/users/{ajeno.id}", headers=auth(admin))
    r_patch = await _cambiar(client, admin, ajeno.id, nuevo_estado="ACTIVO")
    for r in (r_get, r_patch):
        assert r.status_code == 404 and r.json()["code"] == "USUARIO_NO_ENCONTRADO"
    assert (await _recargar(db, ajeno.id)).estado == E.PENDIENTE_APROBACION


async def test_superadmin_aprueba_en_ambas_sedes(client, crear_usuario):  # AC-09
    superadmin = await crear_usuario(R.SUPERADMIN)
    for sede in (USH, RG):
        pendiente = await crear_usuario(R.DOCENTE, sede, E.PENDIENTE_APROBACION)
        r = await _cambiar(client, superadmin, pendiente.id, nuevo_estado="ACTIVO")
        assert r.status_code == 200


async def test_rechazo_exige_motivo(client, db, crear_usuario):  # AC-10
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    pendiente = await crear_usuario(R.ESTUDIANTE, USH, E.PENDIENTE_APROBACION)

    assert (await _cambiar(client, admin, pendiente.id, nuevo_estado="RECHAZADO")).status_code == 422
    assert (await _recargar(db, pendiente.id)).estado == E.PENDIENTE_APROBACION

    r = await _cambiar(
        client, admin, pendiente.id, nuevo_estado="RECHAZADO", motivo="DNI no coincide"
    )
    assert r.status_code == 200
    assert r.json()["estado"] == "RECHAZADO" and r.json()["motivo_estado"] == "DNI no coincide"


async def test_aprobacion_concurrente(client, db, crear_usuario):  # AC-11, EC-13
    admin_1 = await crear_usuario(R.ADMIN_LOCAL, USH)
    admin_2 = await crear_usuario(R.SUPERADMIN)
    pendiente = await crear_usuario(R.ESTUDIANTE, USH, E.PENDIENTE_APROBACION)

    respuestas = await asyncio.gather(
        _cambiar(client, admin_1, pendiente.id, nuevo_estado="ACTIVO"),
        _cambiar(client, admin_2, pendiente.id, nuevo_estado="ACTIVO"),
    )
    assert sorted(r.status_code for r in respuestas) == [200, 409]
    assert next(r for r in respuestas if r.status_code == 409).json()["code"] == "TRANSICION_INVALIDA"

    hist = (
        await db.scalars(
            select(UsuarioHistorialEstado).where(
                UsuarioHistorialEstado.usuario_id == pendiente.id,
                UsuarioHistorialEstado.estado_nuevo == E.ACTIVO,
            )
        )
    ).all()
    assert len(hist) == 1


async def test_suspension_revoca_sesiones_abiertas(client, db, crear_usuario):  # AC-12, EC-04
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    estudiante = await crear_usuario(R.ESTUDIANTE, USH)
    sesion = auth(estudiante)
    assert (await client.get("/api/v1/auth/me", headers=sesion)).status_code == 200

    hasta = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    r = await _cambiar(
        client, admin, estudiante.id,
        nuevo_estado="SUSPENDIDO", motivo="Devolución demorada", suspendido_hasta=hasta,
    )
    assert r.status_code == 200, r.text
    assert r.json()["suspendido_hasta"] is not None

    r_me = await client.get("/api/v1/auth/me", headers=sesion)
    assert r_me.status_code == 401 and r_me.json()["code"] == "TOKEN_REVOCADO"
    assert (await _recargar(db, estudiante.id)).token_version == 1


class TestProtecciones:  # AC-13
    async def test_sobre_si_mismo(self, client, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        r = await _cambiar(client, admin, admin.id, nuevo_estado="INACTIVO", motivo="Prueba")
        assert r.status_code == 403 and r.json()["code"] == "OPERACION_SOBRE_SI_MISMO"

    async def test_admin_local_sobre_otro_admin(self, client, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        otro = await crear_usuario(R.ADMIN_LOCAL, USH)
        r = await _cambiar(client, admin, otro.id, nuevo_estado="SUSPENDIDO", motivo="Prueba")
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"

    async def test_transicion_invalida(self, client, crear_usuario):
        superadmin = await crear_usuario(R.SUPERADMIN)
        inactivo = await crear_usuario(R.ESTUDIANTE, USH, E.INACTIVO)
        r = await _cambiar(client, superadmin, inactivo.id, nuevo_estado="SUSPENDIDO", motivo="x" * 5)
        assert r.status_code == 409
        assert r.json()["code"] == "TRANSICION_INVALIDA" and r.json()["estado_actual"] == "INACTIVO"

    async def test_mismo_estado_es_invalido(self, client, crear_usuario):
        superadmin = await crear_usuario(R.SUPERADMIN)
        activo = await crear_usuario(R.ESTUDIANTE, USH)
        r = await _cambiar(client, superadmin, activo.id, nuevo_estado="ACTIVO")
        assert r.status_code == 409

    async def test_roles_sin_acceso(self, client, crear_usuario):
        docente = await crear_usuario(R.DOCENTE, USH)
        estudiante = await crear_usuario(R.ESTUDIANTE, USH, E.PENDIENTE_APROBACION)
        r = await _cambiar(client, docente, estudiante.id, nuevo_estado="ACTIVO")
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"

    async def test_ultimo_superadmin(self, db, crear_usuario):  # EC-17
        """Vía API es inalcanzable (el actor es otro SUPERADMIN activo y RN-15 impide
        actuar sobre sí mismo); se verifica la salvaguarda del servicio directamente."""
        unico = await crear_usuario(R.SUPERADMIN)
        unico_id = unico.id
        actor = await crear_usuario(R.SUPERADMIN, estado=E.INACTIVO)
        with pytest.raises(AppError) as exc:
            await service.cambiar_estado(
                db, actor, unico_id, CambioEstadoRequest(nuevo_estado="INACTIVO", motivo="Baja")
            )
        assert exc.value.code == "ULTIMO_SUPERADMIN"
        assert (await _recargar(db, unico_id)).estado == E.ACTIVO

    async def test_superadmin_puede_desactivar_a_otro_si_queda_uno(self, client, crear_usuario):
        actor = await crear_usuario(R.SUPERADMIN)
        otro = await crear_usuario(R.SUPERADMIN)
        r = await _cambiar(client, actor, otro.id, nuevo_estado="INACTIVO", motivo="Reemplazo")
        assert r.status_code == 200


async def test_ciclo_completo_con_historial(client, db, crear_usuario):  # §3.2
    superadmin = await crear_usuario(R.SUPERADMIN)
    u = await crear_usuario(R.DOCENTE, RG, E.PENDIENTE_APROBACION)
    pasos = [
        {"nuevo_estado": "ACTIVO"},
        {"nuevo_estado": "SUSPENDIDO", "motivo": "Sanción"},
        {"nuevo_estado": "ACTIVO"},
        {"nuevo_estado": "INACTIVO", "motivo": "Egreso"},
        {"nuevo_estado": "ACTIVO", "motivo": "Reincorporación"},
    ]
    for paso in pasos:
        r = await _cambiar(client, superadmin, u.id, **paso)
        assert r.status_code == 200, (paso, r.text)

    hist = (
        await db.scalars(
            select(UsuarioHistorialEstado)
            .where(UsuarioHistorialEstado.usuario_id == u.id)
            .order_by(UsuarioHistorialEstado.id)
        )
    ).all()
    assert [h.estado_nuevo for h in hist] == [E.ACTIVO, E.SUSPENDIDO, E.ACTIVO, E.INACTIVO, E.ACTIVO]
    assert all(h.actor_id == superadmin.id for h in hist)
    assert (await _recargar(db, u.id)).token_version == 2  # ACTIVO→SUSPENDIDO, ACTIVO→INACTIVO


class TestAltaDirecta:  # AC-14, UC-06
    URL = "/api/v1/users"
    DATOS = {
        "email": "victoria@untdf.edu.ar",
        "password": "Laboratorio1",
        "nombre": "Victoria",
        "apellido": "Admin",
        "dni": "28111222",
    }

    async def test_superadmin_crea_admin_local(self, client, db, crear_usuario):
        superadmin = await crear_usuario(R.SUPERADMIN)
        r = await client.post(
            self.URL, json={**self.DATOS, "rol": "ADMIN_LOCAL", "sede": "Río Grande"},
            headers=auth(superadmin),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["estado"] == "ACTIVO" and body["sede"] == "Río Grande"
        assert body["aprobado_por_id"] == superadmin.id

    @pytest.mark.parametrize(
        "alcance", [{"rol": "ADMIN_LOCAL", "sede": None}, {"rol": "SUPERADMIN", "sede": "Ushuaia"}]
    )
    async def test_alcance_incoherente(self, client, crear_usuario, alcance):
        superadmin = await crear_usuario(R.SUPERADMIN)
        r = await client.post(self.URL, json={**self.DATOS, **alcance}, headers=auth(superadmin))
        assert r.status_code == 422

    async def test_admin_local_no_puede_crear(self, client, crear_usuario):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        r = await client.post(
            self.URL, json={**self.DATOS, "rol": "ESTUDIANTE", "sede": "Ushuaia"}, headers=auth(admin)
        )
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"

    async def test_duplicado(self, client, crear_usuario):
        superadmin = await crear_usuario(R.SUPERADMIN)
        await crear_usuario(email=self.DATOS["email"])
        r = await client.post(
            self.URL, json={**self.DATOS, "rol": "DOCENTE", "sede": "Ushuaia"}, headers=auth(superadmin)
        )
        assert r.status_code == 409 and r.json()["code"] == "EMAIL_YA_REGISTRADO"
