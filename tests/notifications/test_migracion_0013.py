"""SPEC-06 §7 · Migración `0013_notifications_init` — NTF-04 y NTF-23.

La base de tests se crea con ``create_all`` (ADR-013): los tests de integración
verifican la estructura que dejan los modelos, y los de la migración verifican
que el script declare lo mismo. El ciclo real ``upgrade`` → ``downgrade -1`` →
``upgrade`` se corre a mano sobre una base de desarrollo (tasks B-A03).
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.enums import SedeEnum
from app.modules.notifications.models import Comunicado, Notificacion

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0013_notifications_init.py"

CHECKS = {
    "ck_comunicados_alcance_coherente",
    "ck_comunicados_vence_despues_de_publicar",
    "ck_comunicados_contenido_largo_maximo",
    "ck_notificaciones_referencia_completa",
}
INDICES = {
    "ix_comunicados_estado_sede_publicado",
    "ix_notificaciones_usuario_creada",
    "ix_notificaciones_no_leidas",
}


def _cargar():
    spec = importlib.util.spec_from_file_location("notifications_init_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op(monkeypatch, modulo) -> MagicMock:
    op = MagicMock()
    monkeypatch.setattr(modulo, "op", op)
    return op


# ── Script de la migración (sin base de datos) ───────────────────────────────


def test_encadena_con_la_cabeza_de_develop():  # NTF-23
    modulo = _cargar()
    assert modulo.revision == "0013_notifications_init"
    assert modulo.down_revision == "0010_inventory_gestion"


def test_upgrade_crea_tablas_indices_y_checks(monkeypatch):  # NTF-23
    modulo = _cargar()
    op = _op(monkeypatch, modulo)
    modulo.upgrade()

    tablas = [c.args[0] for c in op.create_table.call_args_list]
    assert tablas == ["comunicados", "notificaciones"]
    assert {c.args[0] for c in op.create_index.call_args_list} == INDICES
    parcial = next(
        c for c in op.create_index.call_args_list if c.args[0] == "ix_notificaciones_no_leidas"
    )
    assert str(parcial.kwargs["postgresql_where"]) == "leida_en IS NULL"

    sql = "\n".join(str(c.args[0]) for c in op.execute.call_args_list)
    for nombre in CHECKS:
        assert f"ADD CONSTRAINT {nombre} CHECK" in sql


def test_los_checks_del_script_coinciden_con_los_del_modelo():  # NTF-23
    modulo = _cargar()
    del_script = {nombre: condicion for _, nombre, condicion in modulo.CHECKS}
    del_modelo = {
        f"ck_{tabla.name}_{c.name}" if not c.name.startswith("ck_") else c.name: str(c.sqltext)
        for tabla in (Comunicado.__table__, Notificacion.__table__)
        for c in tabla.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert del_script == del_modelo


def test_downgrade_borra_tablas_y_enums_propios(monkeypatch):  # NTF-23
    modulo = _cargar()
    op = _op(monkeypatch, modulo)
    modulo.downgrade()
    assert [c.args[0] for c in op.drop_table.call_args_list] == ["notificaciones", "comunicados"]
    # `sede_enum` es compartido y no se toca.
    assert "sede_enum" not in "\n".join(str(c) for c in op.mock_calls if "drop" in str(c).lower())


# ── Estructura en PostgreSQL (create_all) ────────────────────────────────────


@pytest.mark.integracion
async def test_la_base_tiene_los_checks_e_indices(db):  # NTF-23
    checks = set(
        await db.scalars(
            text(
                "SELECT conname FROM pg_constraint WHERE contype = 'c' "
                "AND conrelid IN ('comunicados'::regclass, 'notificaciones'::regclass)"
            )
        )
    )
    indices = set(
        await db.scalars(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename IN ('comunicados', 'notificaciones') AND indexname LIKE 'ix_%'"
            )
        )
    )
    assert checks == CHECKS
    assert indices == INDICES


@pytest.mark.integracion
@pytest.mark.parametrize(
    ("sede", "es_global"),
    [(SedeEnum.USHUAIA, True), (None, False)],
    ids=["global-con-sede", "sin-sede-ni-global"],
)
async def test_check_alcance_coherente_en_la_base(db, sede, es_global):  # NTF-04
    db.add(Comunicado(titulo="Aviso", contenido="Texto", sede=sede, es_global=es_global))
    with pytest.raises(IntegrityError, match="ck_comunicados_alcance_coherente"):
        await db.commit()
    await db.rollback()
