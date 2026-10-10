"""Endpoints REST del módulo `inventory` (Catálogo y Existencias; SPEC-02 §4).

- Todos exigen sesión (RN-24).
- Lectura con alcance de sede: las unidades visibles son las de la jurisdicción
  del usuario (GLO-01); el catálogo (`equipamientos`, `categorias`) es global.
- Escritura sólo para administradores; la sede de las unidades nuevas es
  automática para ``ADMIN_LOCAL`` (PRE-19, RN-31).
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import (
    get_current_user,
    puede_ver_sede,
    require_roles,
    resolver_alcance_sede,
    sede_para_alta,
)
from app.core.enums import ROLES_ADMIN, RolUsuario
from app.core.errors import AppError, error_responses
from app.database import get_db
from app.modules.config.service import obtener_parametro
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
from app.modules.users.models import Usuario

router = APIRouter()

_solo_admins = require_roles(RolUsuario.ADMIN_LOCAL, RolUsuario.SUPERADMIN)


def _equipamiento_no_encontrado() -> AppError:
    return AppError(404, "EQUIPAMIENTO_NO_ENCONTRADO", "Equipamiento no encontrado.")


def _unidad_no_encontrada() -> AppError:
    return AppError(404, "UNIDAD_NO_ENCONTRADA", "Unidad física no encontrada.")


async def _commit_or_409(db: AsyncSession, code: str, detail: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(409, code, detail) from exc


async def _commit_inventario(db: AsyncSession) -> None:
    await _commit_or_409(
        db,
        "INVENTARIO_DUPLICADO",
        "Número de serie, código de inventario o código ya registrado.",
    )


def _unidad(datos: UnidadFisicaCreate, actor: Usuario, **extra: object) -> UnidadFisica:
    valores = datos.model_dump(exclude={"sede"})
    return UnidadFisica(**valores, sede=sede_para_alta(actor, datos.sede), **extra)


# ── Categorías ───────────────────────────────────────────────────────────────


@router.get(
    "/categorias",
    response_model=list[CategoriaResponse],
    summary="Listar categorías",
    dependencies=[Depends(get_current_user)],
    responses=error_responses(401),
)
async def listar_categorias(db: AsyncSession = Depends(get_db)) -> list[Categoria]:
    result = await db.scalars(select(Categoria).order_by(Categoria.nombre))
    return list(result.all())


@router.post(
    "/categorias",
    response_model=CategoriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear categoría",
    dependencies=[Depends(_solo_admins)],
    responses=error_responses(401, 403, 409),
)
async def crear_categoria(
    payload: CategoriaCreate,
    db: AsyncSession = Depends(get_db),
) -> Categoria:
    categoria = Categoria(**payload.model_dump())
    db.add(categoria)
    await _commit_or_409(db, "CATEGORIA_DUPLICADA", "La categoría ya existe.")
    return categoria


# ── Equipamiento ─────────────────────────────────────────────────────────────


def _stmt_equipamiento_en_alcance(actor: Usuario, sede: SedeEnum | None):
    """Unidades acotadas al alcance; ítems sin unidades visibles sólo para admins (PRE-01, PRE-12)."""
    sedes = resolver_alcance_sede(actor, sede)
    visible = Equipamiento.unidades.any(UnidadFisica.sede.in_(sedes))
    if actor.rol in ROLES_ADMIN:
        visible = or_(visible, ~Equipamiento.unidades.any())
    return (
        select(Equipamiento)
        .where(visible)
        .options(selectinload(Equipamiento.unidades.and_(UnidadFisica.sede.in_(sedes))))
    )


@router.get(
    "/equipamiento",
    response_model=list[EquipamientoResponse],
    summary="Catálogo de equipamiento de la sede",
    responses=error_responses(401, 403),
)
async def listar_equipamiento(
    sede: SedeEnum | None = Query(default=None),
    categoria: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Equipamiento]:
    """Lista el catálogo con el stock calculado sobre las unidades de la jurisdicción.

    - ``sede``: sólo el Superadministrador puede elegirla; el resto opera en la suya.
    - ``categoria``: id de categoría (coincidencia exacta).
    - ``q``: búsqueda por nombre, código o marca.
    """
    stmt = _stmt_equipamiento_en_alcance(actor, sede).order_by(Equipamiento.nombre)
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


@router.get(
    "/equipamiento/{equipamiento_id}",
    response_model=EquipamientoResponse,
    summary="Detalle de un ítem del catálogo",
    responses=error_responses(401, 403, 404),
)
async def obtener_equipamiento(
    equipamiento_id: int,
    sede: SedeEnum | None = Query(default=None),
    actor: Usuario = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Equipamiento:
    stmt = _stmt_equipamiento_en_alcance(actor, sede).where(Equipamiento.id == equipamiento_id)
    equipamiento = await db.scalar(stmt)
    if equipamiento is None:
        raise _equipamiento_no_encontrado()
    return equipamiento


@router.post(
    "/equipamiento",
    response_model=EquipamientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de equipamiento (con unidades opcionales)",
    responses=error_responses(401, 403, 409, 422),
)
async def crear_equipamiento(
    payload: EquipamientoCreate,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> Equipamiento:
    """PRE-19 en cada unidad; plazo por defecto desde ``prestamo.general.max_dias`` (GLO-03)."""
    if await db.get(Categoria, payload.categoria_id) is None:
        raise AppError(
            422, "CATEGORIA_INEXISTENTE", f"La categoría '{payload.categoria_id}' no existe."
        )
    datos = payload.model_dump(exclude={"unidades", "max_dias_prestamo"})
    max_dias = payload.max_dias_prestamo
    if max_dias is None:
        max_dias = int(await obtener_parametro(db, "prestamo.general.max_dias"))

    equipamiento = Equipamiento(**datos, max_dias_prestamo=max_dias)
    equipamiento.unidades = [_unidad(u, actor) for u in payload.unidades]
    db.add(equipamiento)
    await _commit_inventario(db)
    await db.refresh(equipamiento, attribute_names=["unidades"])
    return equipamiento


@router.post(
    "/equipamiento/{equipamiento_id}/unidades",
    response_model=UnidadFisicaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta de una unidad física",
    responses=error_responses(401, 403, 404, 409),
)
async def agregar_unidad(
    equipamiento_id: int,
    payload: UnidadFisicaCreate,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> UnidadFisica:
    existe = await db.scalar(select(Equipamiento.id).where(Equipamiento.id == equipamiento_id))
    if existe is None:
        raise _equipamiento_no_encontrado()
    unidad = _unidad(payload, actor, equipamiento_id=equipamiento_id)
    db.add(unidad)
    await _commit_inventario(db)
    return unidad


# ── Unidades (stock, PRE-12 / PRE-14) ────────────────────────────────────────


@router.get(
    "/unidades",
    response_model=list[UnidadFisicaResponse],
    summary="Stock de unidades físicas (administración)",
    responses=error_responses(401, 403),
)
async def listar_unidades(
    sede: SedeEnum | None = Query(default=None),
    estado: EstadoUnidadEnum | None = Query(default=None),
    equipamiento_id: int | None = Query(default=None),
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> list[UnidadFisica]:
    stmt = (
        select(UnidadFisica)
        .where(UnidadFisica.sede.in_(resolver_alcance_sede(actor, sede)))
        .order_by(UnidadFisica.codigo_inventario)
    )
    if estado is not None:
        stmt = stmt.where(UnidadFisica.estado == estado)
    if equipamiento_id is not None:
        stmt = stmt.where(UnidadFisica.equipamiento_id == equipamiento_id)
    result = await db.scalars(stmt)
    return list(result.all())


@router.patch(
    "/unidades/{unidad_id}/estado",
    response_model=UnidadFisicaResponse,
    summary="Cambiar el estado de una unidad (mantenimiento, baja, disponible)",
    responses=error_responses(401, 403, 404),
)
async def cambiar_estado_unidad(
    unidad_id: int,
    payload: UnidadFisicaEstadoUpdate,
    actor: Usuario = Depends(_solo_admins),
    db: AsyncSession = Depends(get_db),
) -> UnidadFisica:
    """Cambia el estado de una unidad (PRE-14).

    El botón "Fuera de servicio" del panel envía ``estado="mantenimiento"``;
    para rehabilitarla se envía ``estado="disponible"``.
    """
    unidad = await db.get(UnidadFisica, unidad_id)
    if unidad is None or not puede_ver_sede(actor, unidad.sede):
        raise _unidad_no_encontrada()
    unidad.estado = payload.estado
    await db.commit()
    return unidad
