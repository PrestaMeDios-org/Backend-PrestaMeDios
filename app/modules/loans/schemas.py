"""Contratos API (API-First) del módulo `loans` (Pydantic v2).

- ``*Create`` / ``*EstadoUpdate``: payloads de entrada, estrictos
  (``extra="forbid"``, trim).
- ``*Response``: serializan modelos ORM vía ``from_attributes=True``.

Qué NO se valida acá (depende de otro dominio, de la sesión o de los
parámetros globales editables del módulo `config`):
  - franja operativa (``horario.apertura`` / ``horario.cierre``)
  - límite de días (``prestamo.general.max_dias``, ``prestamo.notebook.max_dias``
    y/o ``Equipamiento.max_dias_prestamo``)
  - anticipación mínima (``solicitud.anticipacion_min_horas``)
  - asignatura obligatoria para estudiantes (el rol sale de la sesión)
  - motivo obligatorio al rechazar o cancelar (``MOTIVO_REQUERIDO``)
  - PDF obligatorio si hay ítems de alta gama (``pdf_aval_id``)
  - que ``renueva_detalle_id`` sea una línea ``entregado`` propia de una notebook
  - solapamientos de reservas (los resuelve la base de datos)
El solicitante y la sede salen siempre de la sesión, nunca del body.
Los errores de negocio usan ``AppError`` (``{detail, code}``), no esquemas propios.
"""

from datetime import UTC, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

from app.core.enums import SedeEnum
from app.modules.loans.enums import (
    ESTADOS_DETALLE_EN_CURSO,
    EstadoDetalleEnum,
    EstadoOrdenEnum,
    SituacionOrdenEnum,
)

_INPUT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validar_rango(retiro: datetime, devolucion: datetime) -> None:
    """Única regla de fechas que no depende de parámetros globales."""
    if devolucion <= retiro:
        raise ValueError("La devolución debe ser posterior al retiro")


# ---------------------------------------------------------------------------
# Reglas operativas
# ---------------------------------------------------------------------------
class ReglasResponse(BaseModel):
    """Reglas operativas vigentes, leídas de `config` (SPEC-05 §6.2, D-L07)."""

    horario_apertura: time = Field(examples=["09:00:00"])
    horario_cierre: time = Field(examples=["16:00:00"])
    anticipacion_min_horas: int = Field(examples=[24])
    max_dias_general: int = Field(examples=[4])
    max_dias_notebook: int = Field(examples=[15])
    tolerancia_retiro_horas: int = Field(examples=[2])


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
    pdf_aval_id: UUID | None = Field(
        default=None,
        description=(
            "Id del PDF de aval subido con `POST /api/v1/files/archivos` "
            "(`proposito=AVAL_PRESTAMO`). Obligatorio si algún ítem es de alta gama (PRE-05)."
        ),
        examples=["3f2b6c1e-8a4d-4f7e-9b1a-2c5d7e9f0a1b"],
    )
    renueva_detalle_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Renovación (PRE-11): línea `entregado` propia, de una notebook, que se renueva. "
            "La orden debe tener una sola línea, del mismo modelo."
        ),
        examples=[42],
    )

    @model_validator(mode="after")
    def _validar_fechas(self) -> "OrdenPedidoCreate":
        _validar_rango(self.retiro, self.devolucion)
        if self.renueva_detalle_id is not None and len(self.items) != 1:
            raise ValueError("Una renovación lleva una sola línea")
        return self


class SolicitanteResumen(BaseModel):
    """Identidad mínima del solicitante (P6): nunca DNI, email ni teléfono."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(examples=[7])
    nombre: str = Field(examples=["Ana"])
    apellido: str = Field(examples=["Pérez"])


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
    resuelto_en: AwareDatetime | None = Field(
        default=None, description="Cuándo se aprobó, rechazó o canceló. Vacío si sigue pendiente."
    )
    solicitante: SolicitanteResumen | None = Field(
        default=None,
        description=(
            "Nombre y apellido del solicitante. Solo se completa para administradores; "
            "el dueño de la orden recibe null."
        ),
    )
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def situacion(self) -> SituacionOrdenEnum:
        """Derivada (RN-L31): en curso si alguna línea está pendiente, reservada o entregada."""
        if any(d.estado in ESTADOS_DETALLE_EN_CURSO for d in self.detalles):
            return SituacionOrdenEnum.EN_CURSO
        return SituacionOrdenEnum.FINALIZADA


# ---------------------------------------------------------------------------
# Bandeja administrativa
# ---------------------------------------------------------------------------
class LineaUnidadesLibresResponse(BaseModel):
    """Unidades que se pueden asignar a una línea al aprobar (RN-L10, RN-L12, AC-L58).

    Solo ids: para mostrar el código de inventario, la interfaz los cruza con el stock
    de `inventory` (plan §8.7, Q1).
    """

    detalle_id: int = Field(examples=[31])
    equipamiento_id: int = Field(examples=[12])
    unidades: list[int] = Field(
        description="Ids de las unidades libres para el período de la línea.",
        examples=[[101, 104]],
    )


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
