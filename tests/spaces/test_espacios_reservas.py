"""SPEC-02 §3 · Integración de seguridad en `spaces` — AC-31…AC-38, EC-23…EC-28."""

import asyncio
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.enums import RolUsuario, SedeEnum
from app.core.settings import ZONA_HORARIA_LAB, ahora_lab
from app.modules.spaces.models import ReservaEspacio
from tests.conftest import auth, dia

pytestmark = pytest.mark.integracion

B = "/api/v1/spaces"
R = RolUsuario
USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE


def _reserva(espacio, fecha=None, inicio="10:00", fin="11:00", **extra):
    return {
        "id_espacio": espacio.id_espacio,
        "fecha_reserva": str(fecha or dia(3)),
        "hora_inicio": inicio,
        "hora_fin": fin,
        **extra,
    }


async def _reservar(client, usuario, espacio, **kw):
    return await client.post(f"{B}/reservas", json=_reserva(espacio, **kw), headers=auth(usuario))


async def _estado(client, actor, reserva_id, **payload):
    return await client.patch(f"{B}/reservas/{reserva_id}/estado", json=payload, headers=auth(actor))


# ── AC-31 ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("get", "/espacios"), ("post", "/espacios"), ("get", "/reservas"), ("post", "/reservas"),
        ("patch", "/reservas/1/estado"), ("get", "/bloqueos"), ("post", "/bloqueos"),
        ("get", "/disponibilidad?fecha=2026-10-12"),
    ],
)
async def test_exigen_sesion(client, db, metodo, ruta):  # AC-31
    r = await getattr(client, metodo)(f"{B}{ruta}", **({"json": {}} if metodo != "get" else {}))
    assert r.status_code == 401 and r.json()["code"] == "NO_AUTENTICADO"


# ── Espacios ─────────────────────────────────────────────────────────────────


async def test_aislamiento_de_espacios(client, crear_usuario, crear_espacio):  # AC-32
    await crear_espacio(USH, "Isla USH")
    await crear_espacio(RG, "Isla RG")
    est = await crear_usuario(R.ESTUDIANTE, USH)
    r = await client.get(f"{B}/espacios", headers=auth(est))
    assert [e["nombre"] for e in r.json()] == ["Isla USH"]
    assert r.json()[0]["sede"] == "Ushuaia"
    ajena = await client.get(f"{B}/espacios", params={"sede": "Río Grande"}, headers=auth(est))
    assert ajena.status_code == 403 and ajena.json()["code"] == "SEDE_FUERA_DE_ALCANCE"
    sa = await crear_usuario(R.SUPERADMIN)
    assert len((await client.get(f"{B}/espacios", headers=auth(sa))).json()) == 2


async def test_alta_de_espacio_pre19(client, crear_usuario):  # AC-33
    admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG)
    r = await client.post(f"{B}/espacios", json={"nombre": "Aula RG"}, headers=auth(admin_rg))
    assert r.status_code == 201 and r.json()["sede"] == "Río Grande"
    r = await client.post(
        f"{B}/espacios", json={"nombre": "X", "sede": "Ushuaia"}, headers=auth(admin_rg)
    )
    assert r.status_code == 403 and r.json()["code"] == "SEDE_FUERA_DE_ALCANCE"
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.post(f"{B}/espacios", json={"nombre": "X"}, headers=auth(sa))
    assert r.status_code == 422 and r.json()["code"] == "SEDE_REQUERIDA"
    est = await crear_usuario(R.ESTUDIANTE, RG)
    r = await client.post(f"{B}/espacios", json={"nombre": "X"}, headers=auth(est))
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


# ── Creación de reservas ─────────────────────────────────────────────────────


async def test_reserva_pertenece_al_usuario_del_token(client, crear_usuario, crear_espacio):  # AC-34
    est = await crear_usuario(R.ESTUDIANTE, USH)
    esp = await crear_espacio(USH)
    r = await _reservar(client, est, esp, motivo="Práctica de montaje")
    assert r.status_code == 201, r.text
    assert r.json()["id_usuario"] == est.id and r.json()["estado_reserva"] == "Pendiente"
    r = await client.post(
        f"{B}/reservas", json=_reserva(esp, id_usuario=999), headers=auth(est)
    )
    assert r.status_code == 422


