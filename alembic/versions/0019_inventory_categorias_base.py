"""inventory: categorías base del catálogo (PRE-01, PRE-14)

Carga las cinco categorías de la demo para que el alta de equipos tenga de dónde
elegir sin pasar por ``POST /categorias``: Audio, Cámaras, Iluminación, Notebooks y
Trípodes. Los ids y colores de Cámaras, Iluminación y Audio son los de la plantilla
del frontend (``mockInventory.ts``). Pedido del Perfil 2.

- ``ON CONFLICT DO NOTHING``: si una base ya tiene alguna (por id o por nombre), no
  se duplica ni se pisa lo que el administrador haya cambiado.
- El ``downgrade`` borra sólo las que siguen como las dejó esta migración y ningún
  equipo usa: la FK de ``equipamientos`` es ``RESTRICT`` y no se pierden datos.

Cuelga de ``0017_config_sedes`` (SPEC-09, backend PR #35), que entra antes a
``develop`` (D-22 de SPEC-03). Alembic encadena por id, no por número:
0016 → 0018 → 0017 → 0019.

Revision ID: 0019_inventory_categorias_base
Revises: 0017_config_sedes
Create Date: 2026-11-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_inventory_categorias_base"
down_revision: Union[str, None] = "0017_config_sedes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (id, nombre, color), en el orden en que se muestran (por nombre).
CATEGORIAS = (
    ("audio", "Audio", "#1A7A4A"),
    ("cameras", "Cámaras", "#1A4A7A"),
    ("lighting", "Iluminación", "#A0620D"),
    ("notebooks", "Notebooks", "#6E6E73"),
    ("tripods", "Trípodes", "#5A2D82"),
)


def upgrade() -> None:
    insertar = sa.text(
        "INSERT INTO categorias (id, nombre, color) VALUES (:id, :nombre, :color) "
        "ON CONFLICT DO NOTHING"
    )
    for id_, nombre, color in CATEGORIAS:
        op.execute(insertar.bindparams(id=id_, nombre=nombre, color=color))


def downgrade() -> None:
    borrar = sa.text(
        "DELETE FROM categorias c WHERE c.id = :id AND c.nombre = :nombre "
        "AND NOT EXISTS (SELECT 1 FROM equipamientos e WHERE e.categoria_id = c.id)"
    )
    for id_, nombre, _color in CATEGORIAS:
        op.execute(borrar.bindparams(id=id_, nombre=nombre))
