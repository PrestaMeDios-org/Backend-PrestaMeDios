"""Migración `0011_loans_resolucion` (SPEC-05 Fase 2, §7.2; AC-L54).

Como en `tests/inventory/test_migracion_0010.py`, se carga el archivo y se
verifican sus operaciones sin base de datos. El ciclo upgrade → downgrade →
upgrade contra PostgreSQL se valida aparte, con una base temporal (S7).
"""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.modules.loans.models import OrdenHistorialEstado, OrdenPedido

RAIZ = Path(__file__).parents[2]
RUTA = RAIZ / "alembic" / "versions" / "0011_loans_resolucion.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("loans_resolucion_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op_falso(monkeypatch, migracion) -> Mock:
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)
    return op


def _nombres(op: Mock, metodo: str) -> list:
    return [c.args[0] for c in getattr(op, metodo).call_args_list]


def test_encadena_con_la_0013():  # C19: la 0013 (SPEC-06) entró antes a develop
    migracion = _cargar()
    assert migracion.revision == "0011_loans_resolucion"
    assert migracion.down_revision == "0013_notifications_init"


def test_alembic_tiene_una_sola_cabeza():  # C19: falla si otra migración cuelga de la misma base
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_upgrade_agrega_la_resolucion_y_el_historial(monkeypatch):
    migracion = _cargar()
    op = _op_falso(monkeypatch, migracion)

    migracion.upgrade()

    columnas = [(c.args[0], c.args[1].name) for c in op.add_column.call_args_list]
    assert columnas == [("ordenes_pedido", "resuelto_por_id"), ("ordenes_pedido", "resuelto_en")]
    fk = op.create_foreign_key.call_args
    assert fk.args[:5] == (
        "fk_ordenes_pedido_resuelto_por_id_usuarios",
        "ordenes_pedido",
        "usuarios",
        ["resuelto_por_id"],
        ["id"],
    )
    assert fk.kwargs == {"ondelete": "SET NULL"}
    assert _nombres(op, "create_table") == ["ordenes_historial_estado"]
    assert _nombres(op, "create_index") == ["ix_ordenes_historial_estado_orden_id_created_at"]


def test_el_historial_reusa_el_enum_de_la_orden_sin_crearlo():
    migracion = _cargar()
    assert migracion.estado_orden_enum.name == "estado_orden_enum"
    assert migracion.estado_orden_enum.create_type is False


def test_downgrade_deshace_todo_en_orden_inverso(monkeypatch):
    migracion = _cargar()
    op = _op_falso(monkeypatch, migracion)

    migracion.downgrade()

    assert _nombres(op, "drop_index") == ["ix_ordenes_historial_estado_orden_id_created_at"]
    assert _nombres(op, "drop_table") == ["ordenes_historial_estado"]
    assert _nombres(op, "drop_constraint") == ["fk_ordenes_pedido_resuelto_por_id_usuarios"]
    assert [c.args[1] for c in op.drop_column.call_args_list] == ["resuelto_en", "resuelto_por_id"]
    nombres_llamados = [c[0] for c in op.method_calls]
    assert nombres_llamados.index("drop_table") < nombres_llamados.index("drop_column")


def test_el_modelo_coincide_con_la_migracion():
    columnas = OrdenPedido.__table__.columns
    assert columnas["resuelto_por_id"].nullable
    assert columnas["resuelto_en"].nullable
    historial = OrdenHistorialEstado.__table__
    assert set(historial.columns.keys()) == {
        "id",
        "orden_id",
        "estado_anterior",
        "estado_nuevo",
        "motivo",
        "actor_id",
        "created_at",
    }
    assert {i.name for i in historial.indexes} == {
        "ix_ordenes_historial_estado_orden_id_created_at"
    }


def test_el_historial_se_borra_con_la_orden_y_conserva_el_actor_como_nulo():
    fks = {fk.parent.name: fk.ondelete for fk in OrdenHistorialEstado.__table__.foreign_keys}
    assert fks == {"orden_id": "CASCADE", "actor_id": "SET NULL"}
