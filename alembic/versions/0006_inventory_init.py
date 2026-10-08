"""inventory: categorias, equipamientos y unidades_fisicas (DT-04)

Hasta ahora las tablas de `inventory` sólo existían si se creaban con
`Base.metadata.create_all`; con `alembic upgrade head` sobre una base nueva
el módulo respondía 500. Esta migración las incorpora de forma **idempotente**:
si una tabla ya existe (bases de desarrollo previas), se omite.

Revision ID: 0006_inventory_init
Revises: 0005_users_y_parametros
Create Date: 2026-10-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_inventory_init"
down_revision: Union[str, None] = "0005_users_y_parametros"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

sede_enum = postgresql.ENUM("Ushuaia", "Río Grande", name="sede_enum", create_type=False)
estado_unidad_enum = postgresql.ENUM(
    "disponible", "prestado", "mantenimiento", "baja", name="estado_unidad_enum", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    existentes = set(sa.inspect(bind).get_table_names())

    # `sede_enum` es compartido con `usuarios` (0005): crear sólo si no existe.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sede_enum AS ENUM ('Ushuaia', 'Río Grande');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    estado_unidad_enum.create(bind, checkfirst=True)

    if "categorias" not in existentes:
        op.create_table(
            "categorias",
            sa.Column("id", sa.String(50), nullable=False),
            sa.Column("nombre", sa.String(100), nullable=False),
            sa.Column("color", sa.String(7), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_categorias"),
            sa.UniqueConstraint("nombre", name="uq_categorias_nombre"),
        )

    if "equipamientos" not in existentes:
        op.create_table(
            "equipamientos",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("codigo", sa.String(30), nullable=False),
            sa.Column("nombre", sa.String(150), nullable=False),
            sa.Column("marca", sa.String(100), nullable=False),
            sa.Column("modelo", sa.String(100), nullable=False),
            sa.Column("categoria_id", sa.String(50), nullable=False),
            sa.Column("descripcion", sa.String(500), nullable=True),
            sa.Column("max_dias_prestamo", sa.Integer(), nullable=False, server_default=sa.text("4")),
            sa.Column("alta_gama", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("imagen_url", sa.String(500), nullable=True),
            sa.Column("video_url", sa.String(500), nullable=True),
            sa.Column(
                "reglas_cuidado", postgresql.ARRAY(sa.String(300)), nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_equipamientos"),
            sa.UniqueConstraint("codigo", name="uq_equipamientos_codigo"),
            sa.ForeignKeyConstraint(
                ["categoria_id"], ["categorias.id"],
                name="fk_equipamientos_categoria_id_categorias",
                ondelete="RESTRICT", onupdate="CASCADE",
            ),
            sa.CheckConstraint(
                "max_dias_prestamo BETWEEN 1 AND 15", name="ck_equipamientos_max_dias_prestamo"
            ),
        )
        op.create_index("ix_equipamientos_nombre", "equipamientos", ["nombre"])
        op.create_index("ix_equipamientos_categoria_id", "equipamientos", ["categoria_id"])

    if "unidades_fisicas" not in existentes:
        op.create_table(
            "unidades_fisicas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("equipamiento_id", sa.Integer(), nullable=False),
            sa.Column("numero_serie", sa.String(100), nullable=False),
            sa.Column("codigo_inventario", sa.String(100), nullable=False),
            sa.Column("sede", sede_enum, nullable=False),
            sa.Column("locker", sa.Integer(), nullable=True),
            sa.Column(
                "estado", estado_unidad_enum, nullable=False, server_default=sa.text("'disponible'")
            ),
            sa.PrimaryKeyConstraint("id", name="pk_unidades_fisicas"),
            sa.UniqueConstraint("numero_serie", name="uq_unidades_fisicas_numero_serie"),
            sa.UniqueConstraint("codigo_inventario", name="uq_unidades_fisicas_codigo_inventario"),
            sa.ForeignKeyConstraint(
                ["equipamiento_id"], ["equipamientos.id"],
                name="fk_unidades_fisicas_equipamiento_id_equipamientos", ondelete="CASCADE",
            ),
            sa.CheckConstraint("locker >= 1", name="ck_unidades_fisicas_locker_positivo"),
        )
        op.create_index("ix_unidades_fisicas_equipamiento_id", "unidades_fisicas", ["equipamiento_id"])
        op.create_index("ix_unidades_fisicas_sede", "unidades_fisicas", ["sede"])
        op.create_index("ix_unidades_fisicas_estado", "unidades_fisicas", ["estado"])


def downgrade() -> None:
    op.drop_table("unidades_fisicas")
    op.drop_table("equipamientos")
    op.drop_table("categorias")
    estado_unidad_enum.drop(op.get_bind(), checkfirst=True)
    # `sede_enum` lo sigue usando `usuarios` (0005); se elimina en el downgrade de 0005.
