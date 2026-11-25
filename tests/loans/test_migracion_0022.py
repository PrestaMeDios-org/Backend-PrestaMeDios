"""Migración `0022_loans_ciclo_entrega` (SPEC-05 Fase 3, §7.2; AC-L54).

Como en `test_migracion_0011.py`: se verifican las operaciones sin base de datos. El
ciclo upgrade → downgrade → upgrade contra PostgreSQL se valida aparte, con una base
temporal. La prueba de que Alembic tiene una sola cabeza está en `test_migracion_0011.py`.
"""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import sqlalchemy as sa

from app.modules.loans.models import DetallePrestamo

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0022_loans_ciclo_entrega.py"
COLUMNAS = ["entregado_en", "devuelto_en", "observacion_devolucion", "motivo_cancelacion"]
CHECKS = [
    "ck_detalles_prestamo_entrega_registrada",
    "ck_detalles_prestamo_devolucion_registrada",
]


def _cargar():
    spec = importlib.util.spec_from_file_location("loans_ciclo_entrega_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op_falso(monkeypatch, migracion) -> Mock:
    op = Mock()
    monkeypatch.setattr(migracion, "op", op)
    return op


def test_encadena_con_la_cabeza_de_develop():  # C19, plan §9.2 (V9)
    migracion = _cargar()
    assert migracion.revision == "0022_loans_ciclo_entrega"
    assert migracion.down_revision == "0021_core_envios_correo"


def test_upgrade_agrega_las_columnas_completa_las_fechas_y_despues_crea_los_check(monkeypatch):
    migracion = _cargar()
    op = _op_falso(monkeypatch, migracion)

    migracion.upgrade()

    agregadas = [(c.args[0], c.args[1].name, c.args[1].nullable) for c in op.add_column.call_args_list]
    assert agregadas == [("detalles_prestamo", nombre, True) for nombre in COLUMNAS]
    sentencias = [c.args[0] for c in op.execute.call_args_list]
    # V12: primero se completan las líneas viejas, después se crean las restricciones.
    assert sentencias[0].startswith("UPDATE detalles_prestamo")
    assert [s.split()[5] for s in sentencias[1:]] == CHECKS


def test_downgrade_borra_los_check_antes_que_las_columnas(monkeypatch):
    migracion = _cargar()
    op = _op_falso(monkeypatch, migracion)

    migracion.downgrade()

    metodos = [c[0] for c in op.method_calls]
    assert metodos == ["execute", "execute"] + ["drop_column"] * 4
    assert [c.args[0].split()[-1] for c in op.execute.call_args_list] == CHECKS[::-1]
    assert [c.args[1] for c in op.drop_column.call_args_list] == COLUMNAS[::-1]


def test_el_modelo_coincide_con_la_migracion():
    tabla = DetallePrestamo.__table__
    for nombre in COLUMNAS:
        assert tabla.columns[nombre].nullable
    assert tabla.columns["observacion_devolucion"].type.length == 500
    assert tabla.columns["motivo_cancelacion"].type.length == 500
    checks = {c.name for c in tabla.constraints if isinstance(c, sa.CheckConstraint)}
    assert set(CHECKS) <= checks
