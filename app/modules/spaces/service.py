"""Reglas de negocio del módulo `spaces` (RES-01…RES-05, GLO-01…GLO-04; SPEC-02 §3).

- Alcance de sede según SPEC-02 §2 (``resolver_alcance_sede`` / ``puede_ver_sede``).
- Horario, anticipación mínima y ventana máxima se leen de `config` en cada
  operación (RN-27); fechas y horas en la zona del laboratorio (RN-28).
- Las escrituras sobre un mismo espacio se serializan con ``SELECT … FOR UPDATE``
  del espacio; la restricción GIST de PostgreSQL es la garantía final.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    permiso_insuficiente,
    puede_ver_sede,
    resolver_alcance_sede,
    sede_para_alta,
)
from app.core.enums import ROLES_ADMIN, RolUsuario, SedeEnum
from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB, ahora_lab
from app.modules.config.service import obtener_parametro
from app.modules.spaces.availability import (
    bloqueo_intervalo_en_fecha,
    bloqueo_solapa,
    intervalos_libres,
)
from app.modules.spaces.models import BloqueoEspacio, Espacio, ReservaEspacio
from app.modules.spaces.schemas import (
    ESTADOS_ACTIVOS,
    BloqueoEspacioCreate,
    BloqueoEspacioResponse,
    DisponibilidadResponse,
    EspacioCreate,
    EstadoReserva,
    FranjaOcupada,
    IntervaloLibre,
    IntervalosEspacio,
    ReservaEspacioCreate,
    ReservaEspacioUpdateStatus,
)
from app.modules.users.models import Usuario

ER = EstadoReserva

ROLES_SOLICITANTES = frozenset({RolUsuario.ESTUDIANTE, RolUsuario.DOCENTE})  # RN-26, D-08

# Transiciones administrativas (SPEC-02 §3.4, incluye En_Uso/Finalizada del PR #6).
TRANSICIONES_ADMIN: dict[ER, set[ER]] = {
    ER.PENDIENTE: {ER.APROBADA, ER.RECHAZADA, ER.CANCELADA},
    ER.APROBADA: {ER.EN_USO, ER.CANCELADA},
    ER.EN_USO: {ER.FINALIZADA},
    ER.RECHAZADA: set(),
    ER.CANCELADA: set(),
    ER.FINALIZADA: set(),
}
CANCELABLES_POR_DUENO = {ER.PENDIENTE, ER.APROBADA}  # RES-03

MOTIVO_DESCARTE = (
    "Reserva descartada automáticamente: el espacio fue adjudicado a otra "
    "solicitud para la misma franja horaria."
)


# ── Errores ──────────────────────────────────────────────────────────────────


def _espacio_no_encontrado() -> AppError:
    return AppError(404, "ESPACIO_NO_ENCONTRADO", "Espacio no encontrado.")


def _reserva_no_encontrada() -> AppError:
    return AppError(404, "RESERVA_NO_ENCONTRADA", "Reserva no encontrada.")


def _franja_ocupada() -> AppError:
    return AppError(409, "FRANJA_OCUPADA", "La franja ya fue adjudicada a otra reserva.")


def _transicion_invalida(actual: ER, nuevo: ER) -> AppError:
    return AppError(
        409,
        "TRANSICION_INVALIDA",
        f"No se puede cambiar una reserva de '{actual.value}' a '{nuevo.value}'.",
        estado_actual=actual.value,
    )


def _fmt(h: time) -> str:
    return h.strftime("%H:%M")


# ── Helpers ──────────────────────────────────────────────────────────────────


async def horario(db: AsyncSession) -> tuple[time, time]:
    """Horario operativo vigente (GLO-02) desde los parámetros globales."""
    apertura = await obtener_parametro(db, "horario.apertura")
    cierre = await obtener_parametro(db, "horario.cierre")
    assert isinstance(apertura, time) and isinstance(cierre, time)
    return apertura, cierre


def _es_admin(usuario: Usuario) -> bool:
    return usuario.rol in ROLES_ADMIN


async def _espacio_en_alcance(
    db: AsyncSession, actor: Usuario, id_espacio: int, *, bloquear: bool = False
) -> Espacio:
    """Espacio visible para ``actor``; fuera de su sede se responde 404 (RN-11)."""
    stmt = select(Espacio).where(Espacio.id_espacio == id_espacio)
    if bloquear:
        stmt = stmt.with_for_update()
    espacio = await db.scalar(stmt)
    if espacio is None or not puede_ver_sede(actor, espacio.sede):
        raise _espacio_no_encontrado()
    return espacio


async def _bloqueos_en_fecha(db: AsyncSession, id_espacio: int, fecha: date) -> list[BloqueoEspacio]:
    result = await db.scalars(
        select(BloqueoEspacio).where(
            BloqueoEspacio.id_espacio == id_espacio,
            BloqueoEspacio.fecha_inicio <= fecha,
            BloqueoEspacio.fecha_fin >= fecha,
        )
    )
    return list(result.all())


async def _validar_sin_bloqueo(
    db: AsyncSession, id_espacio: int, fecha: date, inicio: time, fin: time
) -> None:
    """V6 · Un bloqueo administrativo impide reservar la franja (RES-04, RN-29)."""
    for bloqueo in await _bloqueos_en_fecha(db, id_espacio, fecha):
        if bloqueo_solapa(bloqueo, fecha, inicio, fin):
            raise AppError(
                409,
                "ESPACIO_BLOQUEADO",
                f"El espacio está bloqueado en esa franja: {bloqueo.motivo}",
            )


def _stmt_solapadas(
    id_espacio: int, fecha: date, inicio: time, fin: time, estados: tuple[str, ...]
) -> Select:
    return select(ReservaEspacio).where(
        ReservaEspacio.id_espacio == id_espacio,
        ReservaEspacio.fecha_reserva == fecha,
        ReservaEspacio.estado_reserva.in_(estados),
        ReservaEspacio.hora_inicio < fin,
        ReservaEspacio.hora_fin > inicio,
    )


# ── Espacios ─────────────────────────────────────────────────────────────────


async def listar_espacios(db: AsyncSession, actor: Usuario, sede: SedeEnum | None) -> list[Espacio]:
    sedes = resolver_alcance_sede(actor, sede)
    result = await db.scalars(
        select(Espacio).where(Espacio.sede.in_(sedes)).order_by(Espacio.sede, Espacio.nombre)
    )
    return list(result.all())


async def crear_espacio(db: AsyncSession, actor: Usuario, datos: EspacioCreate) -> Espacio:
    """Alta con sede automática para ``ADMIN_LOCAL`` (PRE-19, RN-31)."""
    espacio = Espacio(nombre=datos.nombre, tipo=datos.tipo, sede=sede_para_alta(actor, datos.sede))
    db.add(espacio)
    await db.commit()
    await db.refresh(espacio)
    return espacio


# ── Reservas ─────────────────────────────────────────────────────────────────


async def crear_reserva(db: AsyncSession, actor: Usuario, datos: ReservaEspacioCreate) -> ReservaEspacio:
    """Solicitud en estado ``Pendiente`` con validaciones V2–V8 (SPEC-02 §3.3)."""
    if actor.rol not in ROLES_SOLICITANTES:
        raise permiso_insuficiente()
    try:
        await _espacio_en_alcance(db, actor, datos.id_espacio, bloquear=True)  # V2

        apertura, cierre = await horario(db)  # V3
        if datos.hora_inicio < apertura or datos.hora_fin > cierre:
            raise AppError(
                422,
                "FUERA_DE_HORARIO",
                "La reserva debe estar dentro del horario del laboratorio "
                f"({_fmt(apertura)}–{_fmt(cierre)}).",
            )

        ahora = ahora_lab()
        minimo = int(await obtener_parametro(db, "solicitud.anticipacion_min_horas"))  # V4
        inicio = datetime.combine(datos.fecha_reserva, datos.hora_inicio, tzinfo=ZONA_HORARIA_LAB)
        if inicio < ahora + timedelta(hours=minimo):
            raise AppError(
                422,
                "ANTICIPACION_INSUFICIENTE",
                f"Las solicitudes se envían con al menos {minimo} horas de anticipación.",
            )

        maximo = int(await obtener_parametro(db, "reserva_espacio.anticipacion_max_dias"))  # V5
        if datos.fecha_reserva > ahora.date() + timedelta(days=maximo):
            raise AppError(
                422, "FUERA_DE_VENTANA", f"Sólo se puede reservar hasta {maximo} días a futuro."
            )

        await _validar_sin_bloqueo(  # V6
            db, datos.id_espacio, datos.fecha_reserva, datos.hora_inicio, datos.hora_fin
        )

        stmt = _stmt_solapadas(  # V7
            datos.id_espacio, datos.fecha_reserva, datos.hora_inicio, datos.hora_fin, ESTADOS_ACTIVOS
        )
        if await db.scalar(stmt.limit(1)) is not None:
            raise _franja_ocupada()

        propias = _stmt_solapadas(  # V8
            datos.id_espacio,
            datos.fecha_reserva,
            datos.hora_inicio,
            datos.hora_fin,
            (ER.PENDIENTE.value, *ESTADOS_ACTIVOS),
        ).where(ReservaEspacio.id_usuario == actor.id)
        if await db.scalar(propias.limit(1)) is not None:
            raise AppError(409, "RESERVA_DUPLICADA", "Ya tenés una solicitud para esa franja.")
    except AppError:
        await db.rollback()
        raise

    reserva = ReservaEspacio(
        id_usuario=actor.id,  # RN-25
        id_espacio=datos.id_espacio,
        fecha_reserva=datos.fecha_reserva,
        hora_inicio=datos.hora_inicio,
        hora_fin=datos.hora_fin,
        motivo=datos.motivo,
        estado_reserva=ER.PENDIENTE.value,
    )
    db.add(reserva)
    await db.commit()
    await db.refresh(reserva)
    return reserva


async def listar_reservas(
    db: AsyncSession,
    actor: Usuario,
    *,
    id_espacio: int | None,
    fecha: date | None,
    estado: ER | None,
    id_usuario: int | None,
    sede: SedeEnum | None,
) -> list[ReservaEspacio]:
    """Estudiante/Docente: sólo las propias. Admin: las de espacios de su alcance (RN-30)."""
    stmt = select(ReservaEspacio).join(Espacio, ReservaEspacio.id_espacio == Espacio.id_espacio)
    if _es_admin(actor):
        stmt = stmt.where(Espacio.sede.in_(resolver_alcance_sede(actor, sede)))
        if id_usuario is not None:
            stmt = stmt.where(ReservaEspacio.id_usuario == id_usuario)
    else:
        stmt = stmt.where(ReservaEspacio.id_usuario == actor.id)  # se ignora ?id_usuario
    if id_espacio is not None:
        stmt = stmt.where(ReservaEspacio.id_espacio == id_espacio)
    if fecha is not None:
        stmt = stmt.where(ReservaEspacio.fecha_reserva == fecha)
    if estado is not None:
        stmt = stmt.where(ReservaEspacio.estado_reserva == estado.value)
    stmt = stmt.order_by(
        ReservaEspacio.fecha_reserva, ReservaEspacio.hora_inicio, ReservaEspacio.id_reserva
    )
    return list((await db.scalars(stmt)).all())


async def cambiar_estado_reserva(
    db: AsyncSession, actor: Usuario, id_reserva: int, req: ReservaEspacioUpdateStatus
) -> ReservaEspacio:
    """Transiciones de SPEC-02 §3.4 (RES-03, RES-05)."""
    try:
        # Orden de bloqueo fijo (espacio → reserva), igual que al crear reservas y
        # bloqueos: evita deadlocks entre aprobaciones concurrentes del mismo espacio.
        id_espacio = await db.scalar(
            select(ReservaEspacio.id_espacio).where(ReservaEspacio.id_reserva == id_reserva)
        )
        if id_espacio is None:
            raise _reserva_no_encontrada()
        espacio = await db.scalar(
            select(Espacio).where(Espacio.id_espacio == id_espacio).with_for_update()
        )
        reserva = await db.scalar(
            select(ReservaEspacio)
            .where(ReservaEspacio.id_reserva == id_reserva)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert espacio is not None and reserva is not None
        actual, nuevo = ER(reserva.estado_reserva), req.nuevo_estado

        if _es_admin(actor):
            if not puede_ver_sede(actor, espacio.sede):
                raise _reserva_no_encontrada()
            if nuevo not in TRANSICIONES_ADMIN[actual]:
                raise _transicion_invalida(actual, nuevo)
            if nuevo == ER.CANCELADA and not req.motivo_rechazo:
                raise AppError(
                    422,
                    "MOTIVO_REQUERIDO",
                    "Indicá el motivo de la cancelación administrativa.",
                )
        else:
            if reserva.id_usuario != actor.id:
                raise _reserva_no_encontrada()
            if nuevo != ER.CANCELADA:
                raise permiso_insuficiente()
            inicio = datetime.combine(
                reserva.fecha_reserva, reserva.hora_inicio, tzinfo=ZONA_HORARIA_LAB
            )
            if actual not in CANCELABLES_POR_DUENO or inicio <= ahora_lab():  # EC-27
                raise _transicion_invalida(actual, nuevo)

        if nuevo in (ER.APROBADA, ER.EN_USO):
            otras = _stmt_solapadas(
                reserva.id_espacio,
                reserva.fecha_reserva,
                reserva.hora_inicio,
                reserva.hora_fin,
                ESTADOS_ACTIVOS,
            ).where(ReservaEspacio.id_reserva != reserva.id_reserva)
            if await db.scalar(otras.limit(1)) is not None:
                raise _franja_ocupada()
            await _validar_sin_bloqueo(
                db, reserva.id_espacio, reserva.fecha_reserva, reserva.hora_inicio, reserva.hora_fin
            )
    except AppError:
        await db.rollback()
        raise

    reserva.estado_reserva = nuevo.value
    if req.motivo_rechazo:
        reserva.motivo = req.motivo_rechazo
    try:
        await db.flush()
        if nuevo == ER.APROBADA:  # RES-05: se descartan las pendientes solapadas
            pendientes = await db.scalars(
                _stmt_solapadas(
                    reserva.id_espacio,
                    reserva.fecha_reserva,
                    reserva.hora_inicio,
                    reserva.hora_fin,
                    (ER.PENDIENTE.value,),
                ).where(ReservaEspacio.id_reserva != reserva.id_reserva)
            )
            for otra in pendientes.all():
                otra.estado_reserva = ER.RECHAZADA.value
                otra.motivo = MOTIVO_DESCARTE
        await db.commit()
    except IntegrityError as exc:  # restricción GIST: garantía final ante concurrencia
        await db.rollback()
        raise _franja_ocupada() from exc
    await db.refresh(reserva)
    return reserva


# ── Bloqueos (RES-04 / GLO-04) ───────────────────────────────────────────────


async def crear_bloqueo(db: AsyncSession, actor: Usuario, datos: BloqueoEspacioCreate) -> BloqueoEspacio:
    try:
        await _espacio_en_alcance(db, actor, datos.id_espacio, bloquear=True)
        if datos.hora_inicio is not None and datos.hora_fin is not None:
            apertura, cierre = await horario(db)
            if datos.hora_inicio < apertura or datos.hora_fin > cierre:
                raise AppError(
                    422,
                    "FUERA_DE_HORARIO",
                    "El bloqueo debe estar dentro del horario del laboratorio "
                    f"({_fmt(apertura)}–{_fmt(cierre)}).",
                )
        activas = await db.scalars(
            select(ReservaEspacio).where(
                ReservaEspacio.id_espacio == datos.id_espacio,
                ReservaEspacio.fecha_reserva >= datos.fecha_inicio,
                ReservaEspacio.fecha_reserva <= datos.fecha_fin,
                ReservaEspacio.estado_reserva.in_(ESTADOS_ACTIVOS),
            )
        )
        bloqueo = BloqueoEspacio(**datos.model_dump())
        if any(
            bloqueo_solapa(bloqueo, r.fecha_reserva, r.hora_inicio, r.hora_fin)
            for r in activas.all()
        ):
            raise AppError(
                409,
                "BLOQUEO_CON_RESERVAS",
                "No se puede bloquear: existe una reserva aprobada o en uso en esa franja. "
                "Cancelala primero.",
            )
    except AppError:
        await db.rollback()
        raise
    db.add(bloqueo)
    await db.commit()
    await db.refresh(bloqueo)
    return bloqueo


async def listar_bloqueos(
    db: AsyncSession, actor: Usuario, *, id_espacio: int | None, fecha: date | None
) -> list[BloqueoEspacio]:
    stmt = (
        select(BloqueoEspacio)
        .join(Espacio, BloqueoEspacio.id_espacio == Espacio.id_espacio)
        .where(Espacio.sede.in_(resolver_alcance_sede(actor, None)))
    )
    if id_espacio is not None:
        stmt = stmt.where(BloqueoEspacio.id_espacio == id_espacio)
    if fecha is not None:
        stmt = stmt.where(BloqueoEspacio.fecha_inicio <= fecha, BloqueoEspacio.fecha_fin >= fecha)
    return list((await db.scalars(stmt.order_by(BloqueoEspacio.fecha_inicio))).all())


# ── Disponibilidad (RES-01) ──────────────────────────────────────────────────


async def disponibilidad(
    db: AsyncSession,
    actor: Usuario,
    *,
    fecha: date,
    sede: SedeEnum | None,
    id_espacio: int | None,
) -> DisponibilidadResponse:
    """Franjas ocupadas (sin identidad), bloqueos e intervalos libres por espacio."""
    sedes = resolver_alcance_sede(actor, sede)
    apertura, cierre = await horario(db)

    stmt = select(Espacio).where(Espacio.sede.in_(sedes)).order_by(Espacio.id_espacio)
    if id_espacio is not None:
        stmt = stmt.where(Espacio.id_espacio == id_espacio)
    espacios = list((await db.scalars(stmt)).all())
    ids = [e.id_espacio for e in espacios]

    reservas: list[ReservaEspacio] = []
    bloqueos: list[BloqueoEspacio] = []
    if ids:
        reservas = list(
            (
                await db.scalars(
                    select(ReservaEspacio)
                    .where(
                        ReservaEspacio.fecha_reserva == fecha,
                        ReservaEspacio.estado_reserva.in_(ESTADOS_ACTIVOS),
                        ReservaEspacio.id_espacio.in_(ids),
                    )
                    .order_by(ReservaEspacio.hora_inicio)
                )
            ).all()
        )
        bloqueos = list(
            (
                await db.scalars(
                    select(BloqueoEspacio).where(
                        BloqueoEspacio.fecha_inicio <= fecha,
                        BloqueoEspacio.fecha_fin >= fecha,
                        BloqueoEspacio.id_espacio.in_(ids),
                    )
                )
            ).all()
        )

    intervalos = []
    for espacio in espacios:
        ocupados = [
            (r.hora_inicio, r.hora_fin) for r in reservas if r.id_espacio == espacio.id_espacio
        ]
        ocupados += [
            intervalo
            for b in bloqueos
            if b.id_espacio == espacio.id_espacio
            if (intervalo := bloqueo_intervalo_en_fecha(b, fecha, apertura, cierre)) is not None
        ]
        intervalos.append(
            IntervalosEspacio(
                id_espacio=espacio.id_espacio,
                intervalos_libres=[
                    IntervaloLibre(hora_inicio=i, hora_fin=f)
                    for i, f in intervalos_libres(ocupados, apertura, cierre)
                ],
            )
        )

    return DisponibilidadResponse(
        fecha=fecha,
        sede=sedes[0] if len(sedes) == 1 else None,
        id_espacio=id_espacio,
        horario_apertura=apertura,
        horario_cierre=cierre,
        franjas_ocupadas=[
            FranjaOcupada(
                id_espacio=r.id_espacio,
                hora_inicio=r.hora_inicio,
                hora_fin=r.hora_fin,
                estado_reserva=ER(r.estado_reserva),
            )
            for r in reservas
        ],
        bloqueos=[BloqueoEspacioResponse.model_validate(b) for b in bloqueos],
        intervalos_disponibles=intervalos,
    )

