"""spaces: reversión lógica de bloqueos y bloqueo general (SPEC-08 v1.1.0, GLO-04)

- ``id_grupo``: las filas creadas por ``POST /bloqueos/general`` comparten un UUID,
  así un bloqueo general se revierte entero (D-S03).
- ``revertido_en`` y ``revertido_por``: deshacer un bloqueo no lo borra; queda el
  registro de quién lo levantó y cuándo (D-S01, P7.3). Los tres nulos son un bloqueo
  individual activo, que es lo que tienen las filas existentes.

La ``0017`` queda reservada para ``0017_config_sedes`` (SPEC-09); esta cuelga de la
cabeza de ``develop`` al abrir el PR. Alembic encadena por id, no por número.

Revision ID: 0018_spaces_bloqueos_reversion
Revises: 0016_loans_aval
Create Date: 2026-11-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_spaces_bloqueos_reversion"
down_revision: Union[str, None] = "0016_loans_aval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "bloqueos_espacios"
FK = "fk_bloqueos_espacios_revertido_por_usuarios"
IX = "ix_bloqueos_espacios_id_grupo"


def upgrade() -> None:
    op.add_column(TABLA, sa.Column("id_grupo", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(TABLA, sa.Column("revertido_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLA, sa.Column("revertido_por", sa.Integer(), nullable=True))
    op.create_foreign_key(FK, TABLA, "usuarios", ["revertido_por"], ["id"], ondelete="SET NULL")
    op.create_index(IX, TABLA, ["id_grupo"])


def downgrade() -> None:
    op.drop_index(IX, table_name=TABLA)
    op.drop_constraint(FK, TABLA, type_="foreignkey")
    op.drop_column(TABLA, "revertido_por")
    op.drop_column(TABLA, "revertido_en")
    op.drop_column(TABLA, "id_grupo")
