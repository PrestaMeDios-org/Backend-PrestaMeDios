"""espacios: tabla de espacios y FKs desde reservas/bloqueos

Revision ID: 0002_espacios
Revises: 0001_spaces_init
Create Date: 2026-10-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_espacios"
down_revision: Union[str, None] = "0001_spaces_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "espacios",
        sa.Column("id_espacio", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("id_sede", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id_espacio"),
    )
    op.create_index("ix_espacios_id_sede", "espacios", ["id_sede"])

    op.create_foreign_key(
        "fk_reservas_espacios_id_espacio",
        "reservas_espacios",
        "espacios",
        ["id_espacio"],
        ["id_espacio"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_bloqueos_espacios_id_espacio",
        "bloqueos_espacios",
        "espacios",
        ["id_espacio"],
        ["id_espacio"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_bloqueos_espacios_id_espacio", "bloqueos_espacios", type_="foreignkey")
    op.drop_constraint("fk_reservas_espacios_id_espacio", "reservas_espacios", type_="foreignkey")
    op.drop_index("ix_espacios_id_sede", table_name="espacios")
    op.drop_table("espacios")
