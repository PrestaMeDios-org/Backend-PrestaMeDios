"""Fábricas compartidas por los tests de `inventory` (SPEC-04)."""

import pytest

from app.core.enums import SedeEnum
from app.modules.inventory.enums import EstadoUnidadEnum
from app.modules.inventory.models import Categoria, Equipamiento, UnidadFisica

USH, RG = SedeEnum.USHUAIA, SedeEnum.RIO_GRANDE
DISP = EstadoUnidadEnum.DISPONIBLE


@pytest.fixture
def crear_equipo(db):
    """Fábrica de ítems. ``unidades``: tuplas ``(sede, estado=disponible, locker=None)``."""

    async def _crear(
        codigo: str = "EQ-1",
        nombre: str = "Cámara",
        *,
        categoria: str = "cameras",
        unidades: tuple[tuple, ...] = (),
        **extra,
    ) -> Equipamiento:
        if await db.get(Categoria, categoria) is None:
            db.add(Categoria(id=categoria, nombre=categoria.capitalize()))
            await db.flush()
        equipo = Equipamiento(
            codigo=codigo,
            nombre=nombre,
            marca=extra.pop("marca", "Sony"),
            modelo=extra.pop("modelo", "X1"),
            categoria_id=categoria,
            **extra,
        )
        equipo.unidades = [
            UnidadFisica(
                numero_serie=f"{codigo}-SN{i}",
                codigo_inventario=f"{codigo}-U{i}",
                sede=u[0],
                estado=u[1] if len(u) > 1 else DISP,
                locker=u[2] if len(u) > 2 else None,
            )
            for i, u in enumerate(unidades, start=1)
        ]
        db.add(equipo)
        await db.commit()
        return equipo

    return _crear