@pytest.mark.parametrize("rol", [R.ADMIN_LOCAL, R.SUPERADMIN])
async def test_admins_no_crean_reservas(client, crear_usuario, crear_espacio, rol):  # D-08
    admin = await crear_usuario(rol, USH)
    esp = await crear_espacio(USH)
    r = await _reservar(client, admin, esp)
    assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"


class TestValidacionesDeCreacion:  # AC-35
    async def test_espacio_de_otra_sede(self, client, crear_usuario, crear_espacio):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(RG)
        r = await _reservar(client, est, esp)
        assert r.status_code == 404 and r.json()["code"] == "ESPACIO_NO_ENCONTRADO"

    async def test_fuera_de_horario_y_horario_configurable(
        self, client, crear_usuario, crear_espacio, set_parametro
    ):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        r = await _reservar(client, est, esp, inicio="08:00", fin="09:00")
        assert r.status_code == 422 and r.json()["code"] == "FUERA_DE_HORARIO"
        assert "09:00–16:00" in r.json()["detail"]
        assert (await _reservar(client, est, esp, inicio="16:00", fin="17:00")).status_code == 422
        await set_parametro("horario.cierre", "18:00")
        assert (await _reservar(client, est, esp, inicio="16:00", fin="17:00")).status_code == 201

    async def test_anticipacion_minima(self, client, crear_usuario, crear_espacio, set_parametro):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        r = await _reservar(client, est, esp, fecha=dia(0), inicio="15:00", fin="16:00")
        assert r.status_code == 422 and r.json()["code"] == "ANTICIPACION_INSUFICIENTE"
        assert "24 horas" in r.json()["detail"]
        await set_parametro("solicitud.anticipacion_min_horas", 0)
        await set_parametro("horario.apertura", "00:00")
        await set_parametro("horario.cierre", "23:59")
        r = await _reservar(client, est, esp, fecha=dia(1), inicio="00:00", fin="01:00")
        assert r.status_code == 201, r.text

    async def test_anticipacion_en_hora_local_del_laboratorio(  # EC-23
        self, client, crear_usuario, crear_espacio, set_parametro
    ):
        await set_parametro("horario.apertura", "00:00")
        await set_parametro("horario.cierre", "23:59")
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        inicio = (ahora_lab() + timedelta(hours=25)).replace(second=0, microsecond=0)
        fin = inicio + timedelta(minutes=30)
        if fin.date() != inicio.date():
            inicio -= timedelta(minutes=30)
            fin -= timedelta(minutes=30)
        r = await _reservar(
            client, est, esp, fecha=inicio.date(),
            inicio=inicio.strftime("%H:%M"), fin=fin.strftime("%H:%M"),
        )
        assert r.status_code == 201, r.text
        assert inicio.tzinfo == ZONA_HORARIA_LAB

    async def test_ventana_maxima(self, client, crear_usuario, crear_espacio):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        r = await _reservar(client, est, esp, fecha=dia(121))
        assert r.status_code == 422 and r.json()["code"] == "FUERA_DE_VENTANA"
        assert (await _reservar(client, est, esp, fecha=dia(120))).status_code == 201

    async def test_bloqueos_de_dia_y_de_franja(self, client, crear_usuario, crear_espacio):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        base = {"id_espacio": esp.id_espacio, "motivo": "Feriado"}
        await client.post(
            f"{B}/bloqueos", headers=auth(admin),
            json={**base, "fecha_inicio": str(dia(3)), "fecha_fin": str(dia(3))},
        )
        r = await _reservar(client, est, esp, fecha=dia(3))
        assert r.status_code == 409 and r.json()["code"] == "ESPACIO_BLOQUEADO"
        assert "Feriado" in r.json()["detail"]
        await client.post(
            f"{B}/bloqueos", headers=auth(admin),
            json={**base, "fecha_inicio": str(dia(4)), "fecha_fin": str(dia(4)),
                  "hora_inicio": "10:00", "hora_fin": "12:00"},
        )
        assert (await _reservar(client, est, esp, fecha=dia(4), inicio="11:00", fin="13:00")).status_code == 409
        assert (await _reservar(client, est, esp, fecha=dia(4), inicio="12:00", fin="13:00")).status_code == 201  # EC-24

    async def test_franja_ocupada_y_concurrencia(self, client, crear_usuario, crear_espacio, crear_reserva):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        otro = await crear_usuario(R.DOCENTE, USH)
        esp = await crear_espacio(USH)
        await crear_reserva(otro, esp, estado="Aprobada")
        r = await _reservar(client, est, esp, inicio="10:30", fin="11:30")
        assert r.status_code == 409 and r.json()["code"] == "FRANJA_OCUPADA"
        esp2 = await crear_espacio(USH, "Isla 2")
        await crear_reserva(otro, esp2)  # Pendiente de otro: no impide (RES-02)
        assert (await _reservar(client, est, esp2)).status_code == 201
        r = await _reservar(client, est, esp2, inicio="10:30", fin="11:30")
        assert r.status_code == 409 and r.json()["code"] == "RESERVA_DUPLICADA"


