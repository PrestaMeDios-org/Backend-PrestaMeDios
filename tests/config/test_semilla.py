"""Las copias congeladas de las migraciones coinciden con ``PARAMETROS_SEMILLA``.

SPEC-01 §11.2 (``0005``) y SPEC-09 §4.2 (``0017``): la semilla con la que se crea
la base de tests es el resultado de aplicar ``0005`` y después ``0017``.
"""

import importlib.util
from pathlib import Path

from app.core.enums import SedeEnum
from app.modules.config.seed import PARAMETROS_SEMILLA
from app.modules.config.service import SEGMENTO_SEDE, claves_de_sede

_VERSIONES = Path(__file__).parents[2] / "alembic" / "versions"


def _cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONES / f"{nombre}.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_semilla_de_migraciones_coincide_con_la_app():
    m0005 = _cargar("0005_users_y_parametros")
    m0017 = _cargar("0017_config_sedes")

    esperado = []
    for clave, tipo, valor, descripcion, unidad, vmin, vmax in m0005.PARAMETROS_SEMILLA:
        editable = True
        if clave in m0017.CLAVES_OBSOLETAS:  # RN-81
            descripcion, editable = m0017.PREFIJO_OBSOLETA + descripcion, False
        esperado.append((clave, tipo, valor, descripcion, unidad, vmin, vmax, editable))
    esperado += [(*fila, True) for fila in m0017.CLAVES_NUEVAS]

    app_semilla = [
        (
            p["clave"], p["tipo"], p["valor"], p["descripcion"],
            p["unidad"], p["valor_min"], p["valor_max"], p.get("editable", True),
        )
        for p in PARAMETROS_SEMILLA
    ]
    assert app_semilla == esperado


def test_cada_sede_tiene_segmento_y_sus_tres_claves():  # AC-109, RN-78, EC-54
    claves = {p["clave"] for p in PARAMETROS_SEMILLA}
    assert set(SEGMENTO_SEDE) == set(SedeEnum)
    for sede in SedeEnum:
        assert set(claves_de_sede(sede)) <= claves, sede
    assert len(set(SEGMENTO_SEDE.values())) == len(SEGMENTO_SEDE)
