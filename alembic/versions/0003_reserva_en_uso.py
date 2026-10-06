"""reservas: la restriccion de solapamiento tambien cubre 'En_Uso'

Revision ID: 0003_reserva_en_uso
Revises: 0002_espacios
Create Date: 2026-10-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003_reserva_en_uso"
down_revision: Union[str, None] = "0002_espacios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE reservas_espacios DROP CONSTRAINT excl_reserva_aprobada_sin_solapamiento")
    op.execute(
        """
        ALTER TABLE reservas_espacios
        ADD CONSTRAINT excl_reserva_aprobada_sin_solapamiento
        EXCLUDE USING gist (
            id_espacio WITH =,
            tsrange(
                CAST(fecha_reserva AS TIMESTAMP) + hora_inicio::interval,
                CAST(fecha_reserva AS TIMESTAMP) + hora_fin::interval
            ) WITH &&
        )
        WHERE (estado_reserva IN ('Aprobada', 'En_Uso'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE reservas_espacios DROP CONSTRAINT excl_reserva_aprobada_sin_solapamiento")
    op.execute(
        """
        ALTER TABLE reservas_espacios
        ADD CONSTRAINT excl_reserva_aprobada_sin_solapamiento
        EXCLUDE USING gist (
            id_espacio WITH =,
            tsrange(
                CAST(fecha_reserva AS TIMESTAMP) + hora_inicio::interval,
                CAST(fecha_reserva AS TIMESTAMP) + hora_fin::interval
            ) WITH &&
        )
        WHERE (estado_reserva = 'Aprobada')
        """
    )
