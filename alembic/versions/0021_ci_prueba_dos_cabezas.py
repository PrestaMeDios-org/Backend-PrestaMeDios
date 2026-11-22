"""PRUEBA DE CI (SPEC-11 B-03, AC-P07): segunda cabeza a propósito. No mergear.

Revision ID: 0021_ci_prueba_dos_cabezas
Revises: 0019_inventory_categorias_base
"""

from typing import Sequence, Union

revision: str = "0021_ci_prueba_dos_cabezas"
down_revision: Union[str, None] = "0019_inventory_categorias_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
