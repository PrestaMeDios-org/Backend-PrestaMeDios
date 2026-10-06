"""spaces init: tablas de reservas/bloqueos + ExcludeConstraint GIST

Revision ID: 0001_spaces_init
Revises:
Create Date: 2026-10-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_spaces_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Requerida para combinar id_espacio (=) con tsrange (&&) en GIST.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "bloqueos_espacios",
        sa.Column("id_bloqueo", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id_espacio", sa.Integer(), nullable=False),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=True),
        sa.Column("hora_fin", sa.Time(), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id_bloqueo"),
    )
    op.create_index("ix_bloqueos_espacios_id_espacio", "bloqueos_espacios", ["id_espacio"])

    op.create_table(
        "reservas_espacios",
        sa.Column("id_reserva", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id_usuario", sa.Integer(), nullable=False),
        sa.Column("id_espacio", sa.Integer(), nullable=False),
        sa.Column("fecha_reserva", sa.Date(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=False),
        sa.Column("hora_fin", sa.Time(), nullable=False),
        sa.Column("estado_reserva", sa.String(length=20), nullable=False, server_default="Pendiente"),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id_reserva"),
    )
    op.create_index("ix_reservas_espacios_id_usuario", "reservas_espacios", ["id_usuario"])
    op.create_index("ix_reservas_espacios_id_espacio", "reservas_espacios", ["id_espacio"])

    # Regla ACID: no solapar reservas 'Aprobadas' sobre el mismo espacio.
    op.execute(
        """
        ALTER TABLE reservas_espacios
        ADD CONSTRAINT excl_reserva_aprobada_sin_solapamiento
        EXCLUDE USING gist (
            id_espacio WITH =,
            tsrange(
                CAST(fecha_reserva AS TIMESTAMP) + hora_inicio::interval,
                CAST(fecha_reserva AS TIMESTAMP) + hora_fin::interval
            ) WITH &&
        )
        WHERE (estado_reserva = 'Aprobada')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE reservas_espacios DROP CONSTRAINT excl_reserva_aprobada_sin_solapamiento")
    op.drop_index("ix_reservas_espacios_id_espacio", table_name="reservas_espacios")
    op.drop_index("ix_reservas_espacios_id_usuario", table_name="reservas_espacios")
    op.drop_table("reservas_espacios")
    op.drop_index("ix_bloqueos_espacios_id_espacio", table_name="bloqueos_espacios")
    op.drop_table("bloqueos_espacios")
