"""Contratos API (API-First) del módulo `inventory` (Pydantic v2).

- ``*Create``: payloads de entrada, estrictos (``extra="forbid"``, trim).
- ``*Response``: serializan modelos ORM vía ``from_attributes=True``.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.modules.inventory.enums import EstadoUnidadEnum, SedeEnum

_INPUT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)

HttpUrlStr = Annotated[str, Field(max_length=500, pattern=r"^https?://")]
ReglaCuidado = Annotated[str, Field(min_length=1, max_length=300)]


# ---------------------------------------------------------------------------
# Categoría
# ---------------------------------------------------------------------------
class CategoriaBase(BaseModel):
    id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$", examples=["cameras"])
    nombre: str = Field(min_length=1, max_length=100, examples=["Cámaras"])
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$", examples=["#1A4A7A"])


class CategoriaCreate(CategoriaBase):
    model_config = _INPUT_CONFIG


class CategoriaResponse(CategoriaBase):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# UnidadFisica (existencias / stock)
# ---------------------------------------------------------------------------
class UnidadFisicaBase(BaseModel):
    numero_serie: str = Field(min_length=1, max_length=100, examples=["SN-A7III-0001"])
    codigo_inventario: str = Field(min_length=1, max_length=100, examples=["CAM-S-01"])
    sede: SedeEnum
    locker: int | None = Field(default=None, ge=1, le=7, examples=[2])
    estado: EstadoUnidadEnum = EstadoUnidadEnum.DISPONIBLE


class UnidadFisicaCreate(UnidadFisicaBase):
    """Alta de unidad. ``sede`` es automática para ``ADMIN_LOCAL`` (PRE-19, SPEC-02 §4)."""

    model_config = _INPUT_CONFIG

    sede: SedeEnum | None = Field(default=None, examples=["Ushuaia"])  # type: ignore[assignment]


class UnidadFisicaResponse(UnidadFisicaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class UnidadFisicaEstadoUpdate(BaseModel):
    """Cambio manual de estado (ej. botón "Fuera de servicio" → mantenimiento)."""

    model_config = _INPUT_CONFIG

    estado: EstadoUnidadEnum


# ---------------------------------------------------------------------------
# Equipamiento (catálogo)
# ---------------------------------------------------------------------------
class EquipamientoBase(BaseModel):
    codigo: str = Field(min_length=1, max_length=30, examples=["CAM-001"])
    nombre: str = Field(min_length=1, max_length=150, examples=["Cámara Sony A7 III"])
    marca: str = Field(min_length=1, max_length=100, examples=["Sony"])
    modelo: str = Field(min_length=1, max_length=100, examples=["ILCE-7M3"])
    categoria_id: str = Field(min_length=1, max_length=50, examples=["cameras"])
    descripcion: str | None = Field(default=None, max_length=500)
    max_dias_prestamo: int = Field(default=4, ge=1, le=15)
    alta_gama: bool = False
    imagen_url: HttpUrlStr | None = None
    video_url: HttpUrlStr | None = None
    reglas_cuidado: list[ReglaCuidado] = Field(default_factory=list)


class EquipamientoCreate(EquipamientoBase):
    """Alta de un ítem con sus unidades físicas.

    ``max_dias_prestamo`` omitido toma ``prestamo.general.max_dias`` (GLO-03).
    """

    model_config = _INPUT_CONFIG

    max_dias_prestamo: int | None = Field(default=None, ge=1, le=15)  # type: ignore[assignment]

    unidades: list[UnidadFisicaCreate] = Field(default_factory=list)


class EquipamientoResponse(EquipamientoBase):
    """Ítem del catálogo con sus existencias y el stock lógico derivado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    unidades: list[UnidadFisicaResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cantidad_total(self) -> int:
        return sum(1 for u in self.unidades if u.estado is not EstadoUnidadEnum.BAJA)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cantidad_disponible(self) -> int:
        return sum(1 for u in self.unidades if u.estado is EstadoUnidadEnum.DISPONIBLE)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def en_mantenimiento(self) -> bool:
        activas = [u for u in self.unidades if u.estado is not EstadoUnidadEnum.BAJA]
        return bool(activas) and all(
            u.estado is EstadoUnidadEnum.MANTENIMIENTO for u in activas
        )
