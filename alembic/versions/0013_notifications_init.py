"""notifications: comunicados y notificaciones (SPEC-06 §7)

- ``comunicados``: NOV-02 (Fase A). Una sede o global, nunca las dos (RN-N2).
- ``notificaciones``: NOV-04 (Fase B). Un destinatario por fila (RN-N6).

El número 0013 deja libres 0011 y 0012, reservados por SPEC-05 (`loans`).
``down_revision`` apunta a la cabeza real de `develop` al implementar; antes de
mergear se verifica con ``alembic heads`` que haya una sola cabeza (plan-06 §3.4).

Revision ID: 0013_notifications_init
Revises: 0010_inventory_gestion
Create Date: 2026-11-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_notifications_init"
down_revision: Union[str, None] = "0010_inventory_gestion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `sede_enum` ya existe (0005/0006) y es compartido: se referencia sin crearlo.
sede_enum = postgresql.ENUM("Ushuaia", "Río Grande", name="sede_enum", create_type=False)
estado_comunicado_enum = postgresql.ENUM(
    "PUBLICADO", "ARCHIVADO", name="estado_comunicado_enum", create_type=False
)
severidad_notificacion_enum = postgresql.ENUM(
    "NORMAL", "CRITICA", name="severidad_notificacion_enum", create_type=False
)

# SQL directo para los CHECK: con `op.create_check_constraint` la NAMING_CONVENTION
# volvería a prefijar el nombre (hallazgo de la migración 0010).
CHECKS: tuple[tuple[str, str, str], ...] = (
    (
        "comunicados",
        "ck_comunicados_alcance_coherente",
        "(es_global AND sede IS NULL) OR (NOT es_global AND sede IS NOT NULL)",
    ),
    (
        "comunicados",
        "ck_comunicados_vence_despues_de_publicar",
        "vence_en IS NULL OR vence_en > publicado_en",
    ),
    ("comunicados", "ck_comunicados_contenido_largo_maximo", "length(contenido) <= 5000"),
    (
        "notificaciones",
        "ck_notificaciones_referencia_completa",
        "(referencia_modulo IS NULL) = (referencia_id IS NULL)",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    estado_comunicado_enum.create(bind, checkfirst=True)
    severidad_notificacion_enum.create(bind, checkfirst=True)

    op.create_table(
        "comunicados",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("titulo", sa.String(150), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("sede", sede_enum, nullable=True),
        sa.Column("es_global", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "estado",
            estado_comunicado_enum,
            nullable=False,
            server_default=sa.text("'PUBLICADO'"),
        ),
        sa.Column("autor_id", sa.Integer(), nullable=True),
        sa.Column(
            "publicado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("vence_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_comunicados"),
        sa.ForeignKeyConstraint(
            ["autor_id"], ["usuarios.id"], name="fk_comunicados_autor_id_usuarios", ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_comunicados_estado_sede_publicado",
        "comunicados",
        ["estado", "sede", sa.text("publicado_en DESC")],
    )

    op.create_table(
        "notificaciones",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(50), nullable=False),
        sa.Column("severidad", severidad_notificacion_enum, nullable=False),
        sa.Column("titulo", sa.String(150), nullable=False),
        sa.Column("mensaje", sa.String(1000), nullable=False),
        sa.Column("referencia_modulo", sa.String(30), nullable=True),
        sa.Column("referencia_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("leida_en", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notificaciones"),
        sa.ForeignKeyConstraint(
            ["usuario_id"],
            ["usuarios.id"],
            name="fk_notificaciones_usuario_id_usuarios",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_notificaciones_usuario_creada",
        "notificaciones",
        ["usuario_id", sa.text("creada_en DESC")],
    )
    op.create_index(
        "ix_notificaciones_no_leidas",
        "notificaciones",
        ["usuario_id"],
        postgresql_where=sa.text("leida_en IS NULL"),
    )

    for tabla, nombre, condicion in CHECKS:
        op.execute(f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} CHECK ({condicion})")


def downgrade() -> None:
    op.drop_table("notificaciones")
    op.drop_table("comunicados")
    bind = op.get_bind()
    severidad_notificacion_enum.drop(bind, checkfirst=True)
    estado_comunicado_enum.drop(bind, checkfirst=True)
    # `sede_enum` no se elimina: lo usan `usuarios`, `inventory` y `loans`.
