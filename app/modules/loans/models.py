"""Modelos ORM del módulo `loans` (SQLAlchemy 2.0).

Tablas: ``ordenes_pedido`` (solicitud unificada) y ``detalles_prestamo``
(una línea por unidad pedida).

"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    String,
    false,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SedeEnum, enum_values
from app.database import Base
from app.modules.loans.enums import EstadoDetalleEnum, EstadoOrdenEnum

# `sede_enum` es compartido con `inventory` y `users`: el tipo ya lo crea otra
# migración, por eso no se emite CREATE TYPE desde acá.
SEDE_ENUM_COMPARTIDO = PGEnum(
    SedeEnum, values_callable=enum_values, name="sede_enum", create_type=False
)


class OrdenPedido(Base):
    """Solicitud unificada de un estudiante o docente."""

    __tablename__ = "ordenes_pedido"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # No hay borrado físico de usuarios (baja lógica), así que RESTRICT alcanza.
    solicitante_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="RESTRICT"),
        index=True,
    )
    # Sede de la solicitud: sale de la sesión del solicitante, nunca del body.
    sede: Mapped[SedeEnum] = mapped_column(SEDE_ENUM_COMPARTIDO, index=True)
    # Sin FK por ahora: todavía no existe el módulo de asignaturas.
    asignatura_id: Mapped[int | None]
    estado: Mapped[EstadoOrdenEnum] = mapped_column(
        SAEnum(EstadoOrdenEnum, values_callable=enum_values, name="estado_orden_enum"),
        default=EstadoOrdenEnum.PENDIENTE,
        server_default=text("'pendiente'"),
        index=True,
    )
    fecha_solicitud: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    observacion_docente: Mapped[str | None] = mapped_column(String(500))
    motivo_resolucion: Mapped[str | None] = mapped_column(String(500))
    es_renovado: Mapped[bool] = mapped_column(default=False, server_default=false())

    detalles: Mapped[list["DetallePrestamo"]] = relationship(
        back_populates="orden",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="DetallePrestamo.id",
    )


class DetallePrestamo(Base):
    """Una línea de la orden: un modelo pedido y, al aprobar, su unidad física."""

    __tablename__ = "detalles_prestamo"
    __table_args__ = (
        CheckConstraint("devolucion_pactada > retiro_pactado", name="rango_pactado"),
        CheckConstraint("fin_ocupacion >= devolucion_pactada", name="fin_ocupacion_valido"),
        # Una línea que ocupa la unidad debe tener unidad asignada.
        CheckConstraint(
            "estado NOT IN ('reservado', 'entregado') OR unidad_fisica_id IS NOT NULL",
            name="unidad_si_ocupa",
        ),
        # Misma unidad + períodos que se pisan = rechazo (SQLSTATE 23P01).
        # Solo compara las líneas que ocupan; el resto libera la unidad.
        # Nombre completo a mano: NAMING_CONVENTION no tiene clave "ex".
        ExcludeConstraint(
            ("unidad_fisica_id", "="),
            ("periodo", "&&"),
            where=text("estado IN ('reservado', 'entregado')"),
            using="gist",
            name="ex_detalles_prestamo_sin_solapamiento",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    orden_id: Mapped[int] = mapped_column(
        ForeignKey("ordenes_pedido.id", ondelete="CASCADE"),
        index=True,
    )
    equipamiento_id: Mapped[int] = mapped_column(
        ForeignKey("equipamientos.id", ondelete="RESTRICT"),
        index=True,
    )
    # Vacía mientras la orden está pendiente; el administrador la asigna al aprobar.
    unidad_fisica_id: Mapped[int | None] = mapped_column(
        ForeignKey("unidades_fisicas.id", ondelete="RESTRICT"),
        index=True,
    )
    estado: Mapped[EstadoDetalleEnum] = mapped_column(
        SAEnum(EstadoDetalleEnum, values_callable=enum_values, name="estado_detalle_enum"),
        default=EstadoDetalleEnum.PENDIENTE,
        server_default=text("'pendiente'"),
        index=True,
    )
    retiro_pactado: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    devolucion_pactada: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Arranca igual a devolucion_pactada; un proceso de demoras la extiende
    # sin perder la fecha pactada (necesaria para calcular "demorado").
    fin_ocupacion: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Columna generada por la base: el ORM nunca la escribe.
    periodo: Mapped[Range[datetime]] = mapped_column(
        TSTZRANGE,
        Computed("tstzrange(retiro_pactado, fin_ocupacion, '[)')", persisted=True),
    )

    orden: Mapped["OrdenPedido"] = relationship(
        back_populates="detalles", lazy="raise_on_sql"
    )