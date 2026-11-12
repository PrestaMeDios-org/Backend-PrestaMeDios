"""Contratos API (API-First) del módulo `notifications` (SPEC-06 §5).

- ``*Create`` / ``*Update``: entrada estricta (``extra="forbid"``, trim).
- ``*Response``: salida; el servicio los arma explícitamente.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import SedeEnum
from app.modules.notifications.enums import EstadoComunicado

_INPUT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)

_TITULO = {"min_length": 3, "max_length": 150, "examples": ["Cierre por feriado"]}
_CONTENIDO = {
    "min_length": 1,
    "max_length": 5000,
    "examples": ["El laboratorio permanecerá cerrado el lunes 20/11.\nLas devoluciones se reciben el martes."],
}
_VENCE_EN_EJEMPLO = ["2026-11-21T00:00:00-03:00"]


def _exigir_zona_horaria(valor: datetime | None) -> datetime | None:
    if valor is not None and valor.tzinfo is None:
        raise ValueError("La fecha de vencimiento debe incluir zona horaria.")
    return valor


# ── Comunicados (NOV-02) ─────────────────────────────────────────────────────


class ComunicadoCreate(BaseModel):
    """Alta de un comunicado (NOV-02, SPEC-06 RN-N2).

    ``sede`` y ``es_global`` son excluyentes. Un ``SUPERADMIN`` tiene que indicar
    uno de los dos; para un ``ADMIN_LOCAL`` la sede es siempre la suya.
    """

    model_config = _INPUT_CONFIG

    titulo: str = Field(..., **_TITULO)
    contenido: str = Field(..., **_CONTENIDO)
    sede: SedeEnum | None = Field(default=None, examples=["Ushuaia"])
    es_global: bool = Field(default=False, examples=[False])
    vence_en: datetime | None = Field(default=None, examples=_VENCE_EN_EJEMPLO)

    _zona = field_validator("vence_en")(_exigir_zona_horaria)

    @model_validator(mode="after")
    def _alcance_excluyente(self) -> "ComunicadoCreate":
        if self.es_global and self.sede is not None:
            raise ValueError("Un comunicado global no lleva sede: indicá una sede o 'es_global'.")
        return self


class ComunicadoUpdate(BaseModel):
    """Edición de un comunicado (SPEC-06 RN-N5). La sede y el alcance no se editan.

    ``vence_en: null`` quita el vencimiento; omitirlo lo deja como está.
    """

    model_config = _INPUT_CONFIG

    titulo: str | None = Field(default=None, **_TITULO)
    contenido: str | None = Field(default=None, **_CONTENIDO)
    vence_en: datetime | None = Field(default=None, examples=_VENCE_EN_EJEMPLO)

    _zona = field_validator("vence_en")(_exigir_zona_horaria)

    @model_validator(mode="after")
    def _al_menos_un_campo(self) -> "ComunicadoUpdate":
        if not self.model_fields_set:
            raise ValueError("Indicá al menos un campo para editar.")
        for campo in ("titulo", "contenido"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"'{campo}' no puede ser nulo.")
        return self


class ComunicadoEstadoUpdate(BaseModel):
    """Archivar o reactivar un comunicado (SPEC-06 RN-N4)."""

    model_config = _INPUT_CONFIG

    estado: EstadoComunicado = Field(..., examples=["ARCHIVADO"])


class AutorComunicado(BaseModel):
    """Identidad pública del autor (P6): nunca DNI, email ni teléfono."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., examples=[3])
    nombre: str = Field(..., examples=["Natalia"])
    apellido: str = Field(..., examples=["Ader"])


class ComunicadoResponse(BaseModel):
    id: int = Field(..., examples=[12])
    titulo: str = Field(..., examples=_TITULO["examples"])
    contenido: str = Field(..., examples=_CONTENIDO["examples"])
    sede: SedeEnum | None = Field(..., examples=["Ushuaia"])
    es_global: bool = Field(..., examples=[False])
    estado: EstadoComunicado = Field(..., examples=["PUBLICADO"])
    vigente: bool = Field(..., description="PUBLICADO y no vencido.", examples=[True])
    autor: AutorComunicado | None = Field(..., description="null si no se puede mostrar.")
    publicado_en: datetime = Field(..., examples=["2026-11-07T10:00:00-03:00"])
    vence_en: datetime | None = Field(..., examples=_VENCE_EN_EJEMPLO)
    actualizado_en: datetime = Field(..., examples=["2026-11-07T10:00:00-03:00"])


class ComunicadosPage(BaseModel):
    items: list[ComunicadoResponse]
    total: int = Field(..., examples=[1])
