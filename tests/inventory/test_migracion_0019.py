"""Migración `0019_inventory_categorias_base` (PRE-01, PRE-14; pedido del Perfil 2).

Como en `tests/loans/test_migracion_0016.py`: se verifican las operaciones sin base de
datos. El ciclo upgrade → downgrade → upgrade contra PostgreSQL se valida aparte, y la
prueba de que Alembic tiene una sola cabeza está en `tests/loans/test_migracion_0011.py`.
"""

import importlib.util
import re
from pathlib import Path
from unittest.mock import Mock

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0019_inventory_categorias_base.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("inventory_categorias_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _ejecutadas(migracion, paso, monkeypatch):
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)
    getattr(migracion, paso)()
    return [c.args[0] for c in op.execute.call_args_list]


def test_encadena_con_la_0018():
    migracion = _cargar()
    assert migracion.revision == "0019_inventory_categorias_base"
    assert migracion.down_revision == "0018_spaces_bloqueos_reversion"


def test_son_las_cinco_categorias_de_la_demo():
    migracion = _cargar()
    assert [nombre for _, nombre, _ in migracion.CATEGORIAS] == [
        "Audio", "Cámaras", "Iluminación", "Notebooks", "Trípodes",
    ]
    for id_, _, color in migracion.CATEGORIAS:
        assert re.fullmatch(r"[a-z0-9-]+", id_)  # el mismo patrón que CategoriaCreate
        assert re.fullmatch(r"#[0-9A-F]{6}", color)


def test_upgrade_no_duplica_ni_pisa(monkeypatch):
    migracion = _cargar()
    sentencias = _ejecutadas(migracion, "upgrade", monkeypatch)
    assert len(sentencias) == 5
    assert all("ON CONFLICT DO NOTHING" in str(s) for s in sentencias)
    assert [s.compile().params["id"] for s in sentencias] == [
        "audio", "cameras", "lighting", "notebooks", "tripods",
    ]


def test_downgrade_no_borra_categorias_en_uso(monkeypatch):
    migracion = _cargar()
    sentencias = _ejecutadas(migracion, "downgrade", monkeypatch)
    assert len(sentencias) == 5
    assert all("NOT EXISTS" in str(s) and "equipamientos" in str(s) for s in sentencias)
