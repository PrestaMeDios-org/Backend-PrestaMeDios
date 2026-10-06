"""Endpoints REST del módulo `inventory` (Catálogo y Existencias)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.modules.inventory.enums import EstadoUnidadEnum, SedeEnum
from app.modules.inventory.models import Categoria, Equipamiento, UnidadFisica
from app.modules.inventory.schemas import (
    CategoriaCreate,
    CategoriaResponse,
    EquipamientoCreate,
    EquipamientoResponse,
    UnidadFisicaCreate,
    UnidadFisicaEstadoUpdate,
    UnidadFisicaResponse,
)

router = APIRouter()

_DUPLICADO = "numero_serie, codigo_inventario o codigo ya registrado."


async def _commit_or_409(db: AsyncSession, detail: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------
@router.get("/categorias", response_model=list[CategoriaResponse])
async def listar_categorias(db: AsyncSession = Depends(get_db)) -> list[Categoria]:
    result = await db.scalars(select(Categoria).order_by(Categoria.nombre))
    return list(result.all())


@router.post(
    "/categorias",
    response_model=CategoriaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_categoria(
    payload: CategoriaCreate,
    db: AsyncSession = Depends(get_db),
) -> Categoria:
    categoria = Categoria(**payload.model_dump())
    db.add(categoria)
    await _commit_or_409(db, "La categoría ya existe.")
    return categoria


# ---------------------------------------------------------------------------
# Equipamiento (catálogo)
# ---------------------------------------------------------------------------
@router.get("/equipamiento", response_model=list[EquipamientoResponse])
async def listar_equipamiento(
    sede: SedeEnum | None = Query(default=None),
    categoria: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> list[Equipamiento]:
    """Lista el catálogo.

    - ``sede``: sólo ítems con unidades en esa sede, y **sólo** esas unidades
      en la respuesta (el stock calculado queda acotado a la sede).
    - ``categoria``: id de categoría (coincidencia exacta).
    - ``q``: búsqueda por nombre, código o marca.
    """
    stmt = select(Equipamiento).order_by(Equipamiento.nombre)
    if sede is not None:
        stmt = stmt.where(Equipamiento.unidades.any(UnidadFisica.sede == sede)).options(
            selectinload(Equipamiento.unidades.and_(UnidadFisica.sede == sede))
        )
    if categoria is not None:
        stmt = stmt.where(Equipamiento.categoria_id == categoria)
    if q is not None:
        patron = f"%{q}%"
        stmt = stmt.where(
            or_(
                Equipamiento.nombre.ilike(patron),
                Equipamiento.codigo.ilike(patron),
                Equipamiento.marca.ilike(patron),
            )
        )
    result = await db.scalars(stmt)
    return list(result.all())


@router.get("/equipamiento/{equipamiento_id}", response_model=EquipamientoResponse)
async def obtener_equipamiento(
    equipamiento_id: int,
    sede: SedeEnum | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Equipamiento:
    stmt = select(Equipamiento).where(Equipamiento.id == equipamiento_id)
    if sede is not None:
        stmt = stmt.options(selectinload(Equipamiento.unidades.and_(UnidadFisica.sede == sede)))
    equipamiento = await db.scalar(stmt)
    if equipamiento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Equipamiento con id={equipamiento_id} no encontrado.",
        )
    return equipamiento


@router.post(
    "/equipamiento",
    response_model=EquipamientoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_equipamiento(
    payload: EquipamientoCreate,
    db: AsyncSession = Depends(get_db),
) -> Equipamiento:
    if await db.get(Categoria, payload.categoria_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"La categoría '{payload.categoria_id}' no existe.",
        )

    equipamiento = Equipamiento(**payload.model_dump(exclude={"unidades"}))
    equipamiento.unidades = [UnidadFisica(**u.model_dump()) for u in payload.unidades]
    db.add(equipamiento)
    await _commit_or_409(db, _DUPLICADO)
    return equipamiento


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
    existe = await db.scalar(select(Equipamiento.id).where(Equipamiento.id == equipamiento_id))
    if existe is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Equipamiento con id={equipamiento_id} no encontrado.",
        )

    unidad = UnidadFisica(**payload.model_dump(), equipamiento_id=equipamiento_id)
    db.add(unidad)
    await _commit_or_409(db, _DUPLICADO)
    return unidad


# ---------------------------------------------------------------------------
# Unidades físicas (existencias / stock)
# ---------------------------------------------------------------------------
@router.get("/unidades", response_model=list[UnidadFisicaResponse])
async def listar_unidades(
    sede: SedeEnum | None = Query(default=None),
    estado: EstadoUnidadEnum | None = Query(default=None),
    equipamiento_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[UnidadFisica]:
    stmt = select(UnidadFisica).order_by(UnidadFisica.codigo_inventario)
    if sede is not None:
        stmt = stmt.where(UnidadFisica.sede == sede)
    if estado is not None:
        stmt = stmt.where(UnidadFisica.estado == estado)
    if equipamiento_id is not None:
        stmt = stmt.where(UnidadFisica.equipamiento_id == equipamiento_id)
    result = await db.scalars(stmt)
    return list(result.all())


@router.patch("/unidades/{unidad_id}/estado", response_model=UnidadFisicaResponse)
async def cambiar_estado_unidad(
    unidad_id: int,
    payload: UnidadFisicaEstadoUpdate,
    db: AsyncSession = Depends(get_db),
) -> UnidadFisica:
    """Cambia el estado de una unidad (PRE-14).

    El botón "Fuera de servicio" del panel envía ``estado="mantenimiento"``;
    para rehabilitarla se envía ``estado="disponible"``.
    """
    unidad = await db.get(UnidadFisica, unidad_id)
    if unidad is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unidad física con id={unidad_id} no encontrada.",
        )
    unidad.estado = payload.estado
    await db.commit()
    return unidad
