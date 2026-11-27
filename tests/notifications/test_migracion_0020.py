"""Portada de los comunicados (SPEC-06 §15; SPEC-10 M-02, §4.7) · Migración ``0020_notifications_portada``.

Se corre de verdad sobre la base de tests con un ``Operations`` de Alembic ligado a la
conexión de la sesión, como ``tests/config/test_migracion_0017.py``. La base parte con
``comunicados_portada`` creada por ``create_all``: el test baja, verifica que sólo se fue
esa tabla, y vuelve a subir.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.enums import SedeEnum

pytestmark = pytest.mark.integracion

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0020_notifications_portada.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("notifications_portada_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M = _cargar()


async def _correr(db, paso: str) -> None:
    def _sync(conn) -> None:
        M.op = Operations(MigrationContext.configure(conn))
        getattr(M, paso)()

    conn = await db.connection()
    await conn.run_sync(_sync)
    await db.commit()


async def _tablas(db) -> set[str]:
    conn = await db.connection()
    return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def _restricciones(db) -> set[str]:
    conn = await db.connection()

    def _sync(c) -> set[str]:
        i = inspect(c)
        return {r["name"] for r in i.get_check_constraints("comunicados_portada")} | {
            r["name"] for r in i.get_foreign_keys("comunicados_portada")
        }

    return await conn.run_sync(_sync)


def test_encadena_con_la_cabeza_de_develop():
    assert M.revision == "0020_notifications_portada"
    assert M.down_revision == "0019_inventory_categorias_base"


async def test_downgrade_solo_borra_su_tabla_y_upgrade_la_recrea(db, crear_comunicado):
    c = await crear_comunicado(SedeEnum.USHUAIA)
    antes = await _tablas(db)
    assert "comunicados_portada" in antes

    await _correr(db, "downgrade")
    despues = await _tablas(db)
    assert despues == antes - {"comunicados_portada"}  # `comunicados` y el resto, intactos
    assert await db.scalar(text("SELECT count(*) FROM comunicados WHERE id = :id"), {"id": c.id}) == 1

    await _correr(db, "upgrade")
    assert await _tablas(db) == antes
    assert {
        "ck_comunicados_portada_tema_valido",
        "ck_comunicados_portada_tema_o_imagen",
        "fk_comunicados_portada_comunicado_id_comunicados",
    } <= await _restricciones(db)


async def test_upgrade_exige_tema_o_imagen(db, crear_comunicado):
    c = await crear_comunicado(SedeEnum.USHUAIA)
    await _correr(db, "downgrade")
    await _correr(db, "upgrade")

    await db.execute(
        text("INSERT INTO comunicados_portada (comunicado_id, tema) VALUES (:id, 'azul')"), {"id": c.id}
    )
    await db.commit()
    with pytest.raises(IntegrityError):  # ni tema ni imagen
        await db.execute(text("UPDATE comunicados_portada SET tema = NULL WHERE comunicado_id = :id"), {"id": c.id})
        await db.commit()
    await db.rollback()
