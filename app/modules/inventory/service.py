"""Funciones de servicio públicas de `inventory` (SPEC-04 §6, DT-20).

Las consume `loans` para no escribir el estado de la unidad por su cuenta.
Ninguna hace ``commit``: la transacción es de quien llama.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Integer, any_, bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SedeEnum
from app.core.errors import AppError
from app.modules.inventory.enums import EstadoUnidadEnum
from app.modules.inventory.models import Equipamiento, UnidadFisica

E = EstadoUnidadEnum

# Transiciones que puede pedir un administrador (SPEC-04 §5.3, RN-I3).
# `prestado` es de `loans` y `baja` es terminal (D-02, D-03).
TRANSICIONES_ADMIN: dict[EstadoUnidadEnum, frozenset[EstadoUnidadEnum]] = {
    E.DISPONIBLE: frozenset({E.MANTENIMIENTO, E.BAJA}),
    E.MANTENIMIENTO: frozenset({E.DISPONIBLE, E.BAJA}),
    E.PRESTADO: frozenset(),
    E.BAJA: frozenset(),
}


@dataclass(frozen=True, slots=True)
class DatosEquipamiento:
    """Datos de un ítem del catálogo para otros módulos (C8 de SPEC-05, SPEC-04 §6)."""

    id: int
    codigo: str
    nombre: str
    activo: bool
    es_notebook: bool
    alta_gama: bool
    max_dias_prestamo: int


def unidad_no_encontrada() -> AppError:
    return AppError(404, "UNIDAD_NO_ENCONTRADA", "Unidad física no encontrada.")


def transicion_invalida(desde: EstadoUnidadEnum, hacia: EstadoUnidadEnum) -> AppError:
    return AppError(
        409,
        "TRANSICION_ESTADO_INVALIDA",
        f"No se puede pasar una unidad de '{desde}' a '{hacia}'.",
    )


async def bloquear_unidad(db: AsyncSession, unidad_id: int) -> UnidadFisica | None:
    """Lee la unidad con ``SELECT ... FOR UPDATE`` para serializar cambios (RN-I8)."""
    stmt = (
        select(UnidadFisica)
        .where(UnidadFisica.id == unidad_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return await db.scalar(stmt)


def validar_transicion_admin(desde: EstadoUnidadEnum, hacia: EstadoUnidadEnum) -> None:
    if hacia not in TRANSICIONES_ADMIN[desde]:
        raise transicion_invalida(desde, hacia)


async def unidades_asignables(
    db: AsyncSession, equipamiento_id: int, sede: SedeEnum
) -> list[int]:
    """Ids de unidades ``disponible`` de la sede, de un ítem activo (PRE-14)."""
    stmt = (
        select(UnidadFisica.id)
        .join(Equipamiento, Equipamiento.id == UnidadFisica.equipamiento_id)
        .where(
            UnidadFisica.equipamiento_id == equipamiento_id,
            UnidadFisica.sede == sede,
            UnidadFisica.estado == E.DISPONIBLE,
            Equipamiento.activo.is_(True),
        )
        .order_by(UnidadFisica.codigo_inventario)
    )
    return list((await db.scalars(stmt)).all())


async def unidad_es_asignable(db: AsyncSession, unidad_id: int, sede: SedeEnum) -> bool:
    """¿La unidad está en esa sede, disponible y su ítem activo?"""
    stmt = (
        select(UnidadFisica.id)
        .join(Equipamiento, Equipamiento.id == UnidadFisica.equipamiento_id)
        .where(
            UnidadFisica.id == unidad_id,
            UnidadFisica.sede == sede,
            UnidadFisica.estado == E.DISPONIBLE,
            Equipamiento.activo.is_(True),
        )
    )
    return await db.scalar(stmt) is not None


async def marcar_unidad_prestada(db: AsyncSession, unidad_id: int) -> UnidadFisica:
    """Entrega (PRE-13): ``disponible`` → ``prestado``."""
    unidad = await bloquear_unidad(db, unidad_id)
    if unidad is None:
        raise unidad_no_encontrada()
    if unidad.estado is not E.DISPONIBLE:
        raise transicion_invalida(unidad.estado, E.PRESTADO)
    unidad.estado = E.PRESTADO
    return unidad


async def liberar_unidad(db: AsyncSession, unidad_id: int) -> UnidadFisica:
    """Devolución (PRE-13): ``prestado`` → ``disponible``."""
    unidad = await bloquear_unidad(db, unidad_id)
    if unidad is None:
        raise unidad_no_encontrada()
    if unidad.estado is not E.PRESTADO:
        raise transicion_invalida(unidad.estado, E.DISPONIBLE)
    unidad.estado = E.DISPONIBLE
    return unidad


async def datos_equipamiento_por_ids(
    db: AsyncSession, ids: Iterable[int]
) -> dict[int, DatosEquipamiento]:
    """Datos del catálogo por lote de ids (C8 de SPEC-05; validación de plazos y alta gama).

    Función pública (P3.3, enmienda 1.1.1): `loans` la usa en vez de importar los modelos
    de `inventory`. Es de sólo lectura y global: el catálogo no pertenece a una sede
    (las unidades sí), así que no filtra por sede ni por estado. ``activo`` viaja en el
    resultado y decide quien llama (un ítem dado de baja no se puede pedir, RN-I5).

    - Los ids repetidos se consultan una sola vez; una entrada vacía devuelve ``{}``
      sin consultar la base; los ids inexistentes se omiten.
    - Selecciona sólo las columnas necesarias, no la entidad ``Equipamiento``: no carga
      las unidades ni sus series en la sesión de quien llama.
    - Una sola consulta con los ids en un único parámetro arreglo.
    - No hace ``commit``, ``rollback`` ni ``flush``: la transacción es de quien llama.
    """
    unicos = list(set(ids))
    if not unicos:
        return {}
    filas = await db.execute(
        select(
            Equipamiento.id,
            Equipamiento.codigo,
            Equipamiento.nombre,
            Equipamiento.activo,
            Equipamiento.es_notebook,
            Equipamiento.alta_gama,
            Equipamiento.max_dias_prestamo,
        ).where(Equipamiento.id == any_(bindparam("ids", unicos, type_=ARRAY(Integer))))
    )
    return {
        fila.id: DatosEquipamiento(
            id=fila.id,
            codigo=fila.codigo,
            nombre=fila.nombre,
            activo=fila.activo,
            es_notebook=fila.es_notebook,
            alta_gama=fila.alta_gama,
            max_dias_prestamo=fila.max_dias_prestamo,
        )
        for fila in filas
    }
