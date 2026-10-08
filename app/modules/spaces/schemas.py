"""Contratos API (API-First) del dominio `spaces` (Subsistema 3: Reserva de Espacios).

Estos esquemas Pydantic v2 definen el contrato OpenAPI del dominio de
Reservas de Espacios *antes* de cualquier implementación de persistencia.
Los esquemas ``Response`` usan ``from_attributes=True`` para serializar
directamente los modelos ORM de SQLAlchemy.
"""

from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums de dominio
# ---------------------------------------------------------------------------
class EstadoReserva(str, Enum):
    """Ciclo de vida de una reserva de espacio."""

    PENDIENTE = "Pendiente"
    APROBADA = "Aprobada"
    RECHAZADA = "Rechazada"
    CANCELADA = "Cancelada"
    EN_USO = "En_Uso"
    FINALIZADA = "Finalizada"


# ---------------------------------------------------------------------------
# Espacio
# ---------------------------------------------------------------------------
class EspacioBase(BaseModel):
    """Campos compartidos del contrato de un espacio reservable."""

    nombre: str = Field(..., max_length=100, examples=["Aula-Estudio 1"])
    id_sede: int = Field(..., examples=[1])
    tipo: Optional[str] = Field(default=None, max_length=100, examples=["Isla de Edición"])


class EspacioCreate(EspacioBase):
    """Payload para dar de alta un espacio."""


class EspacioResponse(EspacioBase):
    """Representación pública de un espacio persistido."""

    model_config = ConfigDict(from_attributes=True)

    id_espacio: int = Field(..., examples=[3])


# ---------------------------------------------------------------------------
# Reserva de Espacio
# ---------------------------------------------------------------------------
class ReservaEspacioBase(BaseModel):
    """Campos compartidos del contrato de una reserva de espacio."""

    id_usuario: int = Field(..., examples=[7])
    id_espacio: int = Field(..., examples=[3])
    fecha_reserva: date = Field(..., examples=["2026-10-12"])
    hora_inicio: time = Field(..., examples=["10:00:00"])
    hora_fin: time = Field(..., examples=["11:30:00"])
    estado_reserva: EstadoReserva = EstadoReserva.PENDIENTE
    motivo: Optional[str] = Field(default=None, max_length=500, examples=["Clase de práctica"])

    @field_validator("hora_inicio", "hora_fin")
    @classmethod
    def hora_dentro_de_franja(cls, v: time) -> time:
        """GLO-02: la franja horaria debe estar entre las 09:00 y las 16:00."""
        if v.tzinfo is not None:
            raise ValueError("Las horas deben expresarse como hora local sin zona horaria.")
        if v < time(9, 0) or v > time(16, 0):
            raise ValueError("La hora debe estar contenida entre las 09:00 y las 16:00 hs (GLO-02).")
        return v

    @model_validator(mode="after")
    def hora_fin_posterior(self) -> "ReservaEspacioBase":
        """`hora_fin` debe ser posterior a `hora_inicio`."""
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("`hora_fin` debe ser posterior a `hora_inicio`.")
        return self


class ReservaEspacioCreate(ReservaEspacioBase):
    """Payload para crear una reserva de espacio."""


class ReservaEspacioResponse(ReservaEspacioBase):
    """Representación pública de una reserva de espacio persistida."""

    model_config = ConfigDict(from_attributes=True)

    id_reserva: int = Field(..., examples=[42])
    created_at: datetime = Field(..., examples=["2026-10-05T14:30:00Z"])


# ---------------------------------------------------------------------------
# Actualización de estado (RES-05)
# ---------------------------------------------------------------------------
class ReservaEspacioUpdateStatus(BaseModel):
    """Payload para la aprobación/rechazo/cancelación administrativa."""

    nuevo_estado: EstadoReserva = Field(..., examples=["Aprobada"])
    motivo_rechazo: Optional[str] = Field(default=None, max_length=500, examples=["Espacio en mantenimiento"])

    @model_validator(mode="after")
    def motivo_requerido_si_rechazada(self) -> "ReservaEspacioUpdateStatus":
        if self.nuevo_estado == "Rechazada" and not self.motivo_rechazo:
            raise ValueError("`motivo_rechazo` es obligatorio cuando `nuevo_estado` es 'Rechazada'.")
        return self


# ---------------------------------------------------------------------------
# Bloqueo administrativo (RES-04 / GLO-04)
# ---------------------------------------------------------------------------
class BloqueoEspacioCreate(BaseModel):
    """Payload para bloquear un espacio por contingencia o mantenimiento."""

    id_espacio: int = Field(..., examples=[3])
    fecha_inicio: date = Field(..., examples=["2026-10-12"])
    fecha_fin: date = Field(..., examples=["2026-10-14"])
    hora_inicio: Optional[time] = Field(default=None, examples=["09:00:00"])
    hora_fin: Optional[time] = Field(default=None, examples=["16:00:00"])
    motivo: str = Field(..., max_length=500, examples=["Mantenimiento eléctrico"])

    @model_validator(mode="after")
    def rango_valido(self) -> "BloqueoEspacioCreate":
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("`fecha_fin` no puede ser anterior a `fecha_inicio`.")
        if (self.hora_inicio is None) != (self.hora_fin is None):
            raise ValueError("`hora_inicio` y `hora_fin` deben informarse juntas para un bloqueo parcial.")
        if self.hora_inicio is not None and self.hora_fin is not None:
            if self.hora_inicio.tzinfo is not None or self.hora_fin.tzinfo is not None:
                raise ValueError("Las horas deben expresarse como hora local sin zona horaria.")
            if self.hora_inicio < time(9, 0) or self.hora_fin > time(16, 0):
                raise ValueError("El bloqueo debe estar contenido entre las 09:00 y las 16:00 hs (GLO-02).")
            if self.hora_fin <= self.hora_inicio:
                raise ValueError("`hora_fin` debe ser posterior a `hora_inicio`.")
        return self


class BloqueoEspacioResponse(BloqueoEspacioCreate):
    """Representación pública de un bloqueo administrativo persistido."""

    model_config = ConfigDict(from_attributes=True)

    id_bloqueo: int = Field(..., examples=[15])
    created_at: datetime = Field(..., examples=["2026-10-05T14:30:00Z"])


# ---------------------------------------------------------------------------
# Filtro de disponibilidad (RES-01)
# ---------------------------------------------------------------------------
class DisponibilidadEspacioFilter(BaseModel):
    """Filtros para consultar turnos libres de espacios."""

    id_sede: int = Field(..., examples=[1])
    id_espacio: Optional[int] = Field(default=None, examples=[3])
    fecha: date = Field(..., examples=["2026-10-12"])
