"""Contratos API (API-First) del módulo `loans` (Pydantic v2).

- ``*Create`` / ``*EstadoUpdate``: payloads de entrada, estrictos
  (``extra="forbid"``, trim).
- ``*Response``: serializan modelos ORM vía ``from_attributes=True``.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

from app.core.enums import SedeEnum
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum

_INPUT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validar_rango(retiro: datetime, devolucion: datetime) -> None:
    """Única regla de fechas que no depende de parámetros globales."""
    if devolucion <= retiro:
        raise ValueError("La devolución debe ser posterior al retiro")


# ---------------------------------------------------------------------------
# DetallePrestamo
# ---------------------------------------------------------------------------
class DetallePrestamoCreate(BaseModel):
    """Una línea del carrito: un modelo del catálogo.

    La unidad física se asigna recién al aprobar. Repetir el mismo
    ``equipamiento_id`` es válido: cada línea pide una unidad.
    """

    model_config = _INPUT_CONFIG

    equipamiento_id: int = Field(ge=1, examples=[12])


class DetallePrestamoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    equipamiento_id: int
    unidad_fisica_id: int | None = Field(
        default=None, description="Vacía hasta que el administrador aprueba."
    )
    estado: EstadoDetalleEnum
    retiro_pactado: AwareDatetime
    devolucion_pactada: AwareDatetime
    fin_ocupacion: AwareDatetime


# ---------------------------------------------------------------------------
# OrdenPedido
# ---------------------------------------------------------------------------
class OrdenPedidoCreate(BaseModel):
    """Formulario unificado de solicitud (estudiante o docente)."""

    model_config = _INPUT_CONFIG

    asignatura_id: int | None = Field(
        default=None,
        ge=1,
        description="Obligatoria para estudiantes; el docente pide para uso de cátedra.",
    )
    retiro: AwareDatetime = Field(examples=["2026-10-12T10:00:00-03:00"])
    devolucion: AwareDatetime = Field(examples=["2026-10-15T15:00:00-03:00"])
    items: list[DetallePrestamoCreate] = Field(min_length=1, max_length=20)
    acepta_normativa: Literal[True] = Field(
        description="Debe ser true: el usuario acepta la normativa vigente."
    )

    @model_validator(mode="after")
    def _validar_fechas(self) -> "OrdenPedidoCreate":
        _validar_rango(self.retiro, self.devolucion)
        return self


class OrdenPedidoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    solicitante_id: int
    sede: SedeEnum
    asignatura_id: int | None
    estado: EstadoOrdenEnum
    fecha_solicitud: AwareDatetime
    observacion_docente: str | None = None
    motivo_resolucion: str | None = None
    es_renovado: bool = False
    detalles: list[DetallePrestamoResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def demorado(self) -> bool:
        """Derivado: hay equipos entregados cuya devolución pactada ya pasó."""
        ahora = datetime.now(UTC)
        return any(
            d.estado is EstadoDetalleEnum.ENTREGADO and d.devolucion_pactada < ahora
            for d in self.detalles
        )


# ---------------------------------------------------------------------------
# Bandeja administrativa
# ---------------------------------------------------------------------------
class AsignacionUnidad(BaseModel):
    """El administrador asigna una unidad física concreta a una línea."""

    model_config = _INPUT_CONFIG

    detalle_id: int = Field(ge=1)
    unidad_fisica_id: int = Field(ge=1)


class OrdenPedidoEstadoUpdate(BaseModel):
    """Cambio de estado de una orden: aprobar, rechazar o cancelar (PRE-10, PRE-18).

    Solo valida la forma del payload. Lo que depende del rol, de la sede o del
    estado actual (quién puede cancelar, si el motivo es obligatorio, si la
    transición es válida) lo resuelve el servicio con ``AppError``.
    """

    model_config = _INPUT_CONFIG

    estado: Literal[
        EstadoOrdenEnum.APROBADA,
        EstadoOrdenEnum.RECHAZADA,
        EstadoOrdenEnum.CANCELADA,
    ]
    motivo: str | None = Field(default=None, min_length=1, max_length=500)
    asignaciones: list[AsignacionUnidad] = Field(default_factory=list)
    nuevo_retiro: AwareDatetime | None = None
    nueva_devolucion: AwareDatetime | None = None

    @model_validator(mode="after")
    def _validar_segun_estado(self) -> "OrdenPedidoEstadoUpdate":
        if self.estado is EstadoOrdenEnum.APROBADA:
            if not self.asignaciones:
                raise ValueError("Aprobar requiere asignar una unidad por línea")
            ids = [a.detalle_id for a in self.asignaciones]
            if len(ids) != len(set(ids)):
                raise ValueError("Hay líneas con más de una asignación")
            if (self.nuevo_retiro is None) != (self.nueva_devolucion is None):
                raise ValueError("Para ajustar horarios enviá retiro y devolución juntos")
            if self.nuevo_retiro and self.nueva_devolucion:
                _validar_rango(self.nuevo_retiro, self.nueva_devolucion)
        else:
            if self.asignaciones:
                raise ValueError("Solo la aprobación admite asignaciones")
            if self.nuevo_retiro or self.nueva_devolucion:
                raise ValueError("Solo la aprobación admite ajuste horario")
        return self