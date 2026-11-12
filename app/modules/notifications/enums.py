"""Enums del módulo `notifications` (SPEC-06 §6.2, §7).

Valores en mayúsculas, como en `core` (DT-09, DT-19).
"""

from enum import StrEnum


class EstadoComunicado(StrEnum):
    """Ciclo de vida de un comunicado (NOV-02, SPEC-06 RN-N4)."""

    PUBLICADO = "PUBLICADO"
    ARCHIVADO = "ARCHIVADO"


class Severidad(StrEnum):
    """Severidad de una notificación personal (NOV-04, SPEC-06 RN-N9)."""

    NORMAL = "NORMAL"
    CRITICA = "CRITICA"


class TipoNotificacion(StrEnum):
    """Tipos de notificación de la Fase B (SPEC-06 §6.2).

    Se persisten como ``varchar(50)`` (D-N05): agregar un tipo es agregar un
    valor acá y su plantilla, sin migración.
    """

    # `loans` (SPEC-05 §10.3)
    ORDEN_APROBADA = "ORDEN_APROBADA"
    ORDEN_RECHAZADA = "ORDEN_RECHAZADA"
    ORDEN_CANCELADA = "ORDEN_CANCELADA"
    ORDEN_HORARIO_AJUSTADO = "ORDEN_HORARIO_AJUSTADO"
    ORDEN_CANCELACION_FORZADA = "ORDEN_CANCELACION_FORZADA"
    ORDEN_NO_RETIRADA = "ORDEN_NO_RETIRADA"
    PRESTAMO_DEMORADO = "PRESTAMO_DEMORADO"
    # `spaces` (RES-04, RES-05; a confirmar con el Perfil 4, C-N02)
    RESERVA_APROBADA = "RESERVA_APROBADA"
    RESERVA_RECHAZADA = "RESERVA_RECHAZADA"
    RESERVA_CANCELACION_FORZADA = "RESERVA_CANCELACION_FORZADA"
