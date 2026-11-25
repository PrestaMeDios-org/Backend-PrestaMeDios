"""SPEC-11 plan §5.4 · Migración ``0021_core_envios_correo``.

Como en las demás migraciones: la base de tests se crea con ``create_all`` y estos
tests verifican que el script declare lo mismo que el modelo. El ciclo real
``upgrade → downgrade base → upgrade`` lo corre la CI (D-04).
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from app.core.models import EnvioCorreoDiario

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0021_core_envios_correo.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("core_envios_correo_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_encadena_con_la_cabeza_de_develop():  # regla de C19
    modulo = _cargar()
    assert modulo.revision == "0021_core_envios_correo"
    assert modulo.down_revision == "0020_notifications_portada"


def test_upgrade_crea_la_tabla_del_modelo(monkeypatch):
    modulo = _cargar()
    op = MagicMock()
    monkeypatch.setattr(modulo, "op", op)
    modulo.upgrade()
    llamada = op.create_table.call_args
    assert llamada.args[0] == EnvioCorreoDiario.__tablename__ == "envios_correo_diarios"
    columnas = {c.name: c for c in llamada.args[1:] if hasattr(c, "name") and hasattr(c, "type")}
    assert set(columnas) == {"fecha", "cantidad"}
    assert columnas["fecha"].primary_key
    assert not columnas["cantidad"].nullable
    restricciones = [c for c in llamada.args[1:] if c.__class__.__name__ == "CheckConstraint"]
    assert [str(c.sqltext) for c in restricciones] == ["cantidad >= 0"]


def test_downgrade_borra_la_tabla(monkeypatch):
    modulo = _cargar()
    op = MagicMock()
    monkeypatch.setattr(modulo, "op", op)
    modulo.downgrade()
    op.drop_table.assert_called_once_with("envios_correo_diarios")
