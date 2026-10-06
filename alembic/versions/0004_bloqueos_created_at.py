"""bloqueos: columna created_at faltante

Revision ID: 0004_bloqueos_created_at
Revises: 0003_reserva_en_uso
Create Date: 2026-10-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_bloqueos_created_at"
down_revision: Union[str, None] = "0003_reserva_en_uso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bloqueos_espacios",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("bloqueos_espacios", "created_at")
