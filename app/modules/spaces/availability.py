"""Reglas compartidas para calcular intervalos de ocupación de espacios."""

from datetime import date, time
from typing import Iterable

from app.modules.spaces.models import BloqueoEspacio, ReservaEspacio

HORA_APERTURA = time(9, 0)
HORA_CIERRE = time(16, 0)


def intervalos_libres(ocupados: Iterable[tuple[time, time]]) -> list[tuple[time, time]]:
    """Resta los intervalos ocupados del horario operativo [09:00, 16:00)."""
    recortados = sorted(
        (max(inicio, HORA_APERTURA), min(fin, HORA_CIERRE))
        for inicio, fin in ocupados
        if inicio < HORA_CIERRE and fin > HORA_APERTURA
    )
    unidos: list[tuple[time, time]] = []
    for inicio, fin in recortados:
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fin))
        else:
            unidos.append((inicio, fin))

    libres: list[tuple[time, time]] = []
    cursor = HORA_APERTURA
    for inicio, fin in unidos:
        if cursor < inicio:
            libres.append((cursor, inicio))
        cursor = max(cursor, fin)
    if cursor < HORA_CIERRE:
        libres.append((cursor, HORA_CIERRE))
    return libres


def bloqueo_intervalo_en_fecha(bloqueo: BloqueoEspacio, fecha: date) -> tuple[time, time] | None:
    """Devuelve el intervalo bloqueado en una fecha incluida en el rango."""
    if not bloqueo.fecha_inicio <= fecha <= bloqueo.fecha_fin:
        return None
    if bloqueo.hora_inicio is None and bloqueo.hora_fin is None:
        return HORA_APERTURA, HORA_CIERRE
    if bloqueo.hora_inicio is None or bloqueo.hora_fin is None:
        raise ValueError(f"El bloqueo {bloqueo.id_bloqueo} tiene un rango horario incompleto.")
    return bloqueo.hora_inicio, bloqueo.hora_fin


def bloqueo_solapa_reserva(bloqueo: BloqueoEspacio, reserva: ReservaEspacio) -> bool:
    """Evalúa la intersección entre un bloqueo y una reserva en una fecha."""
    bloqueado = bloqueo_intervalo_en_fecha(bloqueo, reserva.fecha_reserva)
    return bool(
        bloqueado
        and reserva.hora_inicio < bloqueado[1]
        and reserva.hora_fin > bloqueado[0]
    )
