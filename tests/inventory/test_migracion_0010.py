"""SPEC-04 §7 · Migración `0010_inventory_gestion` — INV-14 (base) e INV-23."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.modules.inventory.models import Equipamiento, UnidadFisica

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0010_inventory_gestion.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("inventory_gestion_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _bind(ids: list[int]) -> Mock:
    bind = Mock()
    bind.execute.return_value.scalars.return_value.all.return_value = ids
    return bind


def _op(monkeypatch, modulo, ids: list[int]) -> SimpleNamespace:
    op = SimpleNamespace(
        get_bind=Mock(return_value=_bind(ids)),
        add_column=Mock(),
        execute=Mock(),
        create_check_constraint=Mock(),
        drop_constraint=Mock(),
        drop_column=Mock(),
    )
    monkeypatch.setattr(modulo, "op", op)
    return op


def _sql(op: SimpleNamespace) -> str:
    return "\n".join(str(c.args[0]) for c in op.execute.call_args_list)


def test_encadena_con_la_migracion_de_loans():  # INV-23
    modulo = _cargar()
    assert modulo.revision == "0010_inventory_gestion"
    assert modulo.down_revision == "0009_loans_init"


def test_upgrade_agrega_columnas_y_check(monkeypatch):  # INV-23
    modulo = _cargar()
    op = _op(monkeypatch, modulo, [])
    modulo.upgrade()
    columnas = [c.args[1].name for c in op.add_column.call_args_list]
    assert columnas == ["activo", "es_notebook"]
    sql = _sql(op)
    # quita el CHECK viejo con sus dos nombres posibles (create_all y migración 0006)
    assert "DROP CONSTRAINT IF EXISTS ck_unidades_fisicas_locker_positivo" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_unidades_fisicas_ck_unidades_fisicas_locker_positivo" in sql
    assert "ADD CONSTRAINT ck_unidades_fisicas_locker_rango" in sql
    assert "BETWEEN 1 AND 7" in sql


def test_upgrade_falla_con_lockers_fuera_de_rango(monkeypatch):  # INV-23
    modulo = _cargar()
    op = _op(monkeypatch, modulo, [4, 9])
    with pytest.raises(RuntimeError, match=r"ids: 4, 9"):
        modulo.upgrade()
    op.add_column.assert_not_called()
    op.execute.assert_not_called()


def test_downgrade_restaura_el_estado_anterior(monkeypatch):  # INV-23
    modulo = _cargar()
    op = _op(monkeypatch, modulo, [])
    modulo.downgrade()
    sql = _sql(op)
    assert "DROP CONSTRAINT IF EXISTS ck_unidades_fisicas_locker_rango" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_unidades_fisicas_ck_unidades_fisicas_locker_rango" in sql
    assert "ADD CONSTRAINT ck_unidades_fisicas_locker_positivo CHECK (locker >= 1)" in sql
    assert [c.args[1] for c in op.drop_column.call_args_list] == ["es_notebook", "activo"]


def test_el_modelo_refleja_la_migracion():  # INV-14
    nombres = {c.name for c in UnidadFisica.__table__.constraints}
    assert "ck_unidades_fisicas_locker_rango" in nombres
    assert "ck_unidades_fisicas_locker_positivo" not in nombres
    assert {"activo", "es_notebook"} <= set(Equipamiento.__table__.columns.keys())
