"""Endpoints REST del módulo `spaces` (Subsistema 3: Reserva de Espacios)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.spaces.availability import (
    bloqueo_intervalo_en_fecha,
    bloqueo_solapa_reserva,
    intervalos_libres,
)
from app.modules.spaces.models import BloqueoEspacio, Espacio, ReservaEspacio
from app.modules.spaces.schemas import (
    BloqueoEspacioCreate,
    BloqueoEspacioResponse,
    EstadoReserva,
    EspacioCreate,
    EspacioResponse,
    ReservaEspacioCreate,
    ReservaEspacioResponse,
    ReservaEspacioUpdateStatus,
)

router = APIRouter()

_TRANSICIONES_RESERVA = {
    EstadoReserva.PENDIENTE: {
        EstadoReserva.APROBADA,
        EstadoReserva.RECHAZADA,
        EstadoReserva.CANCELADA,
    },
    EstadoReserva.APROBADA: {EstadoReserva.EN_USO, EstadoReserva.CANCELADA},
    EstadoReserva.EN_USO: {EstadoReserva.FINALIZADA},
    EstadoReserva.RECHAZADA: set(),
    EstadoReserva.CANCELADA: set(),
    EstadoReserva.FINALIZADA: set(),
}


async def _bloquear_espacio(db: AsyncSession, id_espacio: int) -> Espacio:
    """Serializa escrituras del mismo espacio para proteger reglas entre tablas."""
    stmt = select(Espacio).where(Espacio.id_espacio == id_espacio).with_for_update()
    espacio = (await db.execute(stmt)).scalar_one_or_none()
    if espacio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Espacio con id={id_espacio} no encontrado.",
        )
    return espacio


async def _bloqueos_de_reserva(
    db: AsyncSession, reserva: ReservaEspacio
) -> list[BloqueoEspacio]:
    stmt = select(BloqueoEspacio).where(
        BloqueoEspacio.id_espacio == reserva.id_espacio,
        BloqueoEspacio.fecha_inicio <= reserva.fecha_reserva,
        BloqueoEspacio.fecha_fin >= reserva.fecha_reserva,
    )
    return list((await db.execute(stmt)).scalars().all())


async def _validar_reserva_no_bloqueada(db: AsyncSession, reserva: ReservaEspacio) -> None:
    bloqueos = await _bloqueos_de_reserva(db, reserva)
    if any(bloqueo_solapa_reserva(bloqueo, reserva) for bloqueo in bloqueos):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede reservar: el espacio está bloqueado en esa franja horaria.",
        )


async def _validar_sin_reservas_solapadas(
    db: AsyncSession, reserva: ReservaEspacio
) -> None:
    stmt = select(ReservaEspacio).where(
        ReservaEspacio.id_espacio == reserva.id_espacio,
        ReservaEspacio.fecha_reserva == reserva.fecha_reserva,
        ReservaEspacio.estado_reserva.in_(["Aprobada", "En_Uso"]),
        ReservaEspacio.id_reserva != reserva.id_reserva,
        ReservaEspacio.hora_inicio < reserva.hora_fin,
        ReservaEspacio.hora_fin > reserva.hora_inicio,
    )
    if (await db.execute(stmt)).scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede aprobar: ya existe otra reserva aprobada o en uso que solapa esa franja.",
        )


# ---------------------------------------------------------------------------
# Espacios
# ---------------------------------------------------------------------------
@router.post(
    "/espacios",
    response_model=EspacioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_espacio(
    payload: EspacioCreate,
    db: AsyncSession = Depends(get_db),
) -> Espacio:
    """Da de alta un espacio reservable."""
    espacio = Espacio(**payload.model_dump())
    db.add(espacio)
    await db.commit()
    await db.refresh(espacio)
    return espacio


@router.get("/espacios", response_model=list[EspacioResponse])
async def listar_espacios(
    id_sede: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[Espacio]:
    """Lista espacios, filtrables por sede."""
    stmt = select(Espacio)
    if id_sede is not None:
        stmt = stmt.where(Espacio.id_sede == id_sede)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Reservas
# ---------------------------------------------------------------------------
@router.post(
    "/reservas",
    response_model=ReservaEspacioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_reserva(
    payload: ReservaEspacioCreate,
    db: AsyncSession = Depends(get_db),
) -> ReservaEspacio:
    """Crea una reserva en estado 'Pendiente'.

    Los bloqueos existentes impiden generar nuevas solicitudes. El bloqueo
    transaccional del espacio serializa este control con la creación de bloqueos.
    """
    data = payload.model_dump()
    data["estado_reserva"] = "Pendiente"
    reserva = ReservaEspacio(**data)
    await _bloquear_espacio(db, reserva.id_espacio)
    await _validar_reserva_no_bloqueada(db, reserva)
    db.add(reserva)
    await db.commit()
    await db.refresh(reserva)
    return reserva


@router.get("/reservas", response_model=list[ReservaEspacioResponse])
async def listar_reservas(
    id_espacio: int | None = Query(default=None),
    fecha: date | None = Query(default=None),
    estado: str | None = Query(default=None),
    id_usuario: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ReservaEspacio]:
    """Lista reservas, filtrables por espacio, fecha, estado y/o usuario."""
    stmt = select(ReservaEspacio)
    if id_espacio is not None:
        stmt = stmt.where(ReservaEspacio.id_espacio == id_espacio)
    if fecha is not None:
        stmt = stmt.where(ReservaEspacio.fecha_reserva == fecha)
    if estado is not None:
        stmt = stmt.where(ReservaEspacio.estado_reserva == estado)
    if id_usuario is not None:
        stmt = stmt.where(ReservaEspacio.id_usuario == id_usuario)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.patch(
    "/reservas/{id_reserva}/estado",
    response_model=ReservaEspacioResponse,
)
async def actualizar_estado_reserva(
    id_reserva: int,
    payload: ReservaEspacioUpdateStatus,
    db: AsyncSession = Depends(get_db),
) -> ReservaEspacio:
    """Aplica una transición válida del ciclo de vida de una reserva (RES-05)."""
    reserva = (
        await db.execute(
            select(ReservaEspacio)
            .where(ReservaEspacio.id_reserva == id_reserva)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if reserva is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reserva con id={id_reserva} no encontrada.",
        )
    await _bloquear_espacio(db, reserva.id_espacio)

    estado_actual = EstadoReserva(reserva.estado_reserva)
    if payload.nuevo_estado not in _TRANSICIONES_RESERVA[estado_actual]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede cambiar una reserva de '{estado_actual.value}' "
                f"a '{payload.nuevo_estado.value}'."
            ),
        )

    if payload.nuevo_estado in {EstadoReserva.APROBADA, EstadoReserva.EN_USO}:
        await _validar_sin_reservas_solapadas(db, reserva)
        await _validar_reserva_no_bloqueada(db, reserva)

    reserva.estado_reserva = payload.nuevo_estado.value
    if payload.motivo_rechazo:
        reserva.motivo = payload.motivo_rechazo
    try:
        await db.flush()
        if payload.nuevo_estado == EstadoReserva.APROBADA:
            stmt = select(ReservaEspacio).where(
                ReservaEspacio.id_espacio == reserva.id_espacio,
                ReservaEspacio.fecha_reserva == reserva.fecha_reserva,
                ReservaEspacio.estado_reserva == "Pendiente",
                ReservaEspacio.id_reserva != reserva.id_reserva,
                ReservaEspacio.hora_inicio < reserva.hora_fin,
                ReservaEspacio.hora_fin > reserva.hora_inicio,
            )
            solapadas = (await db.execute(stmt)).scalars().all()
            for otra in solapadas:
                otra.estado_reserva = "Rechazada"
                otra.motivo = (
                    "Reserva descartada automáticamente: el espacio fue "
                    "adjudicado a otra solicitud para la misma franja horaria."
                )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede completar el cambio: el espacio ya está ocupado en esa franja horaria.",
        ) from exc
    await db.refresh(reserva)
    return reserva


# ---------------------------------------------------------------------------
# Bloqueos administrativos (RES-04 / GLO-04)
# ---------------------------------------------------------------------------
@router.post(
    "/bloqueos",
    response_model=BloqueoEspacioResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_bloqueo(
    payload: BloqueoEspacioCreate,
    db: AsyncSession = Depends(get_db),
) -> BloqueoEspacio:
    """Bloquea un espacio por contingencia o mantenimiento."""
    await _bloquear_espacio(db, payload.id_espacio)
    bloqueo = BloqueoEspacio(**payload.model_dump())
    stmt = select(ReservaEspacio).where(
        ReservaEspacio.id_espacio == payload.id_espacio,
        ReservaEspacio.fecha_reserva >= payload.fecha_inicio,
        ReservaEspacio.fecha_reserva <= payload.fecha_fin,
        ReservaEspacio.estado_reserva.in_(["Aprobada", "En_Uso"]),
    )
    reservas = (await db.execute(stmt)).scalars().all()
    if any(
        bloqueo_solapa_reserva(bloqueo, reserva)
        for reserva in reservas
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede crear el bloqueo: existe una reserva aprobada o en uso en esa franja.",
        )
    db.add(bloqueo)
    await db.commit()
    await db.refresh(bloqueo)
    return bloqueo


@router.get("/bloqueos", response_model=list[BloqueoEspacioResponse])
async def listar_bloqueos(
    id_espacio: int | None = Query(default=None),
    fecha: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[BloqueoEspacio]:
    """Lista bloqueos, filtrables por espacio y/o fecha (solapamiento de rango)."""
    stmt = select(BloqueoEspacio)
    if id_espacio is not None:
        stmt = stmt.where(BloqueoEspacio.id_espacio == id_espacio)
    if fecha is not None:
        stmt = stmt.where(
            BloqueoEspacio.fecha_inicio <= fecha,
            BloqueoEspacio.fecha_fin >= fecha,
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Disponibilidad (RES-01)
# ---------------------------------------------------------------------------
@router.get("/disponibilidad")
async def consultar_disponibilidad(
    id_sede: int = Query(...),
    fecha: date = Query(...),
    id_espacio: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Devuelve las franjas ocupadas y libres para cada espacio consultado.

    Los turnos libres se derivan de 09:00–16:00 hs (GLO-02), sin asumir
    una duración fija entre reservas. Los bloqueos parciales se aplican
    en cada fecha incluida en su rango.
    """
    stmt_espacios = select(Espacio).where(Espacio.id_sede == id_sede)
    if id_espacio is not None:
        stmt_espacios = stmt_espacios.where(Espacio.id_espacio == id_espacio)
    espacios = list((await db.execute(stmt_espacios)).scalars().all())
    ids_espacios = [espacio.id_espacio for espacio in espacios]

    reservas: list[ReservaEspacio] = []
    bloqueos: list[BloqueoEspacio] = []
    if ids_espacios:
        stmt_res = select(ReservaEspacio).where(
            ReservaEspacio.fecha_reserva == fecha,
            ReservaEspacio.estado_reserva.in_(["Aprobada", "En_Uso"]),
            ReservaEspacio.id_espacio.in_(ids_espacios),
        )
        stmt_blo = select(BloqueoEspacio).where(
            BloqueoEspacio.fecha_inicio <= fecha,
            BloqueoEspacio.fecha_fin >= fecha,
            BloqueoEspacio.id_espacio.in_(ids_espacios),
        )
        reservas = list((await db.execute(stmt_res)).scalars().all())
        bloqueos = list((await db.execute(stmt_blo)).scalars().all())

    intervalos_por_espacio = []
    for espacio in espacios:
        ocupados = [
            (reserva.hora_inicio, reserva.hora_fin)
            for reserva in reservas
            if reserva.id_espacio == espacio.id_espacio
        ]
        ocupados.extend(
            intervalo
            for bloqueo in bloqueos
            if bloqueo.id_espacio == espacio.id_espacio
            if (intervalo := bloqueo_intervalo_en_fecha(bloqueo, fecha)) is not None
        )
        intervalos_por_espacio.append(
            {
                "id_espacio": espacio.id_espacio,
                "intervalos_libres": [
                    {"hora_inicio": inicio, "hora_fin": fin}
                    for inicio, fin in intervalos_libres(ocupados)
                ],
            }
        )

    return {
        "fecha": fecha,
        "id_sede": id_sede,
        "id_espacio": id_espacio,
        "reservas_ocupadas": [ReservaEspacioResponse.model_validate(r) for r in reservas],
        "bloqueos": [BloqueoEspacioResponse.model_validate(b) for b in bloqueos],
        "intervalos_disponibles": intervalos_por_espacio,
    }