# ── Privacidad (AC-36) ───────────────────────────────────────────────────────


async def test_privacidad_de_reservas(client, crear_usuario, crear_espacio, crear_reserva):
    est = await crear_usuario(R.ESTUDIANTE, USH)
    otro = await crear_usuario(R.ESTUDIANTE, USH)
    esp_ush = await crear_espacio(USH)
    esp_rg = await crear_espacio(RG, "Isla RG")
    propia = await crear_reserva(est, esp_ush)
    await crear_reserva(otro, esp_ush, inicio=time(13), fin=time(14), estado="Aprobada")
    usuario_rg = await crear_usuario(R.ESTUDIANTE, RG)
    await crear_reserva(usuario_rg, esp_rg)

    r = await client.get(f"{B}/reservas", params={"id_usuario": otro.id}, headers=auth(est))
    assert [x["id_reserva"] for x in r.json()] == [propia.id_reserva]

    disp = await client.get(f"{B}/disponibilidad", params={"fecha": str(dia(3))}, headers=auth(est))
    assert disp.status_code == 200
    body = disp.json()
    assert body["franjas_ocupadas"] == [
        {"id_espacio": esp_ush.id_espacio, "hora_inicio": "13:00:00", "hora_fin": "14:00:00",
         "estado_reserva": "Aprobada"}
    ]
    assert "id_usuario" not in str(body) and "id_reserva" not in str(body)
    assert body["horario_apertura"] == "09:00:00" and body["horario_cierre"] == "16:00:00"
    assert body["sede"] == "Ushuaia"

    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    r = await client.get(f"{B}/reservas", headers=auth(admin))
    assert len(r.json()) == 2 and all(x["id_espacio"] == esp_ush.id_espacio for x in r.json())
    r = await client.get(f"{B}/reservas", params={"id_usuario": otro.id}, headers=auth(admin))
    assert len(r.json()) == 1


async def test_disponibilidad_intervalos_y_alcance(client, crear_usuario, crear_espacio, crear_reserva):
    est = await crear_usuario(R.ESTUDIANTE, USH)
    admin = await crear_usuario(R.ADMIN_LOCAL, USH)
    esp = await crear_espacio(USH)
    await crear_reserva(est, esp, inicio=time(10, 15), fin=time(11, 45), estado="Aprobada")
    await client.post(
        f"{B}/bloqueos", headers=auth(admin),
        json={"id_espacio": esp.id_espacio, "fecha_inicio": str(dia(3)), "fecha_fin": str(dia(3)),
              "hora_inicio": "13:00", "hora_fin": "14:00", "motivo": "Mantenimiento"},
    )
    body = (await client.get(f"{B}/disponibilidad", params={"fecha": str(dia(3))}, headers=auth(est))).json()
    assert body["intervalos_disponibles"] == [
        {"id_espacio": esp.id_espacio, "intervalos_libres": [
            {"hora_inicio": "09:00:00", "hora_fin": "10:15:00"},
            {"hora_inicio": "11:45:00", "hora_fin": "13:00:00"},
            {"hora_inicio": "14:00:00", "hora_fin": "16:00:00"},
        ]}
    ]
    r = await client.get(
        f"{B}/disponibilidad", params={"fecha": str(dia(3)), "sede": "Río Grande"}, headers=auth(est)
    )
    assert r.status_code == 403
    sa = await crear_usuario(R.SUPERADMIN)
    r = await client.get(f"{B}/disponibilidad", params={"fecha": str(dia(3))}, headers=auth(sa))
    assert r.json()["sede"] is None  # vista "Ambas sedes" (EC-31)


# ── Transiciones (AC-37) ─────────────────────────────────────────────────────


