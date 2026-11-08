"""SPEC-03 §6.2 · Migración ``0014_files_init`` — AC-90.

Como en ``test_migracion_0013``: la base de tests se crea con ``create_all`` y estos
tests verifican que el script declare lo mismo. El ciclo real ``upgrade`` →
``downgrade -1`` → ``upgrade`` se corre a mano sobre una base de desarrollo.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from app.modules.files.models import Archivo
from app.modules.users.models import Usuario

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0014_files_init.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("files_init_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op(monkeypatch, modulo) -> MagicMock:
    op = MagicMock()
    monkeypatch.setattr(modulo, "op", op)
    return op


def test_encadena_con_la_cabeza_de_develop():  # D-22, EC-45
    modulo = _cargar()
    assert modulo.revision == "0014_files_init"
    assert modulo.down_revision == "0011_loans_resolucion"


def test_upgrade(monkeypatch):
    modulo = _cargar()
    op = _op(monkeypatch, modulo)
    modulo.upgrade()
    assert [c.args[0] for c in op.create_table.call_args_list] == ["archivos", "archivos_contenido"]
    assert op.create_index.call_args.args[:3] == (
        "ix_archivos_vinculado_en_created_at",
        "archivos",
        ["vinculado_en", "created_at"],
    )
    assert op.add_column.call_args.args[0] == "usuarios"
    fk = op.create_foreign_key.call_args
    assert fk.args[:5] == ("fk_usuarios_foto_id_archivos", "usuarios", "archivos", ["foto_id"], ["id"])
    assert fk.kwargs["ondelete"] == "SET NULL"
    sql = "\n".join(str(c.args[0]) for c in op.execute.call_args_list)
    assert "ADD CONSTRAINT ck_archivos_tamano_positivo CHECK (tamano_bytes > 0)" in sql


def test_downgrade_deshace_en_orden_inverso(monkeypatch):
    modulo = _cargar()
    op = _op(monkeypatch, modulo)
    modulo.downgrade()
    assert op.drop_constraint.call_args.args == ("fk_usuarios_foto_id_archivos", "usuarios")
    assert op.drop_column.call_args.args == ("usuarios", "foto_id")
    assert [c.args[0] for c in op.drop_table.call_args_list] == ["archivos_contenido", "archivos"]


def test_nombres_coinciden_con_el_modelo():
    modulo = _cargar()
    checks = {c.name for c in Archivo.__table__.constraints if c.name and c.name.startswith("ck_")}
    assert checks == {nombre for _, nombre, _ in modulo.CHECKS}
    assert {i.name for i in Archivo.__table__.indexes} == {modulo.INDICE_LIMPIEZA}
    (fk,) = Usuario.__table__.c.foto_id.foreign_keys
    assert fk.constraint.name == modulo.FK_FOTO and fk.ondelete == "SET NULL"


@pytest.mark.integracion
async def test_create_all_resuelve_el_ciclo_de_fk(db):  # AC-90 (base de tests)
    filas = await db.execute(
        text(
            "SELECT conname, confdeltype FROM pg_constraint "
            "WHERE conname IN ('fk_usuarios_foto_id_archivos', "
            "'fk_archivos_propietario_id_usuarios', 'fk_archivos_contenido_archivo_id_archivos')"
        )
    )
    assert {nombre: bytes(tipo).decode() for nombre, tipo in filas.all()} == {
        "fk_usuarios_foto_id_archivos": "n",  # SET NULL
        "fk_archivos_propietario_id_usuarios": "r",  # RESTRICT
        "fk_archivos_contenido_archivo_id_archivos": "c",  # CASCADE
    }
