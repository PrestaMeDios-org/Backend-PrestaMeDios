"""SPEC-04 §7 · Migración `0010_inventory_gestion` — INV-23 (guarda de datos).

El esquema que deja la migración (columnas, `CHECK` de locker 1–7, downgrade) lo
verifica `tests/test_migraciones.py` contra PostgreSQL. Acá queda sólo la guarda:
la migración no se aplica si hay lockers fuera de rango.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0010_inventory_gestion.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("inventory_gestion_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op(monkeypatch, modulo, ids: list[int]) -> SimpleNamespace:
    bind = Mock()
    bind.execute.return_value.scalars.return_value.all.return_value = ids
    op = SimpleNamespace(get_bind=Mock(return_value=bind), add_column=Mock(), execute=Mock())
    monkeypatch.setattr(modulo, "op", op)
    return op


def test_upgrade_falla_con_lockers_fuera_de_rango(monkeypatch):  # INV-23
    modulo = _cargar()
    op = _op(monkeypatch, modulo, [4, 9])
    with pytest.raises(RuntimeError, match=r"ids: 4, 9"):
        modulo.upgrade()
    op.add_column.assert_not_called()
    op.execute.assert_not_called()
