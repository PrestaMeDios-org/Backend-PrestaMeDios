"""Modelos ORM del dominio `spaces` (SQLAlchemy 2.0).

Mapean los contratos API-First de ``app/modules/spaces/schemas.py`` a las tablas
``reservas_espacios`` (reservas de espacios físicos) y
``bloqueos_espacios`` (bloqueos administrativos por contingencia o
mantenimiento, RES-04 / GLO-04).
"""

import uuid
from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time, text
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SedeEnum, enum_values
from app.database import Base

# `sede_enum` es compartido (usuarios, unidades_fisicas): lo crean las migraciones.
SEDE_ENUM_ESPACIO = PGEnum(
    SedeEnum, values_callable=enum_values, name="sede_enum", create_type=False
)


class Espacio(Base):
    """Espacio físico reservable (Aula-Estudio, Isla de Edición, etc.)."""

    __tablename__ = "espacios"

    id_espacio: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    sede: Mapped[SedeEnum] = mapped_column(SEDE_ENUM_ESPACIO, nullable=False, index=True)
    tipo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class ReservaEspacio(Base):
    """Reserva de un espacio físico por parte de un usuario."""

    __tablename__ = "reservas_espacios"

    __table_args__ = (
        # REGLA CRÍTICA ACID (integridad referencial temporal):
        # evita a nivel de base de datos que dos reservas del MISMO
        # `id_espacio` se solapen en el tiempo mientras ambas estén en
        # estado 'Aprobada'. No hace falta ningún `if` en Python: la
        # propia restricción GIST rechaza el INSERT/UPDATE conflictivo
        # con error de integridad, incluso bajo concurrencia.
        #
        # Requiere la extensión:  CREATE EXTENSION IF NOT EXISTS btree_gist;
        #
        # - id_espacio con operador '='  -> solo se comparan filas del
        #   mismo espacio.
        # - tsrange(...) con operador '&&' (solapa) -> dos franjas se
        #   excluyen mutuamente si sus rangos se intersectan.
        # - where=... -> la restricción es CONDICIONAL: solo aplica a
        #   filas con estado_reserva = 'Aprobada', por lo que las
        #   reservas Pendientes/Rechazadas/Canceladas pueden coexistir
        #   en la misma franja sin conflicto.
        ExcludeConstraint(
            ("id_espacio", "="),
            (
                text(
                    "tsrange("
                    "CAST(fecha_reserva AS TIMESTAMP) + hora_inicio::interval, "
                    "CAST(fecha_reserva AS TIMESTAMP) + hora_fin::interval"
                    ")"
                ),
                "&&",
            ),
            where=text("estado_reserva IN ('Aprobada', 'En_Uso')"),
            name="excl_reserva_aprobada_sin_solapamiento",
            using="gist",
        ),
    )

    id_reserva: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_usuario: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    id_espacio: Mapped[int] = mapped_column(
        ForeignKey("espacios.id_espacio", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha_reserva: Mapped[date] = mapped_column(Date, nullable=False)
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[time] = mapped_column(Time, nullable=False)
    estado_reserva: Mapped[str] = mapped_column(
        String(20), default="Pendiente", server_default="Pendiente", nullable=False
    )
    motivo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class BloqueoEspacio(Base):
    """Bloqueo administrativo de un espacio (mantenimiento/contingencia).

    Nunca se borra (SPEC-08 D-S01, P7.3): deshacerlo completa ``revertido_en`` y
    ``revertido_por``, y sólo los bloqueos sin ``revertido_en`` afectan la
    disponibilidad. Las filas de un bloqueo general comparten ``id_grupo`` (D-S03).
    """

    __tablename__ = "bloqueos_espacios"

    id_bloqueo: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id_espacio: Mapped[int] = mapped_column(
        ForeignKey("espacios.id_espacio", ondelete="CASCADE"), nullable=False, index=True
    )
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    hora_inicio: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    hora_fin: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    # 0018 (SPEC-08 v1.1.0, GLO-04): grupo del bloqueo general y reversión lógica.
    id_grupo: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    revertido_en: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revertido_por: Mapped[Optional[int]] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
