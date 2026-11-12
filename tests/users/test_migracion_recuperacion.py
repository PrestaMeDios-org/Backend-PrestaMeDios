"""SPEC-03 §5.2 · Migración ``0015_users_recuperacion`` — AC-80.

Como ``test_migracion_0014``: la base de tests sale de ``create_all`` y estos tests
verifican que el script declare lo mismo que los modelos. El ciclo real ``upgrade`` →
``downgrade -1`` → ``upgrade`` se corre a mano sobre una base de desarrollo.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from app.modules.users.models import IntentoRecuperacion, TokenRecuperacion

RUTA = Path(__file__).parents[2] / "alembic" / "versions" / "0015_users_recuperacion.py"


def _cargar(monkeypatch=None):
    spec = importlib.util.spec_from_file_location("users_recuperacion_migration", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    if monkeypatch is not None:
        monkeypatch.setattr(modulo, "op", MagicMock())
    return modulo


def test_encadena_con_files():  # D-22, EC-45
    modulo = _cargar()
    assert modulo.revision == "0015_users_recuperacion"
    assert modulo.down_revision == "0014_files_init"


def test_upgrade_y_downgrade(monkeypatch):  # AC-80
    modulo = _cargar(monkeypatch)
    modulo.upgrade()
    tablas = [c.args[0] for c in modulo.op.create_table.call_args_list]
    assert tablas == ["tokens_recuperacion", "intentos_recuperacion"]
    creados = {c.args[0] for c in modulo.op.create_index.call_args_list}
    assert creados == {nombre for nombre, _, _ in modulo.INDICES}
    modulo.downgrade()
    borradas = [c.args[0] for c in modulo.op.drop_table.call_args_list]
    assert borradas == ["intentos_recuperacion", "tokens_recuperacion"]


def test_indices_y_restricciones_coinciden_con_los_modelos():
    modulo = _cargar()
    del_modelo = {
        (i.name, i.table.name, tuple(c.name for c in i.columns))
        for t in (TokenRecuperacion.__table__, IntentoRecuperacion.__table__)
        for i in t.indexes
    }
    assert del_modelo == {(n, t, tuple(c)) for n, t, c in modulo.INDICES}
    unicos = [
        c.name
        for c in TokenRecuperacion.__table__.constraints
        if c.name and c.name.startswith("uq_")
    ]
    assert unicos == ["uq_tokens_recuperacion_token_hash"]
    (fk,) = TokenRecuperacion.__table__.c.usuario_id.foreign_keys
    assert fk.constraint.name == "fk_tokens_recuperacion_usuario_id_usuarios"
    assert fk.ondelete == "CASCADE"
