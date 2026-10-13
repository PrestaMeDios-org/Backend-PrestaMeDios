"""Reglas puras para calcular intervalos de ocupación de espacios.

El horario operativo se recibe por parámetro (``apertura``/``cierre``) porque
proviene del Panel de Parámetros Globales (GLO-02, GLO-03). Los rangos son
semiabiertos ``[inicio, fin)``: dos franjas contiguas no se solapan (EC-24).
"""

from datetime import date, time
from typing import Iterable

from app.modules.spaces.models import BloqueoEspacio

Intervalo = tuple[time, time]


def solapan(a_inicio: time, a_fin: time, b_inicio: time, b_fin: time) -> bool:
    return a_inicio < b_fin and a_fin > b_inicio


def intervalos_libres(
    ocupados: Iterable[Intervalo], apertura: time, cierre: time
) -> list[Intervalo]:
    """Resta los intervalos ocupados del horario operativo ``[apertura, cierre)``."""
    recortados = sorted(
        (max(inicio, apertura), min(fin, cierre))
        for inicio, fin in ocupados
        if inicio < cierre and fin > apertura
    )
    unidos: list[Intervalo] = []
    for inicio, fin in recortados:
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fin))
        else:
            unidos.append((inicio, fin))

    libres: list[Intervalo] = []
    cursor = apertura
    for inicio, fin in unidos:
        if cursor < inicio:
            libres.append((cursor, inicio))
        cursor = max(cursor, fin)
    if cursor < cierre:
        libres.append((cursor, cierre))
    return libres


def bloqueo_intervalo_en_fecha(
    bloqueo: BloqueoEspacio, fecha: date, apertura: time, cierre: time
) -> Intervalo | None:
    """Intervalo bloqueado en ``fecha`` (día completo = todo el horario operativo)."""
    if not bloqueo.fecha_inicio <= fecha <= bloqueo.fecha_fin:
        return None
    if bloqueo.hora_inicio is None or bloqueo.hora_fin is None:
        return apertura, cierre
    return bloqueo.hora_inicio, bloqueo.hora_fin


def bloqueo_solapa(
    bloqueo: BloqueoEspacio, fecha: date, inicio: time, fin: time
) -> bool:
    """¿El bloqueo intersecta la franja ``[inicio, fin)`` de ``fecha``?

    Un bloqueo de día completo cubre el día entero, aun fuera del horario.
    """
    if not bloqueo.fecha_inicio <= fecha <= bloqueo.fecha_fin:
        return False
    if bloqueo.hora_inicio is None or bloqueo.hora_fin is None:
        return True
    return solapan(inicio, fin, bloqueo.hora_inicio, bloqueo.hora_fin)
