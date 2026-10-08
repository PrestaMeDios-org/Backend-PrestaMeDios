"""Contratos API del Panel de Parámetros Globales (GLO-03, SPEC-01 §6.12–6.14)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.core.enums import TipoParametro

ValorParametro = StrictBool | StrictInt | StrictFloat | StrictStr


class ParametroResponse(BaseModel):
    """Parámetro con su valor tipado y metadatos de versión."""

    model_config = ConfigDict(from_attributes=True)

    clave: str = Field(..., examples=["prestamo.general.max_dias"])
    tipo: TipoParametro = Field(..., examples=["ENTERO"])
    valor: bool | int | float | str = Field(..., examples=[4])
    descripcion: str = Field(..., examples=["Duración máxima de un préstamo general (PRE-07)."])
    unidad: str | None = Field(default=None, examples=["días"])
    valor_min: float | None = Field(default=None, examples=[1])
    valor_max: float | None = Field(default=None, examples=[15])
    editable: bool = Field(..., examples=[True])
    version: int = Field(..., examples=[1])
    actualizado_por_id: int | None = Field(default=None, examples=[None])
    actualizado_en: datetime = Field(..., examples=["2026-10-07T13:45:00Z"])


class ParametroUpdate(BaseModel):
    """Modificación con bloqueo optimista (UC-09). ``valor`` no se convierte de tipo (RN-19)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    valor: ValorParametro = Field(..., examples=[3])
    version: int = Field(..., ge=1, examples=[1])
    motivo: str | None = Field(
        default=None,
        max_length=300,
        examples=["Temporada alta de rodajes: se acorta el plazo general."],
    )


class ParametroHistorialItem(BaseModel):
    """Entrada del historial de un parámetro (RN-22)."""

    model_config = ConfigDict(from_attributes=True)

    version: int = Field(..., examples=[2])
    valor_anterior: bool | int | float | str = Field(..., examples=[4])
    valor_nuevo: bool | int | float | str = Field(..., examples=[3])
    motivo: str | None = Field(default=None, examples=["Temporada alta de rodajes."])
    actor_id: int | None = Field(default=None, examples=[1])
    created_at: datetime = Field(..., examples=["2026-10-07T14:00:00Z"])
