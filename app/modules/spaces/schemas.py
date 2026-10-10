"""Contratos API (API-First) del dominio `spaces` (Subsistema 3: Reserva de Espacios).

SPEC-02 §3.2:
- La sede es ``SedeEnum`` (no un entero) y el solicitante de una reserva es
  siempre el usuario autenticado: ``id_usuario`` no forma parte del alta.
- El horario operativo no está fijo aquí: lo valida el servicio con los
  parámetros globales (GLO-02, GLO-03).
- La disponibilidad no expone la identidad de otros solicitantes (P6).
"""

from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import SedeEnum

_INPUT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EstadoReserva(str, Enum):
    """Ciclo de vida de una reserva de espacio."""

    PENDIENTE = "Pendiente"
    APROBADA = "Aprobada"
    RECHAZADA = "Rechazada"
    CANCELADA = "Cancelada"
    EN_USO = "En_Uso"
    FINALIZADA = "Finalizada"


ESTADOS_ACTIVOS = (EstadoReserva.APROBADA.value, EstadoReserva.EN_USO.value)


def _sin_zona(*horas: time | None) -> None:
    if any(h is not None and h.tzinfo is not None for h in horas):
        raise ValueError("Las horas deben expresarse como hora local sin zona horaria.")


# ── Espacio ──────────────────────────────────────────────────────────────────


class EspacioCreate(BaseModel):
    """Alta de un espacio. ``sede`` es automática para ``ADMIN_LOCAL`` (PRE-19, RN-31)."""

    model_config = _INPUT_CONFIG

    nombre: str = Field(..., min_length=1, max_length=100, examples=["Aula-Estudio 1"])
    tipo: Optional[str] = Field(default=None, max_length=100, examples=["Isla de Edición"])
    sede: Optional[SedeEnum] = Field(default=None, examples=["Ushuaia"])


class EspacioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_espacio: int = Field(..., examples=[3])
    nombre: str = Field(..., examples=["Aula-Estudio 1"])
    tipo: Optional[str] = Field(default=None, examples=["Isla de Edición"])
    sede: SedeEnum = Field(..., examples=["Ushuaia"])


# ── Reserva ──────────────────────────────────────────────────────────────────


class ReservaEspacioCreate(BaseModel):
    """Solicitud de reserva (RES-02). El solicitante es el usuario autenticado (RN-25)."""

    model_config = _INPUT_CONFIG

    id_espacio: int = Field(..., examples=[3])
    fecha_reserva: date = Field(..., examples=["2026-10-12"])
    hora_inicio: time = Field(..., examples=["10:00:00"])
    hora_fin: time = Field(..., examples=["11:30:00"])
    motivo: Optional[str] = Field(default=None, max_length=500, examples=["Clase de práctica"])

    @model_validator(mode="after")
    def _rango(self) -> "ReservaEspacioCreate":
        _sin_zona(self.hora_inicio, self.hora_fin)
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("`hora_fin` debe ser posterior a `hora_inicio`.")
        return self


class ReservaEspacioResponse(BaseModel):
    """Reserva visible para su dueño o para un administrador con jurisdicción."""

    model_config = ConfigDict(from_attributes=True)

    id_reserva: int = Field(..., examples=[42])
    id_usuario: int = Field(..., examples=[7])
    id_espacio: int = Field(..., examples=[3])
    fecha_reserva: date = Field(..., examples=["2026-10-12"])
    hora_inicio: time = Field(..., examples=["10:00:00"])
    hora_fin: time = Field(..., examples=["11:30:00"])
    estado_reserva: EstadoReserva = Field(..., examples=["Pendiente"])
    motivo: Optional[str] = Field(default=None, examples=["Clase de práctica"])
    created_at: datetime = Field(..., examples=["2026-10-05T14:30:00Z"])