class TestTransiciones:
    async def test_dueno_cancela(self, client, crear_usuario, crear_espacio, crear_reserva):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        for estado in ("Pendiente", "Aprobada"):
            res = await crear_reserva(est, esp, fecha=dia(5 if estado == "Pendiente" else 6), estado=estado)
            r = await _estado(client, est, res.id_reserva, nuevo_estado="Cancelada")
            assert r.status_code == 200 and r.json()["estado_reserva"] == "Cancelada"

    async def test_dueno_no_aprueba_y_terceros_no_ven(self, client, crear_usuario, crear_espacio, crear_reserva):
        est = await crear_usuario(R.ESTUDIANTE, USH)
        otro = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        res = await crear_reserva(est, esp)
        r = await _estado(client, est, res.id_reserva, nuevo_estado="Aprobada")
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"
        r = await _estado(client, otro, res.id_reserva, nuevo_estado="Cancelada")
        assert r.status_code == 404 and r.json()["code"] == "RESERVA_NO_ENCONTRADA"

    async def test_dueno_no_cancela_pasada(self, client, crear_usuario, crear_espacio, crear_reserva):  # EC-27
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        res = await crear_reserva(est, esp, fecha=dia(-1), estado="Aprobada")
        r = await _estado(client, est, res.id_reserva, nuevo_estado="Cancelada")
        assert r.status_code == 409 and r.json()["code"] == "TRANSICION_INVALIDA"

    async def test_admin_de_otra_sede(self, client, crear_usuario, crear_espacio, crear_reserva):
        admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG)
        est = await crear_usuario(R.ESTUDIANTE, USH)
        res = await crear_reserva(est, await crear_espacio(USH))
        r = await _estado(client, admin_rg, res.id_reserva, nuevo_estado="Aprobada")
        assert r.status_code == 404 and r.json()["code"] == "RESERVA_NO_ENCONTRADA"

    async def test_desde_estado_terminal(self, client, crear_usuario, crear_espacio, crear_reserva):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        est = await crear_usuario(R.ESTUDIANTE, USH)
        res = await crear_reserva(est, await crear_espacio(USH), estado="Rechazada")
        r = await _estado(client, admin, res.id_reserva, nuevo_estado="Aprobada")
        assert r.status_code == 409 and r.json()["code"] == "TRANSICION_INVALIDA"

    async def test_cancelacion_admin_exige_motivo(self, client, crear_usuario, crear_espacio, crear_reserva):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        est = await crear_usuario(R.ESTUDIANTE, USH)
        res = await crear_reserva(est, await crear_espacio(USH), estado="Aprobada")
        r = await _estado(client, admin, res.id_reserva, nuevo_estado="Cancelada")
        assert r.status_code == 422 and r.json()["code"] == "MOTIVO_REQUERIDO"
        r = await _estado(client, admin, res.id_reserva, nuevo_estado="Cancelada", motivo_rechazo="Rotura")
        assert r.status_code == 200

    async def test_aprobar_descarta_pendientes_y_ciclo_de_uso(
        self, client, db, crear_usuario, crear_espacio, crear_reserva
    ):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        a = await crear_usuario(R.ESTUDIANTE, USH)
        b = await crear_usuario(R.DOCENTE, USH)
        esp = await crear_espacio(USH)
        ra = await crear_reserva(a, esp)
        rb = await crear_reserva(b, esp, inicio=time(10, 30), fin=time(11, 30))
        ra_id, rb_id = ra.id_reserva, rb.id_reserva
        assert (await _estado(client, admin, ra_id, nuevo_estado="Aprobada")).status_code == 200
        db.expire_all()
        descartada = await db.get(ReservaEspacio, rb_id)
        assert descartada.estado_reserva == "Rechazada" and "adjudicado" in descartada.motivo
        assert (await _estado(client, admin, ra_id, nuevo_estado="En_Uso")).status_code == 200
        r = await _estado(client, admin, ra_id, nuevo_estado="Finalizada")
        assert r.status_code == 200 and r.json()["estado_reserva"] == "Finalizada"

    async def test_aprobar_rechaza_si_hay_bloqueo(self, client, db, crear_usuario, crear_espacio, crear_reserva):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        est = await crear_usuario(R.ESTUDIANTE, USH)
        esp = await crear_espacio(USH)
        res = await crear_reserva(est, esp)
        r = await client.post(
            f"{B}/bloqueos", headers=auth(admin),
            json={"id_espacio": esp.id_espacio, "fecha_inicio": str(dia(3)), "fecha_fin": str(dia(3)),
                  "hora_inicio": "10:30", "hora_fin": "11:30", "motivo": "Mantenimiento"},
        )
        assert r.status_code == 201  # una Pendiente no impide bloquear
        r = await _estado(client, admin, res.id_reserva, nuevo_estado="Aprobada")
        assert r.status_code == 409 and r.json()["code"] == "ESPACIO_BLOQUEADO"

    async def test_aprobaciones_concurrentes_solapadas(self, client, crear_usuario, crear_espacio, crear_reserva):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        sa = await crear_usuario(R.SUPERADMIN)
        esp = await crear_espacio(USH)
        r1 = await crear_reserva(await crear_usuario(R.ESTUDIANTE, USH), esp)
        r2 = await crear_reserva(await crear_usuario(R.ESTUDIANTE, USH), esp, inicio=time(10, 30), fin=time(11, 30))
        respuestas = await asyncio.gather(
            _estado(client, admin, r1.id_reserva, nuevo_estado="Aprobada"),
            _estado(client, sa, r2.id_reserva, nuevo_estado="Aprobada"),
        )
        assert sorted(r.status_code for r in respuestas) == [200, 409]


