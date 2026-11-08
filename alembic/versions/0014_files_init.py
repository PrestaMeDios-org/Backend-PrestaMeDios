"""files: archivos, su contenido y la foto de perfil (SPEC-03 §6.2, Fase B2)

- ``archivos``: metadatos (PRE-05, USR-03). ``sede`` usa el ``sede_enum`` existente.
- ``archivos_contenido``: los bytes, aparte (D-10).
- ``usuarios.foto_id``: foto vigente, ``ON DELETE SET NULL``.

El nombre es fijo (D-22). ``down_revision`` es la cabeza de `develop` al abrir el PR;
antes de mergear, ``alembic heads`` debe mostrar una sola cabeza (EC-45).

Revision ID: 0014_files_init
Revises: 0011_loans_resolucion
Create Date: 2026-11-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_files_init"
down_revision: Union[str, None] = "0011_loans_resolucion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `sede_enum` ya existe (0005/0006) y es compartido: se referencia sin crearlo.
sede_enum = postgresql.ENUM("Ushuaia", "Río Grande", name="sede_enum", create_type=False)
proposito_archivo_enum = postgresql.ENUM(
    "FOTO_PERFIL", "AVAL_PRESTAMO", name="proposito_archivo_enum", create_type=False
)

# SQL directo para los CHECK: con `op.create_check_constraint` la NAMING_CONVENTION
# volvería a prefijar el nombre (DT-26, hallazgo de la migración 0010).
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("archivos", "ck_archivos_tamano_positivo", "tamano_bytes > 0"),
)
INDICE_LIMPIEZA = "ix_archivos_vinculado_en_created_at"
FK_FOTO = "fk_usuarios_foto_id_archivos"


def upgrade() -> None:
    proposito_archivo_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "archivos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("propietario_id", sa.Integer(), nullable=False),
        sa.Column("proposito", proposito_archivo_enum, nullable=False),
        sa.Column("sede", sede_enum, nullable=True),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("nombre_original", sa.String(255), nullable=False),
        sa.Column("vinculado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_archivos"),
        sa.ForeignKeyConstraint(
            ["propietario_id"],
            ["usuarios.id"],
            name="fk_archivos_propietario_id_usuarios",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(INDICE_LIMPIEZA, "archivos", ["vinculado_en", "created_at"])
    for tabla, nombre, condicion in CHECKS:
        op.execute(f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} CHECK ({condicion})")

    op.create_table(
        "archivos_contenido",
        sa.Column("archivo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("datos", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("archivo_id", name="pk_archivos_contenido"),
        sa.ForeignKeyConstraint(
            ["archivo_id"],
            ["archivos.id"],
            name="fk_archivos_contenido_archivo_id_archivos",
            ondelete="CASCADE",
        ),
    )

    op.add_column("usuarios", sa.Column("foto_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(FK_FOTO, "usuarios", "archivos", ["foto_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(FK_FOTO, "usuarios", type_="foreignkey")
    op.drop_column("usuarios", "foto_id")
    op.drop_table("archivos_contenido")
    op.drop_index(INDICE_LIMPIEZA, table_name="archivos")
    op.drop_table("archivos")
    proposito_archivo_enum.drop(op.get_bind(), checkfirst=True)
    # `sede_enum` no se elimina: lo usan `usuarios`, `inventory`, `loans` y `notifications`.
