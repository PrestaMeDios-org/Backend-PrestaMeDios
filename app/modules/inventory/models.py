"""Modelos ORM del módulo `inventory` (SQLAlchemy 2.0).

Tablas: ``categorias``, ``equipamientos`` (catálogo) y ``unidades_fisicas``
(existencias / stock).
"""

from enum import Enum

from sqlalchemy import CheckConstraint, ForeignKey, String, false, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.modules.inventory.enums import EstadoUnidadEnum, SedeEnum


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    """Persiste los *valores* de dominio del enum (ej. ``"Río Grande"``)
    en lugar de los nombres de miembro de Python (``RIO_GRANDE``)."""
    return [member.value for member in enum_cls]


class Categoria(Base):
    """Categoría del catálogo (ej. ``cameras`` → "Cámaras")."""

    __tablename__ = "categorias"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    color: Mapped[str | None] = mapped_column(String(7))


class Equipamiento(Base):
    """Ítem del catálogo de equipamiento disponible para préstamo."""

    __tablename__ = "equipamientos"
    __table_args__ = (
        CheckConstraint("max_dias_prestamo BETWEEN 1 AND 15", name="max_dias_prestamo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    nombre: Mapped[str] = mapped_column(String(150), index=True)
    marca: Mapped[str] = mapped_column(String(100))
    modelo: Mapped[str] = mapped_column(String(100))
    categoria_id: Mapped[str] = mapped_column(
        ForeignKey("categorias.id", ondelete="RESTRICT", onupdate="CASCADE"),
        index=True,
    )
    descripcion: Mapped[str | None] = mapped_column(String(500))
    max_dias_prestamo: Mapped[int] = mapped_column(default=4, server_default=text("4"))
    alta_gama: Mapped[bool] = mapped_column(default=False, server_default=false())
    imagen_url: Mapped[str | None] = mapped_column(String(500))
    video_url: Mapped[str | None] = mapped_column(String(500))
    reglas_cuidado: Mapped[list[str]] = mapped_column(
        ARRAY(String(300)), default=list, server_default=text("'{}'")
    )

    unidades: Mapped[list["UnidadFisica"]] = relationship(
        back_populates="equipamiento",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class UnidadFisica(Base):
    """Existencia física individual asociada a un ítem del catálogo."""

    __tablename__ = "unidades_fisicas"
    __table_args__ = (CheckConstraint("locker >= 1", name="locker_positivo"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    equipamiento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamientos.id", ondelete="CASCADE"),
        index=True,
    )
    numero_serie: Mapped[str] = mapped_column(String(100), unique=True)
    codigo_inventario: Mapped[str] = mapped_column(String(100), unique=True)
    sede: Mapped[SedeEnum] = mapped_column(
        SAEnum(SedeEnum, values_callable=_enum_values, name="sede_enum"),
        index=True,
    )
    locker: Mapped[int | None]
    estado: Mapped[EstadoUnidadEnum] = mapped_column(
        SAEnum(EstadoUnidadEnum, values_callable=_enum_values, name="estado_unidad_enum"),
        default=EstadoUnidadEnum.DISPONIBLE,
        server_default=text("'disponible'"),
        index=True,
    )

    equipamiento: Mapped["Equipamiento"] = relationship(
        back_populates="unidades", lazy="raise_on_sql"
    )
