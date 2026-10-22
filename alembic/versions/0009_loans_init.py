"""loans: ordenes_pedido y detalles_prestamo con exclusion constraint

Una unidad física no puede estar en dos líneas activas (`reservado` o
`entregado`) con períodos que se solapan: lo garantiza PostgreSQL con una
Exclusion Constraint (extensión `btree_gist`), sin validaciones en Python.

Revision ID: 0009_loans_init
Revises: 0008_usuarios_perfil
Create Date: 2026-10-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_loans_init"
down_revision: Union[str, None] = "0008_usuarios_perfil"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `sede_enum` ya existe (0005/0006): se referencia sin crearlo.
sede_enum = postgresql.ENUM("Ushuaia", "Río Grande", name="sede_enum", create_type=False)
estado_orden_enum = postgresql.ENUM(
    "pendiente", "aprobada", "rechazada", "cancelada", name="estado_orden_enum", create_type=False
)
estado_detalle_enum = postgresql.ENUM(
    "pendiente",
    "reservado",
    "entregado",
    "devuelto",
    "rechazado",
    "no_retirado",
    "cancelado",
    name="estado_detalle_enum",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # Necesaria para combinar "=" (entero) con "&&" (rango) en un índice GiST.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    estado_orden_enum.create(bind, checkfirst=True)
    estado_detalle_enum.create(bind, checkfirst=True)

    op.create_table(
        "ordenes_pedido",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("solicitante_id", sa.Integer(), nullable=False),
        sa.Column("sede", sede_enum, nullable=False),
        sa.Column("asignatura_id", sa.Integer(), nullable=True),
        sa.Column(
            "estado", estado_orden_enum, nullable=False, server_default=sa.text("'pendiente'")
        ),
        sa.Column(
            "fecha_solicitud",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("observacion_docente", sa.String(500), nullable=True),
        sa.Column("motivo_resolucion", sa.String(500), nullable=True),
        sa.Column("es_renovado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name="pk_ordenes_pedido"),
        sa.ForeignKeyConstraint(
            ["solicitante_id"],
            ["usuarios.id"],
            name="fk_ordenes_pedido_solicitante_id_usuarios",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_ordenes_pedido_solicitante_id", "ordenes_pedido", ["solicitante_id"])
    op.create_index("ix_ordenes_pedido_sede", "ordenes_pedido", ["sede"])
    op.create_index("ix_ordenes_pedido_estado", "ordenes_pedido", ["estado"])

    op.create_table(
        "detalles_prestamo",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("orden_id", sa.Integer(), nullable=False),
        sa.Column("equipamiento_id", sa.Integer(), nullable=False),
        sa.Column("unidad_fisica_id", sa.Integer(), nullable=True),
        sa.Column(
            "estado", estado_detalle_enum, nullable=False, server_default=sa.text("'pendiente'")
        ),
        sa.Column("retiro_pactado", sa.DateTime(timezone=True), nullable=False),
        sa.Column("devolucion_pactada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fin_ocupacion", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "periodo",
            postgresql.TSTZRANGE(),
            sa.Computed("tstzrange(retiro_pactado, fin_ocupacion, '[)')", persisted=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_detalles_prestamo"),
        sa.ForeignKeyConstraint(
            ["orden_id"],
            ["ordenes_pedido.id"],
            name="fk_detalles_prestamo_orden_id_ordenes_pedido",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["equipamiento_id"],
            ["equipamientos.id"],
            name="fk_detalles_prestamo_equipamiento_id_equipamientos",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unidad_fisica_id"],
            ["unidades_fisicas.id"],
            name="fk_detalles_prestamo_unidad_fisica_id_unidades_fisicas",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "devolucion_pactada > retiro_pactado", name="rango_pactado"
        ),
        sa.CheckConstraint(
            "fin_ocupacion >= devolucion_pactada",
            name="fin_ocupacion_valido",
        ),
        sa.CheckConstraint(
            "estado NOT IN ('reservado', 'entregado') OR unidad_fisica_id IS NOT NULL",
            name="unidad_si_ocupa",
        ),
        # Misma unidad + períodos que se pisan = rechazo (SQLSTATE 23P01).
        # Solo compara las líneas que ocupan; el resto libera la unidad.
        postgresql.ExcludeConstraint(
            ("unidad_fisica_id", "="),
            ("periodo", "&&"),
            where=sa.text("estado IN ('reservado', 'entregado')"),
            using="gist",
            name="ex_detalles_prestamo_sin_solapamiento",
        ),
    )
    op.create_index("ix_detalles_prestamo_orden_id", "detalles_prestamo", ["orden_id"])
    op.create_index(
        "ix_detalles_prestamo_equipamiento_id", "detalles_prestamo", ["equipamiento_id"]
    )
    op.create_index(
        "ix_detalles_prestamo_unidad_fisica_id", "detalles_prestamo", ["unidad_fisica_id"]
    )
    op.create_index("ix_detalles_prestamo_estado", "detalles_prestamo", ["estado"])


def downgrade() -> None:
    op.drop_table("detalles_prestamo")
    op.drop_table("ordenes_pedido")
    bind = op.get_bind()
    estado_detalle_enum.drop(bind, checkfirst=True)
    estado_orden_enum.drop(bind, checkfirst=True)
    # No se eliminan `sede_enum` (lo usan `usuarios` e `inventory`) ni la
    # extensión `btree_gist` (puede estar en uso por otros módulos).