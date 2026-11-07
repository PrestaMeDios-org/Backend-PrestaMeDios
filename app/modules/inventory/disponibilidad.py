"""Disponibilidad por fechas del catálogo (SPEC-04 §5.4, PRE-01).

Único punto de `inventory` que usa `loans` (RN-I16). `inventory/service.py` no debe
importar este módulo ni `loans`, porque `loans/service.py` importa `inventory/service.py`.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta

from app.core.errors import AppError
from app.core.settings import ZONA_HORARIA_LAB
from app.modules.inventory.service import unidades_asignables
from app.modules.loans.service import PeriodoOcupado, ocupacion_de_unidades

# D-07: tope técnico de la consulta (no es una regla del reglamento, P8 no aplica).
MAX_DIAS_DISPONIBILIDAD = 62


def inicio_del_dia(fecha: date) -> datetime:
    return datetime.combine(fecha, time.min, tzinfo=ZONA_HORARIA_LAB)


def validar_rango(desde: date, hasta: date, hoy: date) -> None:
    """422 RANGO_FECHAS_INVALIDO con un detalle por regla (§5.4)."""
    if hasta < desde:
        raise AppError(422, "RANGO_FECHAS_INVALIDO", "La fecha final no puede ser anterior a la inicial.")
    if desde < hoy:
        raise AppError(422, "RANGO_FECHAS_INVALIDO", "El rango no puede empezar antes de hoy.")
    if (hasta - desde).days + 1 > MAX_DIAS_DISPONIBILIDAD:
        raise AppError(422, "RANGO_FECHAS_INVALIDO", "Como máximo 62 días.")


def contar_libres_por_dia(
    desde: date, hasta: date, ocupacion: Mapping[int, Sequence[PeriodoOcupado]]
) -> list[tuple[date, int]]:
    """RN-I15: libre ese día si ningún período se solapa con [00:00, 24:00) local."""
    dias: list[tuple[date, int]] = []
    fecha = desde
    while fecha <= hasta:
        ini, fin = inicio_del_dia(fecha), inicio_del_dia(fecha + timedelta(days=1))
        libres = sum(
            1 for periodos in ocupacion.values()
            if not any(p.desde < fin and p.hasta > ini for p in periodos)
        )
        dias.append((fecha, libres))
        fecha += timedelta(days=1)
    return dias


async def disponibilidad_por_dia(db, equipamiento_id, sede, desde, hasta):
    """RN-I14: unidades asignables hoy menos las ocupadas, por día."""
    ids = await unidades_asignables(db, equipamiento_id, sede)
    ocupacion = await ocupacion_de_unidades(
        db, ids, inicio_del_dia(desde), inicio_del_dia(hasta + timedelta(days=1))
    )
    return len(ids), contar_libres_por_dia(desde, hasta, ocupacion)