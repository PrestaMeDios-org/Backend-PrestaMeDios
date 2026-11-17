"""MOMENTÁNEO (SPEC-10 M-02): portada elegible de los comunicados

Tabla aislada ``comunicados_portada``: una fila por comunicado con tema de color o
foto elegidos. No modifica ``comunicados`` ni ``files``. El ``downgrade`` borra sólo
esta tabla: es la forma de sacar la funcionalidad (SPEC-10 §1.4).

Revision ID: 0020_notifications_portada
Revises: 0019_inventory_categorias_base
Create Date: 2026-11-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_notifications_portada"
down_revision: Union[str, None] = "0019_inventory_categorias_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comunicados_portada",
        sa.Column("comunicado_id", sa.Integer(), nullable=False),
        sa.Column("tema", sa.String(length=10), nullable=True),
        sa.Column("imagen", sa.LargeBinary(), nullable=True),
        sa.Column("tipo_mime", sa.String(length=20), nullable=True),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tema IS NULL OR tema IN ('rojo', 'amarillo', 'azul', 'verde')",
            name=op.f("ck_comunicados_portada_tema_valido"),
        ),
        sa.CheckConstraint(
            "(tema IS NULL) <> (imagen IS NULL)",
            name=op.f("ck_comunicados_portada_tema_o_imagen"),
        ),
        sa.ForeignKeyConstraint(
            ["comunicado_id"],
            ["comunicados.id"],
            name=op.f("fk_comunicados_portada_comunicado_id_comunicados"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("comunicado_id", name=op.f("pk_comunicados_portada")),
    )


def downgrade() -> None:
    op.drop_table("comunicados_portada")
