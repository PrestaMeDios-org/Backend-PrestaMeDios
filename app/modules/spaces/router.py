"""Endpoints REST del módulo `spaces` (Subsistema 3: Reserva de Espacios)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.spaces.models import BloqueoEspacio, Espacio, ReservaEspacio
from app.modules.spaces.schemas import (
    BloqueoEspacioCreate,
    BloqueoEspacioResponse,
    EspacioCreate,
    EspacioResponse,
    ReservaEspacioCreate,
    ReservaEspacioResponse,
    ReservaEspacioUpdateStatus,
)

router = APIRouter()


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

    El solapamiento de reservas 'Aprobadas' sobre el mismo espacio y
    franja es rechazado por la base de datos (ExcludeConstraint GIST);
    se traduce a HTTP 409.
    """
    data = payload.model_dump()
    data["estado_reserva"] = "Pendiente"
    reserva = ReservaEspacio(**data)
    db.add(reserva)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El espacio ya tiene una reserva aprobada en esa franja horaria.",
        ) from exc
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
    """Aprobación/rechazo/cancelación administrativa (RES-05)."""
    reserva = await db.get(ReservaEspacio, id_reserva)
    if reserva is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reserva con id={id_reserva} no encontrada.",
        )
    reserva.estado_reserva = payload.nuevo_estado
    if payload.motivo_rechazo:
        reserva.motivo = payload.motivo_rechazo
    try:
        await db.flush()
        if payload.nuevo_estado == "Aprobada":
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
            detail="No se puede aprobar: ya existe otra reserva aprobada que solapa esa franja.",
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
    bloqueo = BloqueoEspacio(**payload.model_dump())
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
    """Devuelve las franjas ocupadas de un espacio en una fecha.

    Los turnos libres se derivan restando las franjas ocupadas del
    rango operativo 09:00–16:00 hs (GLO-02). Se filtra por ``id_sede``
    a través de la relación espacio↔sede.
    """
    stmt_res = (
        select(ReservaEspacio)
        .join(Espacio, ReservaEspacio.id_espacio == Espacio.id_espacio)
        .where(
            ReservaEspacio.fecha_reserva == fecha,
            ReservaEspacio.estado_reserva.in_(["Aprobada", "En_Uso"]),
            Espacio.id_sede == id_sede,
        )
    )
    stmt_blo = (
        select(BloqueoEspacio)
        .join(Espacio, BloqueoEspacio.id_espacio == Espacio.id_espacio)
        .where(
            BloqueoEspacio.fecha_inicio <= fecha,
            BloqueoEspacio.fecha_fin >= fecha,
            Espacio.id_sede == id_sede,
        )
    )
    if id_espacio is not None:
        stmt_res = stmt_res.where(ReservaEspacio.id_espacio == id_espacio)
        stmt_blo = stmt_blo.where(BloqueoEspacio.id_espacio == id_espacio)

    reservas = (await db.execute(stmt_res)).scalars().all()
    bloqueos = (await db.execute(stmt_blo)).scalars().all()
    return {
        "fecha": fecha,
        "id_sede": id_sede,
        "id_espacio": id_espacio,
        "reservas_ocupadas": [ReservaEspacioResponse.model_validate(r) for r in reservas],
        "bloqueos": [BloqueoEspacioResponse.model_validate(b) for b in bloqueos],
    }
