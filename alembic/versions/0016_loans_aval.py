"""loans: aval de alta gama de la orden (SPEC-05 T1.12, RN-L09, K3 de SPEC-03)

``ordenes_pedido.aval_archivo_id`` guarda qué PDF de ``files`` es el aval de la
orden. ``files`` sólo marca el archivo como vinculado (``vinculado_en``), así que
sin esta columna la orden no podría servir su aval (AC-L60).

``RESTRICT``: un archivo vinculado no se borra (la limpieza de ``files`` sólo
toca los no vinculados), y si alguna vez se intentara, la base lo impide.

Revision ID: 0016_loans_aval
Revises: 0015_users_recuperacion
Create Date: 2026-11-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_loans_aval"
down_revision: Union[str, None] = "0015_users_recuperacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ordenes_pedido",
        sa.Column("aval_archivo_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ordenes_pedido_aval_archivo_id_archivos",
        "ordenes_pedido",
        "archivos",
        ["aval_archivo_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ordenes_pedido_aval_archivo_id_archivos", "ordenes_pedido", type_="foreignkey"
    )
    op.drop_column("ordenes_pedido", "aval_archivo_id")
