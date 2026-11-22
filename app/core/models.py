"""Modelos transversales de ``core``.

Sólo lo que no pertenece a ningún dominio: hoy, el contador del límite diario de
correos (SPEC-11 §6.7, plan §5.4).
"""

from datetime import date

from sqlalchemy import CheckConstraint, Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EnvioCorreoDiario(Base):
    """Correos enviados (o intentados) por día, para respetar ``EMAIL_LIMITE_DIARIO``.

    Una fila por fecha del laboratorio. La API y el contenedor de tareas comparten el
    contador por la base, porque son procesos distintos.
    """

    __tablename__ = "envios_correo_diarios"
    __table_args__ = (CheckConstraint("cantidad >= 0", name="cantidad_no_negativa"),)

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
