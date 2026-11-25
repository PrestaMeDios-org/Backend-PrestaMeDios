"""core: contador del límite diario de correos (SPEC-11 §6.7, plan §5.4)

Revision ID: 0021_core_envios_correo
Revises: 0020_notifications_portada
Create Date: 2026-11-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_core_envios_correo"
down_revision: Union[str, None] = "0020_notifications_portada"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "envios_correo_diarios",
        sa.Column("fecha", sa.Date(), nullable=False, primary_key=True),
        sa.Column("cantidad", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("cantidad >= 0", name="cantidad_no_negativa"),
    )


def downgrade() -> None:
    op.drop_table("envios_correo_diarios")
