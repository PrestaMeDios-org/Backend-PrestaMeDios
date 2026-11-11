"""Migración `0018_spaces_bloqueos_reversion` (SPEC-08 v1.1.0, GLO-04; D-S01, D-S03).

Como en `tests/loans/test_migracion_0016.py`: se verifican las operaciones sin base de
datos. El ciclo upgrade → downgrade → upgrade contra PostgreSQL se valida aparte, y la
prueba de que Alembic tiene una sola cabeza está en `tests/loans/test_migracion_0011.py`.
"""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

from app.modules.spaces.models import BloqueoEspacio

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0018_spaces_bloqueos_reversion.py"
TABLA = "bloqueos_espacios"
FK = "fk_bloqueos_espacios_revertido_por_usuarios"
IX = "ix_bloqueos_espacios_id_grupo"


def _cargar():
    spec = importlib.util.spec_from_file_location("spaces_reversion_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_encadena_con_la_0016():
    migracion = _cargar()
    assert migracion.revision == "0018_spaces_bloqueos_reversion"
    assert migracion.down_revision == "0016_loans_aval"


def test_upgrade_agrega_columnas_nulables_fk_e_indice(monkeypatch):
    migracion = _cargar()
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)

    migracion.upgrade()

    columnas = [(c.args[0], c.args[1].name, c.args[1].nullable) for c in op.add_column.call_args_list]
    assert columnas == [
        (TABLA, "id_grupo", True),
        (TABLA, "revertido_en", True),
        (TABLA, "revertido_por", True),
    ]
    fk = op.create_foreign_key.call_args
    assert fk.args == (FK, TABLA, "usuarios", ["revertido_por"], ["id"])
    assert fk.kwargs == {"ondelete": "SET NULL"}
    assert op.create_index.call_args.args == (IX, TABLA, ["id_grupo"])


def test_downgrade_deshace_en_orden_inverso(monkeypatch):
    migracion = _cargar()
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)

    migracion.downgrade()

    assert [c[0] for c in op.method_calls] == [
        "drop_index", "drop_constraint", "drop_column", "drop_column", "drop_column",
    ]
    assert op.drop_constraint.call_args.args[0] == FK


def test_el_modelo_coincide_con_la_migracion():
    columnas = BloqueoEspacio.__table__.columns
    assert all(columnas[c].nullable for c in ("id_grupo", "revertido_en", "revertido_por"))
    assert columnas["id_grupo"].index
    (fk,) = columnas["revertido_por"].foreign_keys
    assert (fk.target_fullname, fk.ondelete) == ("usuarios.id", "SET NULL")
