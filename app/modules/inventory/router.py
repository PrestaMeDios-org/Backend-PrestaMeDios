"""Endpoints REST del módulo `inventory` (Catálogo y Existencias)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.inventory.models import Equipamiento, UnidadFisica
from app.modules.inventory.schemas import (
    EquipamientoCreate,
    EquipamientoResponse,
    EstadoUnidadEnum,
    SedeEnum,
    UnidadFisicaCreate,
    UnidadFisicaResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Equipamiento (catálogo)
# ---------------------------------------------------------------------------
@router.get("/equipamiento", response_model=list[EquipamientoResponse])
async def listar_equipamiento(
    sede: SedeEnum | None = Query(default=None),
    categoria: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[Equipamiento]:
    """Lista el catálogo de equipamiento.

    Filtros opcionales:
    - ``sede``: equipamientos con al menos una unidad física en esa sede.
    - ``categoria``: coincidencia exacta de categoría.
    """
    stmt = select(Equipamiento)
    if sede is not None:
        stmt = stmt.where(Equipamiento.unidades.any(UnidadFisica.sede == sede))
    if categoria is not None:
        stmt = stmt.where(Equipamiento.categoria == categoria)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/equipamiento",
    response_model=EquipamientoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_equipamiento(
    payload: EquipamientoCreate,
    db: AsyncSession = Depends(get_db),
) -> Equipamiento:
    """Da de alta un ítem del catálogo, opcionalmente con sus unidades físicas."""
    equipamiento = Equipamiento(**payload.model_dump(exclude={"unidades"}))
    equipamiento.unidades = [
        UnidadFisica(**unidad.model_dump()) for unidad in payload.unidades
    ]
    db.add(equipamiento)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="numero_serie o codigo_inventario ya registrado.",
        ) from exc

    result = await db.execute(
        select(Equipamiento).where(Equipamiento.id == equipamiento.id)
    )
    return result.scalar_one()


@router.post(
    "/equipamiento/{equipamiento_id}/unidades",
    response_model=UnidadFisicaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def agregar_unidad(
    equipamiento_id: int,
    payload: UnidadFisicaCreate,
    db: AsyncSession = Depends(get_db),
) -> UnidadFisica:
    """Da de alta una unidad física asociada a un equipamiento existente."""
    equipamiento = await db.get(Equipamiento, equipamiento_id)
    if equipamiento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Equipamiento con id={equipamiento_id} no encontrado.",
        )

    unidad = UnidadFisica(**payload.model_dump(), equipamiento_id=equipamiento_id)
    db.add(unidad)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="numero_serie o codigo_inventario ya registrado.",
        ) from exc

    await db.refresh(unidad)
    return unidad


# ---------------------------------------------------------------------------
# Unidades físicas (existencias / stock)
# ---------------------------------------------------------------------------
@router.get("/unidades", response_model=list[UnidadFisicaResponse])
async def listar_unidades(
    sede: SedeEnum | None = Query(default=None),
    estado: EstadoUnidadEnum | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[UnidadFisica]:
    """Lista las unidades físicas, filtrables por ``sede`` y/o ``estado``."""
    stmt = select(UnidadFisica)
    if sede is not None:
        stmt = stmt.where(UnidadFisica.sede == sede)
    if estado is not None:
        stmt = stmt.where(UnidadFisica.estado == estado)
    result = await db.execute(stmt)
    return list(result.scalars().all())
