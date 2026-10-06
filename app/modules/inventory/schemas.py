"""Contratos API (API-First) del módulo `inventory`.

Estos esquemas Pydantic v2 definen el contrato OpenAPI del dominio de
Catálogo y Existencias *antes* de cualquier implementación de persistencia.
Los esquemas ``Response`` usan ``from_attributes=True`` para serializar
directamente los modelos ORM de SQLAlchemy.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums de dominio
# ---------------------------------------------------------------------------
class SedeEnum(str, Enum):
    """Sedes físicas donde se aloja el equipamiento."""

    USHUAIA = "Ushuaia"
    RIO_GRANDE = "Río Grande"


class EstadoUnidadEnum(str, Enum):
    """Ciclo de vida de una unidad física dentro del inventario."""

    DISPONIBLE = "disponible"
    PRESTADO = "prestado"
    MANTENIMIENTO = "mantenimiento"
    BAJA = "baja"


# ---------------------------------------------------------------------------
# UnidadFisica (existencias / stock)
# ---------------------------------------------------------------------------
class UnidadFisicaBase(BaseModel):
    """Campos compartidos del contrato de una unidad física."""

    numero_serie: str = Field(..., max_length=100, examples=["SN-GOPRO12-0001"])
    codigo_inventario: str = Field(..., max_length=100, examples=["INV-USH-0001"])
    sede: SedeEnum
    locker: Optional[str] = Field(default=None, max_length=50, examples=["L-12"])
    estado: EstadoUnidadEnum = EstadoUnidadEnum.DISPONIBLE


class UnidadFisicaCreate(UnidadFisicaBase):
    """Payload para dar de alta una unidad física."""


class UnidadFisicaResponse(UnidadFisicaBase):
    """Representación pública de una unidad física persistida."""

    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------------------------------------------------------------------------
# Equipamiento (catálogo)
# ---------------------------------------------------------------------------
class EquipamientoBase(BaseModel):
    """Campos compartidos del contrato de un ítem del catálogo."""

    nombre: str = Field(..., max_length=150, examples=["Cámara GoPro Hero 12"])
    marca: str = Field(..., max_length=100, examples=["GoPro"])
    modelo: str = Field(..., max_length=100, examples=["Hero 12 Black"])
    categoria: str = Field(..., max_length=100, examples=["Cámaras de acción"])
    descripcion: Optional[str] = None
    max_dias_prestamo: int = Field(default=4, ge=1)
    alta_gama: bool = False
    imagen_url: Optional[str] = Field(default=None, max_length=500)


class EquipamientoCreate(EquipamientoBase):
    """Payload para dar de alta un ítem del catálogo.

    Permite registrar opcionalmente sus unidades físicas en la misma operación.
    """

    unidades: list[UnidadFisicaCreate] = Field(default_factory=list)


class EquipamientoResponse(EquipamientoBase):
    """Representación pública de un ítem del catálogo con sus existencias."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    unidades: list[UnidadFisicaResponse] = Field(default_factory=list)
