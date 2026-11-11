"""SPEC-09 §4.2 · Migración ``0017_config_sedes`` — AC-102, AC-103 (migración) y AC-112.

A diferencia de las migraciones de esquema, ``0017`` sólo mueve datos: se corre de
verdad sobre la base de tests con un ``Operations`` de Alembic ligado a la conexión
de la sesión. La base parte del estado anterior a ``0017`` (``_estado_previo``),
porque el fixture ``db`` la siembra con la semilla vigente, que ya la incluye.
"""

import importlib.util
from datetime import time
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import bindparam, select, text

from app.modules.config.models import ParametroGlobal, ParametroGlobalHistorial
from app.modules.config.service import obtener_parametro

pytestmark = pytest.mark.integracion

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0017_config_sedes.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("config_sedes_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M = _cargar()
NUEVAS = [c[0] for c in M.CLAVES_NUEVAS]
DESCRIPCION_ORIGINAL = {
    "horario.apertura": "Hora de apertura operativa del laboratorio (GLO-02).",
    "horario.cierre": "Hora de cierre operativo del laboratorio (GLO-02).",
}


async def _correr(db, paso: str) -> None:
    def _sync(conn) -> None:
        M.op = Operations(MigrationContext.configure(conn))
        getattr(M, paso)()

    conn = await db.connection()
    await conn.run_sync(_sync)
    await db.commit()
    db.expire_all()


async def _estado_previo(db, apertura: str = "09:00", cierre: str = "16:00") -> None:
    """Deja ``parametros_globales`` como estaba antes de ``0017``."""
    await db.execute(
        text("DELETE FROM parametros_globales WHERE clave IN :c").bindparams(
            bindparam("c", expanding=True)
        ),
        {"c": NUEVAS},
    )
    for clave, descripcion in DESCRIPCION_ORIGINAL.items():
        p = await db.get(ParametroGlobal, clave)
        p.editable, p.descripcion = True, descripcion
    (await db.get(ParametroGlobal, "horario.apertura")).valor = apertura
    (await db.get(ParametroGlobal, "horario.cierre")).valor = cierre
    await db.commit()


async def _parametros(db) -> dict[str, ParametroGlobal]:
    filas = await db.scalars(select(ParametroGlobal))
    return {p.clave: p for p in filas.all()}


def test_encadena_con_la_cabeza_de_develop():  # D-22 de SPEC-03
    # `0018_spaces_bloqueos_reversion` (SPEC-08 v1.1.0) entró a `develop` antes que esta
    # migración, así que la 0017 cuelga de ella: 0016 → 0018 → 0017 (plan §8).
    assert M.revision == "0017_config_sedes"
    assert M.down_revision == "0018_spaces_bloqueos_reversion"


async def test_upgrade_copia_el_horario_vigente(db):  # AC-102, D-03, D-05
    await _estado_previo(db, apertura="08:30", cierre="17:00")
    await _correr(db, "upgrade")
    p = await _parametros(db)

    assert set(NUEVAS) <= set(p)
    for sede in ("ushuaia", "rio_grande"):
        assert p[f"horario.{sede}.apertura"].valor == "08:30"
        assert p[f"horario.{sede}.cierre"].valor == "17:00"
        assert p[f"contacto.{sede}.email"].valor == ""
    for clave in NUEVAS:
        assert p[clave].version == 1 and p[clave].editable is True


async def test_upgrade_deja_obsoletas_las_globales(db):  # AC-103 (migración), RN-81
    await _estado_previo(db, apertura="08:30")
    await _correr(db, "upgrade")
    p = await _parametros(db)

    for clave, descripcion in DESCRIPCION_ORIGINAL.items():
        assert p[clave].editable is False
        assert p[clave].descripcion == M.PREFIJO_OBSOLETA + descripcion
    assert await obtener_parametro(db, "horario.apertura") == time(8, 30)


async def test_upgrade_sin_la_clave_global_falla(db):
    await _estado_previo(db)
    await db.execute(text("DELETE FROM parametros_globales WHERE clave = 'horario.cierre'"))
    await db.commit()
    with pytest.raises(RuntimeError, match="horario.cierre"):
        await _correr(db, "upgrade")
    await db.rollback()


async def test_ciclo_upgrade_downgrade_upgrade(db):  # AC-112, P7.4
    await _estado_previo(db)
    await _correr(db, "upgrade")
    db.add(
        ParametroGlobalHistorial(
            clave="horario.rio_grande.apertura",
            valor_anterior="09:00",
            valor_nuevo="10:00",
            version=2,
        )
    )
    await db.commit()

    await _correr(db, "downgrade")
    p = await _parametros(db)
    assert not set(NUEVAS) & set(p)
    for clave, descripcion in DESCRIPCION_ORIGINAL.items():
        assert p[clave].editable is True and p[clave].descripcion == descripcion
    historial = await db.scalars(
        select(ParametroGlobalHistorial).where(ParametroGlobalHistorial.clave.in_(NUEVAS))
    )
    assert historial.all() == []

    await _correr(db, "upgrade")
    p = await _parametros(db)
    assert set(NUEVAS) <= set(p)
    assert p["horario.apertura"].descripcion.count(M.PREFIJO_OBSOLETA) == 1
