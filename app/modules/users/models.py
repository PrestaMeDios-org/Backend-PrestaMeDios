"""Modelos ORM del módulo `users` (SPEC-01 §4.2, §4.3).

Tablas: ``usuarios`` y ``usuarios_historial_estado``. No hay borrado físico
de usuarios: la baja es lógica (``INACTIVO``, RN-17).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum, enum_values
from app.database import Base

ROL_USUARIO_ENUM = SAEnum(RolUsuario, values_callable=enum_values, name="rol_usuario_enum")
ESTADO_CUENTA_ENUM = SAEnum(EstadoCuenta, values_callable=enum_values, name="estado_cuenta_enum")
# `sede_enum` es compartido con `inventory.unidades_fisicas`: lo crea la
# migración de forma idempotente, por eso no se emite CREATE TYPE desde aquí.
SEDE_ENUM_COMPARTIDO = PGEnum(
    SedeEnum, values_callable=enum_values, name="sede_enum", create_type=False
)


class Usuario(Base):
    """Cuenta de usuario con rol y alcance de sede (USR-01, USR-05, GLO-01)."""

    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_minusculas"),
        CheckConstraint("dni ~ '^[0-9]{7,8}$'", name="dni_numerico"),
        CheckConstraint(
            "(rol = 'SUPERADMIN' AND sede IS NULL) OR (rol <> 'SUPERADMIN' AND sede IS NOT NULL)",
            name="sede_segun_rol",
        ),
        CheckConstraint(
            "suspendido_hasta IS NULL OR estado = 'SUSPENDIDO'", name="suspension_coherente"
        ),
        CheckConstraint("token_version >= 0", name="token_version_no_negativa"),
        Index("ix_usuarios_sede_rol_estado", "sede", "rol", "estado"),
        Index("ix_usuarios_estado_created_at", "estado", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nombre: Mapped[str] = mapped_column(String(100))
    apellido: Mapped[str] = mapped_column(String(100))
    dni: Mapped[str] = mapped_column(String(8), unique=True)
    telefono: Mapped[str | None] = mapped_column(String(20))
    rol: Mapped[RolUsuario] = mapped_column(ROL_USUARIO_ENUM)
    sede: Mapped[SedeEnum | None] = mapped_column(SEDE_ENUM_COMPARTIDO)
    estado: Mapped[EstadoCuenta] = mapped_column(
        ESTADO_CUENTA_ENUM,
        default=EstadoCuenta.PENDIENTE_APROBACION,
        server_default=text("'PENDIENTE_APROBACION'"),
    )
    motivo_estado: Mapped[str | None] = mapped_column(String(500))
    suspendido_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    ultimo_login_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprobado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsuarioHistorialEstado(Base):
    """Traza inmutable de transiciones de estado de cuentas (RN-22, USR-08)."""

    __tablename__ = "usuarios_historial_estado"
    __table_args__ = (
        Index(
            "ix_usuarios_historial_estado_usuario_id_created_at", "usuario_id", "created_at"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    estado_anterior: Mapped[EstadoCuenta | None] = mapped_column(ESTADO_CUENTA_ENUM)
    estado_nuevo: Mapped[EstadoCuenta] = mapped_column(ESTADO_CUENTA_ENUM)
    motivo: Mapped[str | None] = mapped_column(String(500))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
