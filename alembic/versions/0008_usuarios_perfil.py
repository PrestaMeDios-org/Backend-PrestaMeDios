"""usuarios: cambio obligatorio de contrasena e historial de ediciones (SPEC-02 §5.1)

Revision ID: 0008_usuarios_perfil
Revises: 0007_spaces_sede_y_usuario
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_usuarios_perfil"
down_revision: Union[str, None] = "0007_spaces_sede_y_usuario"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column(
            "debe_cambiar_password", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_table(
        "usuarios_historial_cambios",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("cambios", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_usuarios_historial_cambios"),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"],
            name="fk_usuarios_historial_cambios_usuario_id_usuarios", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["usuarios.id"],
            name="fk_usuarios_historial_cambios_actor_id_usuarios", ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_usuarios_historial_cambios_usuario_id_created_at",
        "usuarios_historial_cambios", ["usuario_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_usuarios_historial_cambios_usuario_id_created_at",
        table_name="usuarios_historial_cambios",
    )
    op.drop_table("usuarios_historial_cambios")
    op.drop_column("usuarios", "debe_cambiar_password")
