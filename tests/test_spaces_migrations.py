"""Verifica que el modelo ORM y la migración protejan ambos estados activos."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy.dialects.postgresql import ExcludeConstraint

from app.modules.spaces.models import ReservaEspacio


def test_modelo_excluye_solapamientos_en_reservas_aprobadas_y_en_uso():
    constraint = next(
        item for item in ReservaEspacio.__table__.constraints if isinstance(item, ExcludeConstraint)
    )
    assert "Aprobada" in str(constraint.where)
    assert "En_Uso" in str(constraint.where)


def test_migracion_actualiza_la_exclusion_para_reservas_en_uso(monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0003_reserva_en_uso.py"
    )
    spec = importlib.util.spec_from_file_location("spaces_en_uso_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    execute = Mock()
    monkeypatch.setattr(migration, "op", SimpleNamespace(execute=execute))

    migration.upgrade()

    statements = "\n".join(str(call.args[0]) for call in execute.call_args_list)
    assert "WHERE (estado_reserva IN ('Aprobada', 'En_Uso'))" in statements
