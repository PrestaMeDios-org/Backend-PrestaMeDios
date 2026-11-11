"""SPEC-09 Fase A · horario y correo de contacto por sede (GLO-03, ADR-022 a y c).

Inserta seis parámetros por sede y deja ``horario.apertura`` y ``horario.cierre``
como obsoletos y no editables (RN-81, D-02). El horario de cada sede arranca con el
valor vigente de las claves globales, no con el de la semilla (D-03); los correos
arrancan en ``""``, "sin configurar" (D-05).

Cuelga de ``0018_spaces_bloqueos_reversion`` (SPEC-08 v1.1.0), que entró antes a
``develop``: la que se mergea segunda reapunta su ``down_revision`` a la cabeza de
``develop`` (D-22 de SPEC-03). Alembic encadena por id, no por número: 0016 → 0018 → 0017.

Revision ID: 0017_config_sedes
Revises: 0018_spaces_bloqueos_reversion
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_config_sedes"
down_revision: Union[str, None] = "0018_spaces_bloqueos_reversion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Copia congelada (SPEC-09 §4.1): (clave, tipo, valor de la semilla, descripcion,
# unidad, valor_min, valor_max). `tests/config/test_semilla.py` la compara con
# `app.modules.config.seed.PARAMETROS_SEMILLA`.
_NOTA_TRANSICION = (
    " Hasta que reservas y préstamos lean el horario de cada sede, rige el global (SPEC-09 EC-51)."
)
CLAVES_NUEVAS = [
    ("horario.ushuaia.apertura", "HORA", "09:00",
     "Hora de apertura del laboratorio de Ushuaia (GLO-02, GLO-03)." + _NOTA_TRANSICION,
     None, None, None),
    ("horario.ushuaia.cierre", "HORA", "16:00",
     "Hora de cierre del laboratorio de Ushuaia (GLO-02, GLO-03)." + _NOTA_TRANSICION,
     None, None, None),
    ("horario.rio_grande.apertura", "HORA", "09:00",
     "Hora de apertura del laboratorio de Río Grande (GLO-02, GLO-03)." + _NOTA_TRANSICION,
     None, None, None),
    ("horario.rio_grande.cierre", "HORA", "16:00",
     "Hora de cierre del laboratorio de Río Grande (GLO-02, GLO-03)." + _NOTA_TRANSICION,
     None, None, None),
    ("contacto.ushuaia.email", "TEXTO", "",
     "Correo de contacto del laboratorio de Ushuaia, para el aviso de anticipación mínima "
     "(ADR-022 c). Vacío: sin configurar.",
     None, None, None),
    ("contacto.rio_grande.email", "TEXTO", "",
     "Correo de contacto del laboratorio de Río Grande, para el aviso de anticipación mínima "
     "(ADR-022 c). Vacío: sin configurar.",
     None, None, None),
]

# Las claves de horario por sede copian el valor vigente de la global (D-03).
ORIGEN = {
    "horario.ushuaia.apertura": "horario.apertura",
    "horario.ushuaia.cierre": "horario.cierre",
    "horario.rio_grande.apertura": "horario.apertura",
    "horario.rio_grande.cierre": "horario.cierre",
}

CLAVES_OBSOLETAS = ("horario.apertura", "horario.cierre")
PREFIJO_OBSOLETA = "Obsoleta (SPEC-09): usar el horario de cada sede. "


def upgrade() -> None:
    bind = op.get_bind()

    copiar = sa.text(
        "INSERT INTO parametros_globales "
        "(clave, tipo, valor, descripcion, unidad, valor_min, valor_max) "
        "SELECT :clave, CAST(:tipo AS parametro_tipo_enum), valor, :descripcion, "
        ":unidad, :valor_min, :valor_max "
        "FROM parametros_globales WHERE clave = :origen"
    )
    insertar = sa.text(
        "INSERT INTO parametros_globales "
        "(clave, tipo, valor, descripcion, unidad, valor_min, valor_max) "
        "VALUES (:clave, CAST(:tipo AS parametro_tipo_enum), CAST(:valor AS jsonb), "
        ":descripcion, :unidad, :valor_min, :valor_max)"
    )
    for clave, tipo, valor, descripcion, unidad, vmin, vmax in CLAVES_NUEVAS:
        datos = {
            "clave": clave, "tipo": tipo, "descripcion": descripcion,
            "unidad": unidad, "valor_min": vmin, "valor_max": vmax,
        }
        if clave in ORIGEN:
            filas = bind.execute(copiar, {**datos, "origen": ORIGEN[clave]}).rowcount
            if filas != 1:
                raise RuntimeError(f"Falta el parámetro '{ORIGEN[clave]}' para copiar su valor.")
        else:
            bind.execute(insertar, {**datos, "valor": json.dumps(valor)})

    bind.execute(
        sa.text(
            "UPDATE parametros_globales "
            "SET editable = false, descripcion = :prefijo || descripcion "
            "WHERE clave IN :claves AND NOT starts_with(descripcion, :prefijo)"
        ).bindparams(sa.bindparam("claves", expanding=True)),
        {"prefijo": PREFIJO_OBSOLETA, "claves": list(CLAVES_OBSOLETAS)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    # El historial de las claves nuevas se borra por ON DELETE CASCADE.
    bind.execute(
        sa.text("DELETE FROM parametros_globales WHERE clave IN :claves").bindparams(
            sa.bindparam("claves", expanding=True)
        ),
        {"claves": [c[0] for c in CLAVES_NUEVAS]},
    )
    bind.execute(
        sa.text(
            "UPDATE parametros_globales "
            "SET editable = true, "
            "descripcion = CASE WHEN starts_with(descripcion, :prefijo) "
            "THEN substr(descripcion, char_length(:prefijo) + 1) ELSE descripcion END "
            "WHERE clave IN :claves"
        ).bindparams(sa.bindparam("claves", expanding=True)),
        {"prefijo": PREFIJO_OBSOLETA, "claves": list(CLAVES_OBSOLETAS)},
    )
