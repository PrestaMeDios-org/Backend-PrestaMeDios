"""Migración `0019_inventory_categorias_base` (PRE-01, PRE-14; pedido del Perfil 2).

Migración de datos: se corre de verdad sobre la base de tests con un ``Operations``
de Alembic ligado a la conexión de la sesión, como ``tests/config/test_migracion_0017.py``.
La cadena y el ciclo de esquema los verifica ``tests/test_migraciones.py``.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select

from app.modules.inventory.models import Categoria
from app.modules.inventory.schemas import CategoriaCreate

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0019_inventory_categorias_base.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("inventory_categorias_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M = _cargar()
IDS = {id_ for id_, _, _ in M.CATEGORIAS}


async def _correr(db, paso: str) -> None:
    def _sync(conn) -> None:
        M.op = Operations(MigrationContext.configure(conn))
        getattr(M, paso)()

    conn = await db.connection()
    await conn.run_sync(_sync)
    await db.commit()
    db.expire_all()


async def _categorias(db) -> dict[str, str]:
    return {c.id: c.nombre for c in (await db.scalars(select(Categoria))).all()}


@pytest.mark.parametrize(("id_", "nombre", "color"), M.CATEGORIAS, ids=[c[0] for c in M.CATEGORIAS])
def test_cada_categoria_se_puede_crear_por_la_api(id_, nombre, color):
    # Las mismas reglas que `POST /categorias`: si no, la categoría base no se podría editar.
    CategoriaCreate(id=id_, nombre=nombre, color=color)


@pytest.mark.integracion
async def test_upgrade_no_duplica_ni_pisa(db):
    db.add(Categoria(id="audio", nombre="Sonido"))  # el administrador la renombró
    db.add(Categoria(id="camaras-viejas", nombre="Cámaras"))  # mismo nombre, otro id
    await db.commit()

    await _correr(db, "upgrade")
    await _correr(db, "upgrade")  # idempotente

    categorias = await _categorias(db)
    assert categorias["audio"] == "Sonido"
    assert "cameras" not in categorias
    assert {"lighting", "notebooks", "tripods"} <= set(categorias)
    assert len(categorias) == 5


@pytest.mark.integracion
async def test_downgrade_no_borra_categorias_en_uso_ni_cambiadas(db, crear_equipo):
    await _correr(db, "upgrade")
    await crear_equipo(categoria="audio")
    (await db.get(Categoria, "cameras")).nombre = "Cámaras de cine"
    await db.commit()

    await _correr(db, "downgrade")

    assert set(await _categorias(db)) == {"audio", "cameras"}
