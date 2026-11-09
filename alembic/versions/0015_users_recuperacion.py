"""users: tokens e intentos de recuperación de contraseña (SPEC-03 §5.2, Fase B1)

- ``tokens_recuperacion``: sólo el SHA-256 del token (RN-46), un uso, con vencimiento.
- ``intentos_recuperacion``: HMAC del email e IP, para el límite por hora (RN-49).

El nombre es fijo (D-22). ``down_revision`` es la cabeza al abrir el PR (EC-45): B1 se
apila sobre B2 (``0014_files_init``), todavía en revisión.

Revision ID: 0015_users_recuperacion
Revises: 0014_files_init
Create Date: 2026-11-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_users_recuperacion"
down_revision: Union[str, None] = "0014_files_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "ix_tokens_recuperacion_usuario_id_usado_en",
        "tokens_recuperacion",
        ["usuario_id", "usado_en"],
    ),
    (
        "ix_intentos_recuperacion_email_hash_created_at",
        "intentos_recuperacion",
        ["email_hash", "created_at"],
    ),
    ("ix_intentos_recuperacion_ip_created_at", "intentos_recuperacion", ["ip", "created_at"]),
)


def upgrade() -> None:
    op.create_table(
        "tokens_recuperacion",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tokens_recuperacion"),
        sa.UniqueConstraint("token_hash", name="uq_tokens_recuperacion_token_hash"),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_tokens_recuperacion_usuario_id_usuarios",
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "intentos_recuperacion",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email_hash", sa.CHAR(64), nullable=False),
        sa.Column("ip", sa.String(45), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_intentos_recuperacion"),
    )
    for nombre, tabla, columnas in INDICES:
        op.create_index(nombre, tabla, columnas)


def downgrade() -> None:
    op.drop_table("intentos_recuperacion")
    op.drop_table("tokens_recuperacion")
