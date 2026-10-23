"""Contratos API (API-First) del módulo `inventory` (Pydantic v2).

- ``*Create``: payloads de entrada, estrictos (``extra="forbid"``, trim).
- ``*Response``: serializan modelos ORM vía ``from_attributes=True``.
"""

from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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
    """Cambio manual de estado (PRE-14). ``prestado`` lo gestiona sólo `loans` (SPEC-04 D-02)."""

    model_config = _INPUT_CONFIG

    estado: EstadoUnidadEnum = Field(examples=["mantenimiento"])


def _rechazar_nulos(modelo: BaseModel, anulables: frozenset[str]) -> None:
    for campo in modelo.model_fields_set:
        if getattr(modelo, campo) is None and campo not in anulables:
            raise ValueError(f"'{campo}' no puede ser nulo.")


class UnidadFisicaUpdate(BaseModel):
    """Edición de una unidad; la sede no se modifica (SPEC-04 RN-I1, PRE-12)."""

    model_config = _INPUT_CONFIG

    numero_serie: str | None = Field(
        default=None, min_length=1, max_length=100, examples=["SN-A7III-0001"]
    )
    codigo_inventario: str | None = Field(
        default=None, min_length=1, max_length=100, examples=["CAM-S-01"]
    )
    locker: int | None = Field(default=None, ge=1, le=7, examples=[2])

    @model_validator(mode="after")
    def _sin_nulos(self) -> "UnidadFisicaUpdate":
        _rechazar_nulos(self, frozenset({"locker"}))
        return self


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
    es_notebook: bool = Field(default=False, examples=[False])
    imagen_url: HttpUrlStr | None = None
    video_url: HttpUrlStr | None = None
    reglas_cuidado: list[ReglaCuidado] = Field(default_factory=list)


class EquipamientoCreate(EquipamientoBase):
    """Alta de un ítem con sus unidades físicas.

    ``max_dias_prestamo`` omitido toma ``prestamo.notebook.max_dias`` si
    ``es_notebook`` y, si no, ``prestamo.general.max_dias`` (GLO-03, SPEC-04 D-05).
    """

    model_config = _INPUT_CONFIG

    max_dias_prestamo: int | None = Field(default=None, ge=1, le=15)  # type: ignore[assignment]

    unidades: list[UnidadFisicaCreate] = Field(default_factory=list)


class EquipamientoUpdate(BaseModel):
    """Edición parcial de un ítem del catálogo. ``codigo`` es inmutable (PRE-12)."""

    model_config = _INPUT_CONFIG

    nombre: str | None = Field(default=None, min_length=1, max_length=150)
    marca: str | None = Field(default=None, min_length=1, max_length=100)
    modelo: str | None = Field(default=None, min_length=1, max_length=100)
    categoria_id: str | None = Field(default=None, min_length=1, max_length=50)
    descripcion: str | None = Field(default=None, max_length=500)
    max_dias_prestamo: int | None = Field(default=None, ge=1, le=15)
    alta_gama: bool | None = None
    es_notebook: bool | None = None
    imagen_url: HttpUrlStr | None = None
    video_url: HttpUrlStr | None = None
    reglas_cuidado: list[ReglaCuidado] | None = None

    @model_validator(mode="after")
    def _sin_nulos(self) -> "EquipamientoUpdate":
        _rechazar_nulos(self, frozenset({"descripcion", "imagen_url", "video_url"}))
        return self


class EquipamientoEstadoUpdate(BaseModel):
    """Baja y reactivación lógica de un ítem (RN-I5)."""

    model_config = _INPUT_CONFIG

    activo: bool = Field(examples=[False])


def _stock(unidades: Sequence[UnidadFisicaBase]) -> tuple[int, int, bool]:
    """(total, disponibles, en_mantenimiento) según RN-I4."""
    activas = [u for u in unidades if u.estado is not EstadoUnidadEnum.BAJA]
    disponibles = sum(1 for u in activas if u.estado is EstadoUnidadEnum.DISPONIBLE)
    en_mant = bool(activas) and all(u.estado is EstadoUnidadEnum.MANTENIMIENTO for u in activas)
    return len(activas), disponibles, en_mant


class EquipamientoResponse(EquipamientoBase):
    """Ítem del catálogo con sus existencias y el stock lógico derivado (administradores)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    activo: bool = True
    unidades: list[UnidadFisicaResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cantidad_total(self) -> int:
        return _stock(self.unidades)[0]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cantidad_disponible(self) -> int:
        return _stock(self.unidades)[1]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def en_mantenimiento(self) -> bool:
        return _stock(self.unidades)[2]


class EquipamientoPublicoResponse(EquipamientoBase):
    """Vista para estudiantes y docentes: sin unidades, series ni códigos (RN-I7, D-04)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    locker: int | None = Field(default=None, examples=[2])
    cantidad_total: int
    cantidad_disponible: int
    en_mantenimiento: bool

    @classmethod
    def desde_equipamiento(cls, equipamiento: Any) -> "EquipamientoPublicoResponse":
        """Arma la vista pública desde el ORM (unidades ya acotadas a la sede visible)."""
        unidades = [UnidadFisicaResponse.model_validate(u) for u in equipamiento.unidades]
        total, disponibles, en_mant = _stock(unidades)
        lockers = {u.locker for u in unidades if u.estado is not EstadoUnidadEnum.BAJA}
        base = EquipamientoBase.model_validate(equipamiento, from_attributes=True).model_dump()
        return cls(
            **base,
            id=equipamiento.id,
            locker=lockers.pop() if len(lockers) == 1 else None,
            cantidad_total=total,
            cantidad_disponible=disponibles,
            en_mantenimiento=en_mant,
        )
