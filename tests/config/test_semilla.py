"""La copia congelada de la migración 0005 coincide con ``PARAMETROS_SEMILLA`` (SPEC-01 §11.2)."""

import importlib.util
from pathlib import Path

from app.modules.config.seed import PARAMETROS_SEMILLA

_MIGRACION = Path(__file__).parents[2] / "alembic" / "versions" / "0005_users_y_parametros.py"


def test_semilla_de_migracion_coincide_con_la_app():
    spec = importlib.util.spec_from_file_location("migracion_0005", _MIGRACION)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    app_semilla = [
        (p["clave"], p["tipo"], p["valor"], p["descripcion"], p["unidad"], p["valor_min"], p["valor_max"])
        for p in PARAMETROS_SEMILLA
    ]
    assert modulo.PARAMETROS_SEMILLA == app_semilla
