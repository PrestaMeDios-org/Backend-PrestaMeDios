"""spaces: sede como sede_enum y FK de reservas a usuarios (SPEC-02 §3.1, DT-02, DT-03)

- ``espacios.id_sede`` (1 = Ushuaia, 2 = Río Grande) pasa a ``espacios.sede``.
  Cualquier otro valor aborta la migración con un mensaje explícito (D-02).
- Las reservas cuyo ``id_usuario`` no existe en ``usuarios`` (datos cargados
  antes de la autenticación) se eliminan con aviso (D-03) y se crea la FK.

El ``downgrade`` restaura ``id_sede`` y quita la FK; las reservas eliminadas
no se recuperan.

Revision ID: 0007_spaces_sede_y_usuario
Revises: 0006_inventory_init
Create Date: 2026-10-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_spaces_sede_y_usuario"
down_revision: Union[str, None] = "0006_inventory_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

sede_enum = postgresql.ENUM("Ushuaia", "Río Grande", name="sede_enum", create_type=False)


def upgrade() -> None:
    op.add_column("espacios", sa.Column("sede", sede_enum, nullable=True))
    op.execute(
        """
        DO $$
        DECLARE invalidos text;
        BEGIN
            SELECT string_agg(DISTINCT id_sede::text, ', ') INTO invalidos
            FROM espacios WHERE id_sede NOT IN (1, 2);
            IF invalidos IS NOT NULL THEN
                RAISE EXCEPTION 'espacios.id_sede con valores sin sede conocida: %. '
                    'Sólo se admiten 1 (Ushuaia) y 2 (Río Grande); corregirlos antes de migrar.',
                    invalidos;
            END IF;
        END $$;
        """
    )
    op.execute(
        "UPDATE espacios SET sede = CASE id_sede WHEN 1 THEN 'Ushuaia'::sede_enum "
        "ELSE 'Río Grande'::sede_enum END"
    )
    op.alter_column("espacios", "sede", nullable=False)
    op.drop_index("ix_espacios_id_sede", table_name="espacios")
    op.drop_column("espacios", "id_sede")
    op.create_index("ix_espacios_sede", "espacios", ["sede"])

    op.execute(
        """
        DO $$
        DECLARE eliminadas integer;
        BEGIN
            DELETE FROM reservas_espacios r
            WHERE NOT EXISTS (SELECT 1 FROM usuarios u WHERE u.id = r.id_usuario);
            GET DIAGNOSTICS eliminadas = ROW_COUNT;
            IF eliminadas > 0 THEN
                RAISE NOTICE 'Se eliminaron % reservas con id_usuario inexistente (SPEC-02 D-03).',
                    eliminadas;
            END IF;
        END $$;
        """
    )
    op.create_foreign_key(
        "fk_reservas_espacios_id_usuario_usuarios",
        "reservas_espacios",
        "usuarios",
        ["id_usuario"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_reservas_espacios_id_usuario_usuarios", "reservas_espacios", type_="foreignkey"
    )
    op.add_column("espacios", sa.Column("id_sede", sa.Integer(), nullable=True))
    op.execute("UPDATE espacios SET id_sede = CASE sede WHEN 'Ushuaia' THEN 1 ELSE 2 END")
    op.alter_column("espacios", "id_sede", nullable=False)
    op.drop_index("ix_espacios_sede", table_name="espacios")
    op.drop_column("espacios", "sede")
    op.create_index("ix_espacios_id_sede", "espacios", ["id_sede"])
