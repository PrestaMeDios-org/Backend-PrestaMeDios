"""Parámetros semilla del reglamento vigente (SPEC-01 §11.2, SPEC-09 §4.2).

Refleja el estado de ``parametros_globales`` después de la última migración que
toca parámetros (hoy ``0017_config_sedes``): con esta lista se siembra la base de
tests. Las migraciones guardan una copia congelada al crearse y
``tests/config/test_semilla.py`` verifica que ``0005`` más ``0017`` den esta lista.
Una clave nueva se agrega con una migración nueva.
"""

from typing import Any, NotRequired, TypedDict


class ParametroSemilla(TypedDict):
    clave: str
    tipo: str
    valor: Any
    descripcion: str
    unidad: str | None
    valor_min: int | None
    valor_max: int | None
    editable: NotRequired[bool]  # si falta, ``true``


PREFIJO_OBSOLETA = "Obsoleta (SPEC-09): usar el horario de cada sede. "
_NOTA_TRANSICION = (
    " Hasta que reservas y préstamos lean el horario de cada sede, rige el global (SPEC-09 EC-51)."
)


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
        "descripcion": PREFIJO_OBSOLETA + "Hora de apertura operativa del laboratorio (GLO-02).",
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
        "editable": False,  # RN-81 de SPEC-09
    },
    {
        "clave": "horario.cierre",
        "tipo": "HORA",
        "valor": "16:00",
        "descripcion": PREFIJO_OBSOLETA + "Hora de cierre operativo del laboratorio (GLO-02).",
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
        "editable": False,  # RN-81 de SPEC-09
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
    # ── SPEC-09 · horario y correo de contacto por sede (GLO-03, ADR-022 a y c) ──
    {
        "clave": "horario.ushuaia.apertura",
        "tipo": "HORA",
        "valor": "09:00",
        "descripcion": "Hora de apertura del laboratorio de Ushuaia (GLO-02, GLO-03)." + _NOTA_TRANSICION,
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "horario.ushuaia.cierre",
        "tipo": "HORA",
        "valor": "16:00",
        "descripcion": "Hora de cierre del laboratorio de Ushuaia (GLO-02, GLO-03)." + _NOTA_TRANSICION,
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "horario.rio_grande.apertura",
        "tipo": "HORA",
        "valor": "09:00",
        "descripcion": "Hora de apertura del laboratorio de Río Grande (GLO-02, GLO-03)." + _NOTA_TRANSICION,
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "horario.rio_grande.cierre",
        "tipo": "HORA",
        "valor": "16:00",
        "descripcion": "Hora de cierre del laboratorio de Río Grande (GLO-02, GLO-03)." + _NOTA_TRANSICION,
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "contacto.ushuaia.email",
        "tipo": "TEXTO",
        "valor": "",
        "descripcion": (
            "Correo de contacto del laboratorio de Ushuaia, para el aviso de anticipación mínima "
            "(ADR-022 c). Vacío: sin configurar."
        ),
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
    {
        "clave": "contacto.rio_grande.email",
        "tipo": "TEXTO",
        "valor": "",
        "descripcion": (
            "Correo de contacto del laboratorio de Río Grande, para el aviso de anticipación mínima "
            "(ADR-022 c). Vacío: sin configurar."
        ),
        "unidad": None,
        "valor_min": None,
        "valor_max": None,
    },
]
