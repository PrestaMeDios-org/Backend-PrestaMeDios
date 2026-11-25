"""loans: ciclo de entrega y devolución en el mostrador (SPEC-05 Fase 3, §7.2)

En ``detalles_prestamo``:

- ``entregado_en`` y ``devuelto_en``: cuándo se entregó y se recibió el equipo (PRE-13).
- ``observacion_devolucion``: estado físico al devolver; alimenta el historial de la
  unidad (PRE-12).
- ``motivo_cancelacion``: motivo de la cancelación forzada de la línea (PRE-17).
- ``CHECK`` ``entrega_registrada`` y ``devolucion_registrada``: una línea entregada
  tiene fecha de entrega, y una devuelta, las dos (P7.1).

Antes de crear los ``CHECK`` se completan las líneas viejas en ``entregado`` o
``devuelto`` con las fechas pactadas (plan §9.2, V12): ningún endpoint las creaba,
pero una base de pruebas podría tenerlas.

La spec la preveía como ``0012``; ese número ya se usó (C19).

Revision ID: 0022_loans_ciclo_entrega
Revises: 0021_core_envios_correo
Create Date: 2026-11-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_loans_ciclo_entrega"
down_revision: Union[str, None] = "0021_core_envios_correo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "detalles_prestamo"
COLUMNAS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("entregado_en", sa.DateTime(timezone=True)),
    ("devuelto_en", sa.DateTime(timezone=True)),
    ("observacion_devolucion", sa.String(500)),
    ("motivo_cancelacion", sa.String(500)),
)

# SQL directo para los CHECK: con `op.create_check_constraint` la NAMING_CONVENTION
# volvería a prefijar el nombre (DT-26, hallazgo de la migración 0010).
CHECKS: tuple[tuple[str, str], ...] = (
    (
        "ck_detalles_prestamo_entrega_registrada",
        "estado <> 'entregado' OR entregado_en IS NOT NULL",
    ),
    (
        "ck_detalles_prestamo_devolucion_registrada",
        "estado <> 'devuelto' OR (entregado_en IS NOT NULL AND devuelto_en IS NOT NULL)",
    ),
)

COMPLETAR_FECHAS = (
    "UPDATE detalles_prestamo SET "
    "entregado_en = COALESCE(entregado_en, retiro_pactado), "
    "devuelto_en = CASE WHEN estado = 'devuelto' "
    "THEN COALESCE(devuelto_en, devolucion_pactada) ELSE devuelto_en END "
    "WHERE estado IN ('entregado', 'devuelto')"
)


def upgrade() -> None:
    for nombre, tipo in COLUMNAS:
        op.add_column(TABLA, sa.Column(nombre, tipo, nullable=True))
    op.execute(COMPLETAR_FECHAS)
    for nombre, condicion in CHECKS:
        op.execute(f"ALTER TABLE {TABLA} ADD CONSTRAINT {nombre} CHECK ({condicion})")


def downgrade() -> None:
    for nombre, _ in reversed(CHECKS):
        op.execute(f"ALTER TABLE {TABLA} DROP CONSTRAINT {nombre}")
    for nombre, _ in reversed(COLUMNAS):
        op.drop_column(TABLA, nombre)
