"""Parámetros semilla del reglamento vigente (SPEC-01 §11.2).

Fuente única usada por la migración ``0005`` y por los tests, para que no
diverjan. Las migraciones copian estos valores al momento de crearse; si en
el futuro se agrega una clave, se hace con una migración nueva.
"""

from typing import Any, TypedDict


class ParametroSemilla(TypedDict):
    clave: str
    tipo: str
    valor: Any
    descripcion: str
    unidad: str | None
    valor_min: int | None
    valor_max: int | None


PARAMETROS_SEMILLA: list[ParametroSemilla] = [
    {
        "clave": "prestamo.general.max_dias",
        "tipo": "ENTERO",
        "valor": 4,
        "descripcion": "Duración máxima de un préstamo general de equipamiento (PRE-07).",
        "unidad": "días",
        "valor_min": 1,
        "valor_max": 15,
    },
    {
        "clave": "prestamo.notebook.max_dias",
        "tipo": "ENTERO",
        "valor": 15,
        "descripcion": "Duración máxima de un préstamo de notebook.",
        "unidad": "días",
        "valor_min": 1,
        "valor_max": 30,
    },
    {
        "clave": "solicitud.anticipacion_min_horas",
        "tipo": "ENTERO",
        "valor": 24,
        "descripcion": (
            "Anticipación mínima entre el envío de una solicitud (préstamo o reserva) "
            "y el inicio del retiro o turno (D-07)."
        ),
        "unidad": "horas",
        "valor_min": 0,
        "valor_max": 168,
    },
    {
        "clave": "prestamo.tolerancia_retiro_horas",
        "tipo": "ENTERO",
        "valor": 2,
        "descripcion": "Margen para retirar un equipo antes de la cancelación automática (PRE-08).",
        "unidad": "horas",
        "valor_min": 0,
        "valor_max": 24,
    },
    {
        "clave": "notificacion.aviso_vencimiento_horas",
        "tipo": "ENTERO",
        "valor": 24,
        "descripcion": "Antelación del aviso de vencimiento de un préstamo (NOV-03).",
        "unidad": "horas",
        "valor_min": 1,
        "valor_max": 168,
    },
    {
        "clave": "horario.apertura",
        "tipo": "HORA",
        "valor": "09:00",
        "descripcion": "Hora de apertura operativa del laboratorio (GLO-02).",
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "horario.cierre",
        "tipo": "HORA",
        "valor": "16:00",
        "descripcion": "Hora de cierre operativo del laboratorio (GLO-02).",
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "reserva_espacio.anticipacion_max_dias",
        "tipo": "ENTERO",
        "valor": 120,
        "descripcion": "Cuántos días a futuro se pueden solicitar reservas de espacios.",
        "unidad": "días",
        "valor_min": 1,
        "valor_max": 365,
    },
]
