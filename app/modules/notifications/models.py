"""Modelos ORM del módulo `notifications` (SPEC-06 §7).

Tablas: ``comunicados`` (NOV-02, Fase A) y ``notificaciones`` (NOV-04, Fase B).
Ninguna se borra físicamente (P7.3).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SedeEnum, enum_values
from app.database import Base
from app.modules.notifications.enums import EstadoComunicado, Severidad

ESTADO_COMUNICADO_ENUM = SAEnum(
    EstadoComunicado, values_callable=enum_values, name="estado_comunicado_enum"
)
SEVERIDAD_ENUM = SAEnum(Severidad, values_callable=enum_values, name="severidad_notificacion_enum")
# `sede_enum` es compartido con `usuarios` e `inventory`: no se crea desde acá.
SEDE_ENUM_COMPARTIDO = PGEnum(
    SedeEnum, values_callable=enum_values, name="sede_enum", create_type=False
)


class Comunicado(Base):
    """Comunicado de una sede o global (NOV-02, GLO-01)."""

    __tablename__ = "comunicados"
    __table_args__ = (
        CheckConstraint(
            "(es_global AND sede IS NULL) OR (NOT es_global AND sede IS NOT NULL)",
            name="alcance_coherente",
        ),
        CheckConstraint(
            "vence_en IS NULL OR vence_en > publicado_en", name="vence_despues_de_publicar"
        ),
        CheckConstraint("length(contenido) <= 5000", name="contenido_largo_maximo"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=False), primary_key=True)
    titulo: Mapped[str] = mapped_column(String(150))
    contenido: Mapped[str] = mapped_column(Text)
    sede: Mapped[SedeEnum | None] = mapped_column(SEDE_ENUM_COMPARTIDO)
    es_global: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    estado: Mapped[EstadoComunicado] = mapped_column(
        ESTADO_COMUNICADO_ENUM,
        default=EstadoComunicado.PUBLICADO,
        server_default=text("'PUBLICADO'"),
    )
    autor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    publicado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    vence_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index(
    "ix_comunicados_estado_sede_publicado",
    Comunicado.estado,
    Comunicado.sede,
    Comunicado.publicado_en.desc(),
)


class Notificacion(Base):
    """Aviso personal a un único destinatario (NOV-04, SPEC-06 RN-N6)."""

    __tablename__ = "notificaciones"
    __table_args__ = (
        CheckConstraint(
            "(referencia_modulo IS NULL) = (referencia_id IS NULL)", name="referencia_completa"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT")
    )
    tipo: Mapped[str] = mapped_column(String(50))
    severidad: Mapped[Severidad] = mapped_column(SEVERIDAD_ENUM)
    titulo: Mapped[str] = mapped_column(String(150))
    mensaje: Mapped[str] = mapped_column(String(1000))
    referencia_modulo: Mapped[str | None] = mapped_column(String(30))
    referencia_id: Mapped[int | None] = mapped_column(BigInteger)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    leida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "ix_notificaciones_usuario_creada",
    Notificacion.usuario_id,
    Notificacion.creada_en.desc(),
)
Index(
    "ix_notificaciones_no_leidas",
    Notificacion.usuario_id,
    postgresql_where=Notificacion.leida_en.is_(None),
)
