"""Plantillas de las notificaciones personales (NOV-04, SPEC-06 §6.2, RN-N7…RN-N9).

Cada tipo declara su severidad, las claves que admite en ``datos`` y el texto. El
llamador nunca escribe texto libre: así el contenido es homogéneo y no puede filtrar
datos personales (P6, RN-N8). Agregar un tipo es sumar un valor a ``TipoNotificacion``,
su fila acá y su test; no hace falta migración (D-N05).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from string import Template

from app.modules.notifications.enums import Severidad, TipoNotificacion

MENSAJE_MAX = 1000  # largo de `notificaciones.mensaje`
CLAVES_PROHIBIDAS = frozenset({"dni", "email", "telefono", "password"})  # RN-N8


@dataclass(frozen=True)
class Plantilla:
    severidad: Severidad
    claves: frozenset[str]
    titulo: str
    mensaje: Template


def _p(severidad: Severidad, claves: str, titulo: str, mensaje: str) -> Plantilla:
    return Plantilla(severidad, frozenset(claves.split()), titulo, Template(mensaje))


N, CRITICA = Severidad.NORMAL, Severidad.CRITICA
T = TipoNotificacion

PLANTILLAS: dict[TipoNotificacion, Plantilla] = {
    # `loans` (SPEC-05 §10.3)
    T.ORDEN_APROBADA: _p(
        N, "numero_orden retiro", "Solicitud aprobada",
        "Tu solicitud N° $numero_orden fue aprobada. Retiro: $retiro.",
    ),
    T.ORDEN_RECHAZADA: _p(
        N, "numero_orden motivo", "Solicitud rechazada",
        "Tu solicitud N° $numero_orden fue rechazada. Motivo: $motivo.",
    ),
    T.ORDEN_CANCELADA: _p(
        N, "numero_orden motivo", "Solicitud cancelada",
        "Tu solicitud N° $numero_orden fue cancelada. Motivo: $motivo.",
    ),
    T.ORDEN_HORARIO_AJUSTADO: _p(
        CRITICA, "numero_orden retiro devolucion", "Aprobada con horario modificado",
        "Tu solicitud N° $numero_orden fue aprobada con otro horario. "
        "Retiro: $retiro. Devolución: $devolucion.",
    ),
    T.ORDEN_CANCELACION_FORZADA: _p(
        CRITICA, "numero_orden motivo", "Cancelación por fuerza mayor",
        "El laboratorio canceló tu solicitud N° $numero_orden. Motivo: $motivo.",
    ),
    T.ORDEN_NO_RETIRADA: _p(
        N, "numero_orden", "Reserva cancelada por no retiro",
        "Tu solicitud N° $numero_orden se canceló porque el equipo no se retiró a tiempo.",
    ),
    T.PRESTAMO_DEMORADO: _p(
        N, "numero_orden devolucion", "Préstamo demorado",
        "El préstamo de la solicitud N° $numero_orden debía devolverse el $devolucion. "
        "Acercate al laboratorio para devolverlo.",
    ),
    # `spaces` (RES-04, RES-05; a confirmar con el Perfil 4, C-N02)
    T.RESERVA_APROBADA: _p(
        N, "espacio fecha horario", "Reserva aprobada",
        "Tu reserva de $espacio para el $fecha ($horario) fue aprobada.",
    ),
    T.RESERVA_RECHAZADA: _p(
        N, "espacio fecha horario motivo", "Reserva rechazada",
        "Tu reserva de $espacio para el $fecha ($horario) fue rechazada. Motivo: $motivo.",
    ),
    T.RESERVA_CANCELACION_FORZADA: _p(
        CRITICA, "espacio fecha horario motivo", "Reserva cancelada por el laboratorio",
        "El laboratorio canceló tu reserva de $espacio para el $fecha ($horario). "
        "Motivo: $motivo.",
    ),
}


def renderizar(tipo: TipoNotificacion, datos: Mapping[str, str]) -> tuple[Severidad, str, str]:
    """Severidad, título y mensaje de ``tipo`` con ``datos`` (RN-N7).

    Lanza ``ValueError`` si falta o sobra una clave, o si un valor no es texto: es un
    error de programación del llamador y se detecta antes de guardar nada.
    """
    plantilla = PLANTILLAS[tipo]
    faltan = plantilla.claves - datos.keys()
    sobran = datos.keys() - plantilla.claves
    if faltan or sobran:
        raise ValueError(
            f"Datos inválidos para {tipo.value}: se esperan {sorted(plantilla.claves)}"
            f"{f'; faltan {sorted(faltan)}' if faltan else ''}"
            f"{f'; sobran {sorted(sobran)}' if sobran else ''}."
        )
    no_texto = sorted(k for k, v in datos.items() if not isinstance(v, str))
    if no_texto:
        raise ValueError(f"Datos inválidos para {tipo.value}: {no_texto} deben ser texto.")
    mensaje = plantilla.mensaje.substitute(datos)
    if len(mensaje) > MENSAJE_MAX:
        mensaje = mensaje[: MENSAJE_MAX - 1] + "…"
    return plantilla.severidad, plantilla.titulo, mensaje