# ── Bloqueos (AC-38) ─────────────────────────────────────────────────────────


class TestBloqueos:
    def _bloqueo(self, esp, **extra):
        return {"id_espacio": esp.id_espacio, "fecha_inicio": str(dia(3)),
                "fecha_fin": str(dia(3)), "motivo": "Mantenimiento", **extra}

    async def test_alcance_y_roles(self, client, crear_usuario, crear_espacio):
        admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH)
        esp_rg = await crear_espacio(RG)
        r = await client.post(f"{B}/bloqueos", json=self._bloqueo(esp_rg), headers=auth(admin_ush))
        assert r.status_code == 404 and r.json()["code"] == "ESPACIO_NO_ENCONTRADO"
        doc = await crear_usuario(R.DOCENTE, RG)
        r = await client.post(f"{B}/bloqueos", json=self._bloqueo(esp_rg), headers=auth(doc))
        assert r.status_code == 403 and r.json()["code"] == "PERMISO_INSUFICIENTE"

    async def test_franja_fuera_de_horario(self, client, crear_usuario, crear_espacio):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        esp = await crear_espacio(USH)
        r = await client.post(
            f"{B}/bloqueos", json=self._bloqueo(esp, hora_inicio="08:00", hora_fin="10:00"), headers=auth(admin)
        )
        assert r.status_code == 422 and r.json()["code"] == "FUERA_DE_HORARIO"

    async def test_no_pisa_reservas_activas(self, client, crear_usuario, crear_espacio, crear_reserva):
        admin = await crear_usuario(R.ADMIN_LOCAL, USH)
        esp = await crear_espacio(USH)
        await crear_reserva(await crear_usuario(R.ESTUDIANTE, USH), esp, estado="Aprobada")
        r = await client.post(
            f"{B}/bloqueos", json=self._bloqueo(esp, hora_inicio="10:30", hora_fin="11:30"), headers=auth(admin)
        )
        assert r.status_code == 409 and r.json()["code"] == "BLOQUEO_CON_RESERVAS"

    async def test_listado_con_alcance(self, client, crear_usuario, crear_espacio):
        admin_ush = await crear_usuario(R.ADMIN_LOCAL, USH)
        admin_rg = await crear_usuario(R.ADMIN_LOCAL, RG)
        esp_rg = await crear_espacio(RG)
        await client.post(f"{B}/bloqueos", json=self._bloqueo(esp_rg), headers=auth(admin_rg))
        assert (await client.get(f"{B}/bloqueos", headers=auth(admin_ush))).json() == []
        assert len((await client.get(f"{B}/bloqueos", headers=auth(admin_rg))).json()) == 1


async def test_usuario_dado_de_baja_conserva_reservas(db, crear_usuario, crear_espacio, crear_reserva):  # EC-28
    from sqlalchemy.exc import IntegrityError

    from app.modules.users.models import Usuario

    est = await crear_usuario(R.ESTUDIANTE, USH)
    est_id = est.id
    await crear_reserva(est, await crear_espacio(USH))
    await db.delete(await db.get(Usuario, est_id))
    with pytest.raises(IntegrityError):  # FK RESTRICT: sólo baja lógica
        await db.commit()
    await db.rollback()
    assert (await db.scalars(select(ReservaEspacio))).first() is not None


async def test_inicio_en_zona_lab():
    inicio = datetime.combine(dia(1), time(9), tzinfo=ZONA_HORARIA_LAB)
    assert inicio.utcoffset() == timedelta(hours=-3)
