"""loans: resolución de la orden e historial de estados (SPEC-05 Fase 2)

- ``ordenes_pedido.resuelto_por_id`` y ``resuelto_en``: quién y cuándo aprobó,
  rechazó o canceló la orden (auditoría, USR-08).
- ``ordenes_historial_estado``: traza inmutable de cada transición de la orden,
  igual que ``usuarios_historial_estado`` (P7.3, D-L10).

``down_revision`` apunta a la cabeza de ``develop`` al abrir el PR. Si
``0013_notifications_init`` (SPEC-06) se mergea antes, esta migración pasa a
colgar de ella (C19; plan de SPEC-05 §8.3, V5).

Revision ID: 0011_loans_resolucion
Revises: 0010_inventory_gestion
Create Date: 2026-11-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_loans_resolucion"
down_revision: Union[str, None] = "0010_inventory_gestion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `estado_orden_enum` ya existe (0009): se referencia sin crearlo ni borrarlo.
estado_orden_enum = postgresql.ENUM(
    "pendiente", "aprobada", "rechazada", "cancelada", name="estado_orden_enum", create_type=False
)


def upgrade() -> None:
    op.add_column("ordenes_pedido", sa.Column("resuelto_por_id", sa.Integer(), nullable=True))
    op.add_column(
        "ordenes_pedido", sa.Column("resuelto_en", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_ordenes_pedido_resuelto_por_id_usuarios",
        "ordenes_pedido",
        "usuarios",
        ["resuelto_por_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "ordenes_historial_estado",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("orden_id", sa.Integer(), nullable=False),
        sa.Column("estado_anterior", estado_orden_enum, nullable=True),
        sa.Column("estado_nuevo", estado_orden_enum, nullable=False),
        sa.Column("motivo", sa.String(500), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ordenes_historial_estado"),
        sa.ForeignKeyConstraint(
            ["orden_id"],
            ["ordenes_pedido.id"],
            name="fk_ordenes_historial_estado_orden_id_ordenes_pedido",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["usuarios.id"],
            name="fk_ordenes_historial_estado_actor_id_usuarios",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_ordenes_historial_estado_orden_id_created_at",
        "ordenes_historial_estado",
        ["orden_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ordenes_historial_estado_orden_id_created_at", table_name="ordenes_historial_estado"
    )
    op.drop_table("ordenes_historial_estado")
    op.drop_constraint(
        "fk_ordenes_pedido_resuelto_por_id_usuarios", "ordenes_pedido", type_="foreignkey"
    )
    op.drop_column("ordenes_pedido", "resuelto_en")
    op.drop_column("ordenes_pedido", "resuelto_por_id")
    # `estado_orden_enum` no se borra: lo sigue usando `ordenes_pedido` (0009).
