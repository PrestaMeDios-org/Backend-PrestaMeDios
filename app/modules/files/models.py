"""Modelos ORM del módulo `files` (SPEC-03 §6.2, migración ``0014_files_init``).

- ``archivos``: metadatos. ``sede`` es la del propietario al subir (nula para
  ``SUPERADMIN``) y decide la jurisdicción del aval (RN-60, EC-44).
- ``archivos_contenido``: los bytes, en una tabla aparte para que las consultas de
  metadatos no los lean (D-10). La clase se llama ``ArchivoDatos`` para no chocar con
  ``ArchivoContenido``, el dataclass público de ``service.py`` (§6.5).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SedeEnum, enum_values
from app.database import Base
from app.modules.files.enums import PropositoArchivo

PROPOSITO_ARCHIVO_ENUM = SAEnum(
    PropositoArchivo, values_callable=enum_values, name="proposito_archivo_enum"
)
# `sede_enum` es compartido y ya existe (0005/0006): no se emite CREATE TYPE.
_SEDE_ENUM = PGEnum(SedeEnum, values_callable=enum_values, name="sede_enum", create_type=False)


class Archivo(Base):
    """Metadatos de un archivo subido (USR-03, PRE-05)."""

    __tablename__ = "archivos"
    __table_args__ = (
        CheckConstraint("tamano_bytes > 0", name="tamano_positivo"),
        Index("ix_archivos_vinculado_en_created_at", "vinculado_en", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    propietario_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("usuarios.id", ondelete="RESTRICT")
    )
    proposito: Mapped[PropositoArchivo] = mapped_column(PROPOSITO_ARCHIVO_ENUM)
    sede: Mapped[SedeEnum | None] = mapped_column(_SEDE_ENUM)
    tipo_mime: Mapped[str] = mapped_column(String(100))
    tamano_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    nombre_original: Mapped[str] = mapped_column(String(255))
    vinculado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ArchivoDatos(Base):
    """Contenido binario de un archivo (D-10). Se borra con su ``Archivo`` (``CASCADE``)."""

    __tablename__ = "archivos_contenido"

    archivo_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("archivos.id", ondelete="CASCADE"), primary_key=True
    )
    datos: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
