"""Modelos ORM del Panel de Parámetros Globales (GLO-03, SPEC-01 §4.4, §4.5).

Catálogo cerrado: las claves sólo se crean/eliminan por migración (RN-18).
Prohibido almacenar secretos (RN-23).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    func,
    text,
    true,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import TipoParametro, enum_values
from app.database import Base

PARAMETRO_TIPO_ENUM = SAEnum(TipoParametro, values_callable=enum_values, name="parametro_tipo_enum")


class ParametroGlobal(Base):
    """Variable operativa tipada, editable sin tocar código (GLO-03)."""

    __tablename__ = "parametros_globales"
    __table_args__ = (
        CheckConstraint(
            r"clave ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'", name="clave_formato"
        ),
        CheckConstraint(
            "valor_min IS NULL OR valor_max IS NULL OR valor_min <= valor_max",
            name="rango_coherente",
        ),
        CheckConstraint("version >= 1", name="version_positiva"),
    )

    clave: Mapped[str] = mapped_column(String(100), primary_key=True)
    tipo: Mapped[TipoParametro] = mapped_column(PARAMETRO_TIPO_ENUM)
    valor: Mapped[Any] = mapped_column(JSONB)
    descripcion: Mapped[str] = mapped_column(String(300))
    unidad: Mapped[str | None] = mapped_column(String(20))
    valor_min: Mapped[Decimal | None] = mapped_column(Numeric)
    valor_max: Mapped[Decimal | None] = mapped_column(Numeric)
    editable: Mapped[bool] = mapped_column(default=True, server_default=true())
    version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    actualizado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ParametroGlobalHistorial(Base):
    """Traza inmutable de cada modificación de un parámetro (RN-22)."""

    __tablename__ = "parametros_globales_historial"
    __table_args__ = (
        Index("ix_parametros_globales_historial_clave_created_at", "clave", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    clave: Mapped[str] = mapped_column(
        ForeignKey("parametros_globales.clave", ondelete="CASCADE", onupdate="CASCADE")
    )
    valor_anterior: Mapped[Any] = mapped_column(JSONB)
    valor_nuevo: Mapped[Any] = mapped_column(JSONB)
    version: Mapped[int]
    motivo: Mapped[str | None] = mapped_column(String(300))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
