"""users y parametros globales: usuarios, historial de estados, parametros + semilla (SPEC-01)

Revision ID: 0005_users_y_parametros
Revises: 0004_bloqueos_created_at
Create Date: 2026-10-07
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_users_y_parametros"
down_revision: Union[str, None] = "0004_bloqueos_created_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Copia congelada de `app.modules.config.seed.PARAMETROS_SEMILLA` (SPEC-01 §11.2).
# Las migraciones no importan código de la app para no cambiar retroactivamente;
# `tests/config/test_semilla.py` verifica que ambas coincidan.
PARAMETROS_SEMILLA = [
    ("prestamo.general.max_dias", "ENTERO", 4,
     "Duración máxima de un préstamo general de equipamiento (PRE-07).", "días", 1, 15),
    ("prestamo.notebook.max_dias", "ENTERO", 15,
     "Duración máxima de un préstamo de notebook.", "días", 1, 30),
    ("solicitud.anticipacion_min_horas", "ENTERO", 24,
     "Anticipación mínima entre el envío de una solicitud (préstamo o reserva) "
     "y el inicio del retiro o turno (D-07).", "horas", 0, 168),
    ("prestamo.tolerancia_retiro_horas", "ENTERO", 2,
     "Margen para retirar un equipo antes de la cancelación automática (PRE-08).", "horas", 0, 24),
    ("notificacion.aviso_vencimiento_horas", "ENTERO", 24,
     "Antelación del aviso de vencimiento de un préstamo (NOV-03).", "horas", 1, 168),
    ("horario.apertura", "HORA", "09:00",
     "Hora de apertura operativa del laboratorio (GLO-02).", None, None, None),
    ("horario.cierre", "HORA", "16:00",
     "Hora de cierre operativo del laboratorio (GLO-02).", None, None, None),
    ("reserva_espacio.anticipacion_max_dias", "ENTERO", 120,
     "Cuántos días a futuro se pueden solicitar reservas de espacios.", "días", 1, 365),
]

rol_usuario_enum = postgresql.ENUM(
    "SUPERADMIN", "ADMIN_LOCAL", "DOCENTE", "ESTUDIANTE", name="rol_usuario_enum", create_type=False
)
estado_cuenta_enum = postgresql.ENUM(
    "PENDIENTE_APROBACION", "ACTIVO", "RECHAZADO", "SUSPENDIDO", "INACTIVO",
    name="estado_cuenta_enum", create_type=False,
)
parametro_tipo_enum = postgresql.ENUM(
    "ENTERO", "DECIMAL", "BOOLEANO", "TEXTO", "HORA", name="parametro_tipo_enum", create_type=False
)
sede_enum = postgresql.ENUM("Ushuaia", "Río Grande", name="sede_enum", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    rol_usuario_enum.create(bind, checkfirst=True)
    estado_cuenta_enum.create(bind, checkfirst=True)
    parametro_tipo_enum.create(bind, checkfirst=True)
    # `sede_enum` es compartido con inventory.unidades_fisicas: crear sólo si no existe.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sede_enum AS ENUM ('Ushuaia', 'Río Grande');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("apellido", sa.String(100), nullable=False),
        sa.Column("dni", sa.String(8), nullable=False),
        sa.Column("telefono", sa.String(20), nullable=True),
        sa.Column("rol", rol_usuario_enum, nullable=False),
        sa.Column("sede", sede_enum, nullable=True),
        sa.Column(
            "estado", estado_cuenta_enum, nullable=False,
            server_default=sa.text("'PENDIENTE_APROBACION'"),
        ),
        sa.Column("motivo_estado", sa.String(500), nullable=True),
        sa.Column("suspendido_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ultimo_login_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aprobado_por_id", sa.Integer(), nullable=True),
        sa.Column("aprobado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_usuarios"),
        sa.UniqueConstraint("email", name="uq_usuarios_email"),
        sa.UniqueConstraint("dni", name="uq_usuarios_dni"),
        sa.ForeignKeyConstraint(
            ["aprobado_por_id"], ["usuarios.id"],
            name="fk_usuarios_aprobado_por_id_usuarios", ondelete="SET NULL",
        ),
        sa.CheckConstraint("email = lower(email)", name="ck_usuarios_email_minusculas"),
        sa.CheckConstraint("dni ~ '^[0-9]{7,8}$'", name="ck_usuarios_dni_numerico"),
        sa.CheckConstraint(
            "(rol = 'SUPERADMIN' AND sede IS NULL) OR (rol <> 'SUPERADMIN' AND sede IS NOT NULL)",
            name="ck_usuarios_sede_segun_rol",
        ),
        sa.CheckConstraint(
            "suspendido_hasta IS NULL OR estado = 'SUSPENDIDO'",
            name="ck_usuarios_suspension_coherente",
        ),
        sa.CheckConstraint("token_version >= 0", name="ck_usuarios_token_version_no_negativa"),
    )
    op.create_index("ix_usuarios_sede_rol_estado", "usuarios", ["sede", "rol", "estado"])
    op.create_index("ix_usuarios_estado_created_at", "usuarios", ["estado", "created_at"])

    op.create_table(
        "usuarios_historial_estado",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("estado_anterior", estado_cuenta_enum, nullable=True),
        sa.Column("estado_nuevo", estado_cuenta_enum, nullable=False),
        sa.Column("motivo", sa.String(500), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_usuarios_historial_estado"),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"],
            name="fk_usuarios_historial_estado_usuario_id_usuarios", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["usuarios.id"],
            name="fk_usuarios_historial_estado_actor_id_usuarios", ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_usuarios_historial_estado_usuario_id_created_at",
        "usuarios_historial_estado", ["usuario_id", "created_at"],
    )

    op.create_table(
        "parametros_globales",
        sa.Column("clave", sa.String(100), nullable=False),
        sa.Column("tipo", parametro_tipo_enum, nullable=False),
        sa.Column("valor", postgresql.JSONB(), nullable=False),
        sa.Column("descripcion", sa.String(300), nullable=False),
        sa.Column("unidad", sa.String(20), nullable=True),
        sa.Column("valor_min", sa.Numeric(), nullable=True),
        sa.Column("valor_max", sa.Numeric(), nullable=True),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("actualizado_por_id", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("clave", name="pk_parametros_globales"),
        sa.ForeignKeyConstraint(
            ["actualizado_por_id"], ["usuarios.id"],
            name="fk_parametros_globales_actualizado_por_id_usuarios", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            r"clave ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'",
            name="ck_parametros_globales_clave_formato",
        ),
        sa.CheckConstraint(
            "valor_min IS NULL OR valor_max IS NULL OR valor_min <= valor_max",
            name="ck_parametros_globales_rango_coherente",
        ),
        sa.CheckConstraint("version >= 1", name="ck_parametros_globales_version_positiva"),
    )

    op.create_table(
        "parametros_globales_historial",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("clave", sa.String(100), nullable=False),
        sa.Column("valor_anterior", postgresql.JSONB(), nullable=False),
        sa.Column("valor_nuevo", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(300), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_parametros_globales_historial"),
        sa.ForeignKeyConstraint(
            ["clave"], ["parametros_globales.clave"],
            name="fk_parametros_globales_historial_clave_parametros_globales",
            ondelete="CASCADE", onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["usuarios.id"],
            name="fk_parametros_globales_historial_actor_id_usuarios", ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_parametros_globales_historial_clave_created_at",
        "parametros_globales_historial", ["clave", "created_at"],
    )

    insertar = sa.text(
        "INSERT INTO parametros_globales "
        "(clave, tipo, valor, descripcion, unidad, valor_min, valor_max) "
        "VALUES (:clave, CAST(:tipo AS parametro_tipo_enum), CAST(:valor AS jsonb), "
        ":descripcion, :unidad, :valor_min, :valor_max)"
    )
    for clave, tipo, valor, descripcion, unidad, vmin, vmax in PARAMETROS_SEMILLA:
        bind.execute(
            insertar,
            {
                "clave": clave, "tipo": tipo, "valor": json.dumps(valor),
                "descripcion": descripcion, "unidad": unidad,
                "valor_min": vmin, "valor_max": vmax,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_parametros_globales_historial_clave_created_at", table_name="parametros_globales_historial")
    op.drop_table("parametros_globales_historial")
    op.drop_table("parametros_globales")
    op.drop_index("ix_usuarios_historial_estado_usuario_id_created_at", table_name="usuarios_historial_estado")
    op.drop_table("usuarios_historial_estado")
    op.drop_index("ix_usuarios_estado_created_at", table_name="usuarios")
    op.drop_index("ix_usuarios_sede_rol_estado", table_name="usuarios")
    op.drop_table("usuarios")

    bind = op.get_bind()
    parametro_tipo_enum.drop(bind, checkfirst=True)
    estado_cuenta_enum.drop(bind, checkfirst=True)
    rol_usuario_enum.drop(bind, checkfirst=True)
    # `sede_enum` sólo se elimina si ninguna columna lo usa (p. ej. inventory).
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sede_enum')
               AND NOT EXISTS (
                   SELECT 1 FROM pg_attribute a JOIN pg_type t ON a.atttypid = t.oid
                   WHERE t.typname = 'sede_enum' AND a.attnum > 0 AND NOT a.attisdropped
               ) THEN
                DROP TYPE sede_enum;
            END IF;
        END $$;
        """
    )
