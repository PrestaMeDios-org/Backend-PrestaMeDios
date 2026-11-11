"""Migración `0016_loans_aval` (SPEC-05 T1.12; AC-L54).

Como en `test_migracion_0011.py`: se verifican las operaciones sin base de datos. El
ciclo upgrade → downgrade → upgrade contra PostgreSQL se valida aparte (S7). La
prueba de que Alembic tiene una sola cabeza está en `test_migracion_0011.py`.
"""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

from app.modules.loans.models import OrdenPedido

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0016_loans_aval.py"
FK = "fk_ordenes_pedido_aval_archivo_id_archivos"


def _cargar():
    spec = importlib.util.spec_from_file_location("loans_aval_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_encadena_con_la_0015():
    migracion = _cargar()
    assert migracion.revision == "0016_loans_aval"
    assert migracion.down_revision == "0015_users_recuperacion"


def test_upgrade_agrega_la_columna_y_la_fk_a_archivos(monkeypatch):
    migracion = _cargar()
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)

    migracion.upgrade()

    (tabla, columna), _ = op.add_column.call_args
    assert (tabla, columna.name, columna.nullable) == ("ordenes_pedido", "aval_archivo_id", True)
    fk = op.create_foreign_key.call_args
    assert fk.args == (FK, "ordenes_pedido", "archivos", ["aval_archivo_id"], ["id"])
    assert fk.kwargs == {"ondelete": "RESTRICT"}


def test_downgrade_borra_la_fk_antes_que_la_columna(monkeypatch):
    migracion = _cargar()
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)

    migracion.downgrade()

    assert [c[0] for c in op.method_calls] == ["drop_constraint", "drop_column"]
    assert op.drop_constraint.call_args.args[0] == FK
    assert op.drop_column.call_args.args == ("ordenes_pedido", "aval_archivo_id")


def test_el_modelo_coincide_con_la_migracion():
    columna = OrdenPedido.__table__.columns["aval_archivo_id"]
    assert columna.nullable
    (fk,) = columna.foreign_keys
    assert (fk.target_fullname, fk.ondelete) == ("archivos.id", "RESTRICT")
