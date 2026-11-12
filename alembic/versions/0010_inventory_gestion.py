"""inventory: baja lógica, notebooks y CHECK de locker 1–7 (SPEC-04, DT-23)

- ``equipamientos.activo``: baja lógica del catálogo (P7.3).
- ``equipamientos.es_notebook``: plazo por defecto de notebooks (SPEC-04 D-05).
- ``unidades_fisicas``: el locker pasa de ``>= 1`` a ``BETWEEN 1 AND 7`` (P7.1).
  Si hay datos fuera de rango la migración falla con los ids; no los corrige.

Revision ID: 0010_inventory_gestion
Revises: 0009_loans_init
Create Date: 2026-10-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_inventory_gestion"
down_revision: Union[str, None] = "0009_loans_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    fuera_de_rango = bind.execute(
        sa.text("SELECT id FROM unidades_fisicas WHERE locker IS NOT NULL AND locker NOT BETWEEN 1 AND 7")
    ).scalars().all()
    if fuera_de_rango:
        raise RuntimeError(
            "No se puede aplicar el CHECK de locker 1–7: hay unidades con locker fuera de rango "
            f"(ids: {', '.join(map(str, fuera_de_rango))}). Corregilas y volvé a ejecutar."
        )

    op.add_column(
        "equipamientos",
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "equipamientos",
        sa.Column("es_notebook", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _quitar_checks("locker_positivo")
    # SQL directo: con `op.create_check_constraint` la NAMING_CONVENTION volvería a
    # prefijar el nombre ("ck_unidades_fisicas_ck_unidades_fisicas_...").
    op.execute(
        "ALTER TABLE unidades_fisicas ADD CONSTRAINT ck_unidades_fisicas_locker_rango "
        "CHECK (locker IS NULL OR locker BETWEEN 1 AND 7)"
    )


def downgrade() -> None:
    _quitar_checks("locker_rango")
    op.execute(
        "ALTER TABLE unidades_fisicas ADD CONSTRAINT ck_unidades_fisicas_locker_positivo "
        "CHECK (locker >= 1)"
    )
    op.drop_column("equipamientos", "es_notebook")
    op.drop_column("equipamientos", "activo")


def _quitar_checks(sufijo: str) -> None:
    """Quita el CHECK con ambos nombres posibles.

    Las bases creadas con `create_all` lo tienen como ``ck_unidades_fisicas_<x>``; las
    creadas con la migración 0006 como ``ck_unidades_fisicas_ck_unidades_fisicas_<x>``.
    """
    for nombre in (f"ck_unidades_fisicas_{sufijo}", f"ck_unidades_fisicas_ck_unidades_fisicas_{sufijo}"):
        op.execute(f"ALTER TABLE unidades_fisicas DROP CONSTRAINT IF EXISTS {nombre}")
