"""SPEC-06 Fase B · Plantillas de notificación (RN-N7…RN-N9) — NTF-14, NTF-15, NTF-16.

Sin base de datos: `renderizar` es una función pura.
"""

import pytest

from app.modules.notifications.enums import Severidad, TipoNotificacion
from app.modules.notifications.plantillas import (
    CLAVES_PROHIBIDAS,
    MENSAJE_MAX,
    PLANTILLAS,
    renderizar,
)
from tests.notifications.conftest import datos_de_ejemplo

T = TipoNotificacion
CRITICAS = {T.ORDEN_HORARIO_AJUSTADO, T.ORDEN_CANCELACION_FORZADA, T.RESERVA_CANCELACION_FORZADA}


def test_todos_los_tipos_tienen_plantilla():  # NTF-15
    assert set(PLANTILLAS) == set(TipoNotificacion)


@pytest.mark.parametrize("tipo", list(TipoNotificacion))
def test_cada_plantilla_se_arma_sin_variables_sueltas(tipo):  # NTF-15
    datos = datos_de_ejemplo(tipo)
    _, titulo, mensaje = renderizar(tipo, datos)
    assert titulo and mensaje
    assert "$" not in titulo + mensaje
    for valor in datos.values():
        assert valor in mensaje  # todas las claves declaradas se usan


def test_ninguna_plantilla_pide_datos_personales():  # NTF-15 (RN-N8)
    for plantilla in PLANTILLAS.values():
        assert not plantilla.claves & CLAVES_PROHIBIDAS


def test_severidades():  # NTF-16 (NOV-04, RN-N9)
    for tipo, plantilla in PLANTILLAS.items():
        esperada = Severidad.CRITICA if tipo in CRITICAS else Severidad.NORMAL
        assert plantilla.severidad == esperada, tipo


@pytest.mark.parametrize(
    "cambio",
    [{"quitar": "numero_orden"}, {"agregar": ("email", "x@untdf.edu.ar")}],
    ids=["falta-una-clave", "sobra-una-clave"],
)
def test_datos_incompletos_o_de_mas_son_value_error(cambio):  # NTF-14
    datos = datos_de_ejemplo(T.ORDEN_APROBADA)
    if "quitar" in cambio:
        datos.pop(cambio["quitar"])
    else:
        clave, valor = cambio["agregar"]
        datos[clave] = valor
    with pytest.raises(ValueError, match="ORDEN_APROBADA"):
        renderizar(T.ORDEN_APROBADA, datos)


def test_valores_que_no_son_texto_son_value_error():  # NTF-14
    datos = {**datos_de_ejemplo(T.ORDEN_NO_RETIRADA), "numero_orden": 42}
    with pytest.raises(ValueError, match="texto"):
        renderizar(T.ORDEN_NO_RETIRADA, datos)  # type: ignore[arg-type]


def test_mensaje_largo_se_recorta_al_largo_de_la_columna():
    datos = {"numero_orden": "1", "motivo": "x" * 2000}
    _, _, mensaje = renderizar(T.ORDEN_RECHAZADA, datos)
    assert len(mensaje) == MENSAJE_MAX and mensaje.endswith("…")
