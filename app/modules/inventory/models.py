"""Modelos ORM del módulo `inventory` (SQLAlchemy 2.0).

Mapean los contratos API-First de ``schemas.py`` a las tablas
``equipamientos`` (catálogo) y ``unidades_fisicas`` (existencias / stock).
"""

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.modules.inventory.schemas import EstadoUnidadEnum, SedeEnum


def _enum_values(enum_cls: type) -> list[str]:
    """Persiste los *valores* de dominio del enum (ej. ``"Ushuaia"``,
    ``"disponible"``) en lugar de los nombres de miembro de Python."""
    return [member.value for member in enum_cls]


class Equipamiento(Base):
    """Ítem del catálogo de equipamiento disponible para préstamo."""

    __tablename__ = "equipamientos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    marca: Mapped[str] = mapped_column(String(100), nullable=False)
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    categoria: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    descripcion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_dias_prestamo: Mapped[int] = mapped_column(default=4, nullable=False)
    alta_gama: Mapped[bool] = mapped_column(default=False, nullable=False)
    imagen_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    unidades: Mapped[list["UnidadFisica"]] = relationship(
        back_populates="equipamiento",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UnidadFisica(Base):
    """Existencia física individual asociada a un ítem del catálogo."""

    __tablename__ = "unidades_fisicas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    equipamiento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamientos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    numero_serie: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    codigo_inventario: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    sede: Mapped[SedeEnum] = mapped_column(
        SAEnum(SedeEnum, values_callable=_enum_values, name="sede_enum"),
        nullable=False,
        index=True,
    )
    locker: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estado: Mapped[EstadoUnidadEnum] = mapped_column(
        SAEnum(EstadoUnidadEnum, values_callable=_enum_values, name="estado_unidad_enum"),
        default=EstadoUnidadEnum.DISPONIBLE,
        nullable=False,
        index=True,
    )

    equipamiento: Mapped["Equipamiento"] = relationship(back_populates="unidades")
