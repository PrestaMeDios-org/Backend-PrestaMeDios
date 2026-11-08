"""Modelos ORM del módulo `users` (SPEC-01 §4.2, §4.3).

Tablas: ``usuarios``, ``usuarios_historial_estado``, ``usuarios_historial_cambios`` y,
para USR-02, ``tokens_recuperacion`` e ``intentos_recuperacion`` (SPEC-03 §5.2). No hay borrado físico
de usuarios: la baja es lógica (``INACTIVO``, RN-17).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    false,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum, enum_values
from app.database import Base

# Registra `archivos` en la metadata: `usuarios.foto_id` la referencia (SPEC-03 §6.2).
from app.modules.files import models as _files_models  # noqa: E402, F401

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
    debe_cambiar_password: Mapped[bool] = mapped_column(default=False, server_default=false())
    ultimo_login_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprobado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Foto vigente (USR-03). `use_alter`: ciclo con `archivos.propietario_id`.
    foto_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("archivos.id", ondelete="SET NULL", use_alter=True),
    )
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


class UsuarioHistorialCambios(Base):
    """Traza inmutable de ediciones de perfil (SPEC-02 RN-34, USR-08).

    ``cambios`` = ``{campo: [antes, después]}``; nunca contiene contraseñas.
    """

    __tablename__ = "usuarios_historial_cambios"
    __table_args__ = (
        Index(
            "ix_usuarios_historial_cambios_usuario_id_created_at", "usuario_id", "created_at"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    cambios: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TokenRecuperacion(Base):
    """Token de recuperación de contraseña (USR-02, SPEC-03 RN-46…RN-48).

    Se guarda sólo el SHA-256 del token, nunca el token.
    """

    __tablename__ = "tokens_recuperacion"
    __table_args__ = (
        Index("ix_tokens_recuperacion_usuario_id_usado_en", "usuario_id", "usado_en"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IntentoRecuperacion(Base):
    """Solicitud de recuperación, para el límite por email y por IP (SPEC-03 RN-49).

    Guarda un HMAC del email normalizado, no el email. Sin FK: se cuenta exista o no
    la cuenta.
    """

    __tablename__ = "intentos_recuperacion"
    __table_args__ = (
        Index("ix_intentos_recuperacion_email_hash_created_at", "email_hash", "created_at"),
        Index("ix_intentos_recuperacion_ip_created_at", "ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    email_hash: Mapped[str] = mapped_column(CHAR(64))
    ip: Mapped[str] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