class ReservaEspacioUpdateStatus(BaseModel):
    """Transición de estado (RES-03, RES-05; SPEC-02 §3.4)."""

    model_config = _INPUT_CONFIG

    nuevo_estado: EstadoReserva = Field(..., examples=["Aprobada"])
    motivo_rechazo: Optional[str] = Field(
        default=None, max_length=500, examples=["Espacio en mantenimiento"]
    )

    @model_validator(mode="after")
    def _motivo(self) -> "ReservaEspacioUpdateStatus":
        if self.nuevo_estado == EstadoReserva.RECHAZADA and not self.motivo_rechazo:
            raise ValueError("`motivo_rechazo` es obligatorio cuando `nuevo_estado` es 'Rechazada'.")
        return self


# ── Bloqueo administrativo (RES-04 / GLO-04) ─────────────────────────────────


class BloqueoEspacioCreate(BaseModel):
    """Bloqueo de días completos (sin horas) o de una franja diaria."""

    model_config = _INPUT_CONFIG

    id_espacio: int = Field(..., examples=[3])
    fecha_inicio: date = Field(..., examples=["2026-10-12"])
    fecha_fin: date = Field(..., examples=["2026-10-14"])
    hora_inicio: Optional[time] = Field(default=None, examples=["09:00:00"])
    hora_fin: Optional[time] = Field(default=None, examples=["16:00:00"])
    motivo: str = Field(..., min_length=1, max_length=500, examples=["Mantenimiento eléctrico"])

    @model_validator(mode="after")
    def _rango(self) -> "BloqueoEspacioCreate":
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("`fecha_fin` no puede ser anterior a `fecha_inicio`.")
        if (self.hora_inicio is None) != (self.hora_fin is None):
            raise ValueError("`hora_inicio` y `hora_fin` deben informarse juntas para un bloqueo parcial.")
        _sin_zona(self.hora_inicio, self.hora_fin)
        if self.hora_inicio is not None and self.hora_fin is not None:
            if self.hora_fin <= self.hora_inicio:
                raise ValueError("`hora_fin` debe ser posterior a `hora_inicio`.")
        return self


class BloqueoEspacioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_bloqueo: int = Field(..., examples=[15])
    id_espacio: int = Field(..., examples=[3])
    fecha_inicio: date = Field(..., examples=["2026-10-12"])
    fecha_fin: date = Field(..., examples=["2026-10-14"])
    hora_inicio: Optional[time] = Field(default=None, examples=[None])
    hora_fin: Optional[time] = Field(default=None, examples=[None])
    motivo: str = Field(..., examples=["Feriado"])
    created_at: datetime = Field(..., examples=["2026-10-05T14:30:00Z"])


# ── Disponibilidad (RES-01) ──────────────────────────────────────────────────


class FranjaOcupada(BaseModel):
    """Franja tomada por una reserva activa, sin identidad del solicitante (RN-30)."""

    id_espacio: int = Field(..., examples=[3])
    hora_inicio: time = Field(..., examples=["10:00:00"])
    hora_fin: time = Field(..., examples=["11:30:00"])
    estado_reserva: EstadoReserva = Field(..., examples=["Aprobada"])


class IntervaloLibre(BaseModel):
    hora_inicio: time = Field(..., examples=["09:00:00"])
    hora_fin: time = Field(..., examples=["10:00:00"])


class IntervalosEspacio(BaseModel):
    id_espacio: int = Field(..., examples=[3])
    intervalos_libres: list[IntervaloLibre]


class DisponibilidadResponse(BaseModel):
    fecha: date = Field(..., examples=["2026-10-12"])
    sede: Optional[SedeEnum] = Field(default=None, examples=["Ushuaia"])
    id_espacio: Optional[int] = Field(default=None, examples=[3])
    horario_apertura: time = Field(..., examples=["09:00:00"])
    horario_cierre: time = Field(..., examples=["16:00:00"])
    franjas_ocupadas: list[FranjaOcupada]
    bloqueos: list[BloqueoEspacioResponse]
    intervalos_disponibles: list[IntervalosEspacio]
