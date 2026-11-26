"""Migraciones de Alembic contra PostgreSQL (Constitución P7.4; regla C19).

La base de tests sale de ``create_all`` (``tests/conftest.py``), así que nada más
verifica que las migraciones dejen el mismo esquema que los modelos. Estos tests las
corren de verdad sobre una base aparte, ``<TEST_DATABASE_URL>_mig``:

- cada migración baja y vuelve a subir, y el ``downgrade`` deja exactamente el
  esquema que había antes del ``upgrade``;
- en ``head``, el esquema migrado es igual al de los modelos: autogenerate vacío y el
  mismo catálogo (constraints con su definición, índices, columnas y enums) que la
  base de tests. Autogenerate solo no compara ``CHECK`` ni ``EXCLUDE``.

Reemplazan a los tests por migración que mockeaban ``op`` y comparaban los literales
del script (informe ``revision-tests/B6-migraciones.md``). Las migraciones que mueven
datos siguen con sus propios tests (``0010``, ``0017``, ``0019``).
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base
from tests.conftest import TEST_DATABASE_URL, _crear_base_si_no_existe

RAIZ = Path(__file__).parents[1]

_CATALOGO = {
    "constraints": """
        SELECT c.conrelid::regclass::text || '.' || c.conname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
        WHERE n.nspname = 'public' AND c.conrelid <> 0
          AND c.conrelid::regclass::text <> 'alembic_version'""",
    "indices": """
        SELECT tablename || '.' || indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'""",
    "columnas": """
        SELECT table_name || '.' || column_name,
               concat_ws('|', udt_name, is_nullable, column_default, character_maximum_length)
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name <> 'alembic_version'""",
    "enums": """
        SELECT t.typname, string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
        FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' GROUP BY t.typname""",
}

# Deuda conocida (informe B6, H-1): las migraciones 0001, 0005 y 0006 aplicaron la
# naming convention sobre nombres que ya la tenían (o la omitieron en las FK). Misma
# definición, otro nombre en una base migrada. Clave: nombre en la base migrada;
# valor: nombre según los modelos.
NOMBRES_HEREDADOS = {
    "usuarios.ck_usuarios_ck_usuarios_dni_numerico": "usuarios.ck_usuarios_dni_numerico",
    "usuarios.ck_usuarios_ck_usuarios_email_minusculas": "usuarios.ck_usuarios_email_minusculas",
    "usuarios.ck_usuarios_ck_usuarios_sede_segun_rol": "usuarios.ck_usuarios_sede_segun_rol",
    "usuarios.ck_usuarios_ck_usuarios_suspension_coherente": "usuarios.ck_usuarios_suspension_coherente",
    "usuarios.ck_usuarios_ck_usuarios_token_version_no_negativa": (
        "usuarios.ck_usuarios_token_version_no_negativa"
    ),
    "parametros_globales.ck_parametros_globales_ck_parametros_globales_clave_formato": (
        "parametros_globales.ck_parametros_globales_clave_formato"
    ),
    "parametros_globales.ck_parametros_globales_ck_parametros_globales_rango_coherente": (
        "parametros_globales.ck_parametros_globales_rango_coherente"
    ),
    "parametros_globales.ck_parametros_globales_ck_parametros_globales_version_positiva": (
        "parametros_globales.ck_parametros_globales_version_positiva"
    ),
    "equipamientos.ck_equipamientos_ck_equipamientos_max_dias_prestamo": (
        "equipamientos.ck_equipamientos_max_dias_prestamo"
    ),
    # Sólo entre 0006 y 0010: el downgrade de 0010 la recrea con el nombre correcto.
    "unidades_fisicas.ck_unidades_fisicas_ck_unidades_fisicas_locker_positivo": (
        "unidades_fisicas.ck_unidades_fisicas_locker_positivo"
    ),
    "bloqueos_espacios.fk_bloqueos_espacios_id_espacio": (
        "bloqueos_espacios.fk_bloqueos_espacios_id_espacio_espacios"
    ),
    "reservas_espacios.fk_reservas_espacios_id_espacio": (
        "reservas_espacios.fk_reservas_espacios_id_espacio_espacios"
    ),
}


def _config() -> Config:
    # Sin `alembic.ini`: así `env.py` no reconfigura el logging de pytest.
    config = Config()
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    return config


def _revisiones() -> list[str]:
    """Revisiones de la base a la cabeza."""
    return [r.revision for r in reversed(list(ScriptDirectory.from_config(_config()).walk_revisions()))]


def _catalogo(conn: Connection) -> dict[str, dict[str, str]]:
    """Catálogo del esquema ``public``, con los nombres heredados ya normalizados."""
    catalogo = {
        seccion: {nombre: definicion for nombre, definicion in conn.execute(text(consulta)).all()}
        for seccion, consulta in _CATALOGO.items()
    }
    catalogo["constraints"] = {
        NOMBRES_HEREDADOS.get(nombre, nombre): definicion
        for nombre, definicion in catalogo["constraints"].items()
    }
    return catalogo


def _diferencias(a: dict[str, dict[str, str]], b: dict[str, dict[str, str]]) -> list[str]:
    """Sólo lo que cambia entre dos catálogos, legible en el mensaje del assert."""
    return [
        f"{seccion} {nombre}: {a[seccion].get(nombre)!r} → {b[seccion].get(nombre)!r}"
        for seccion in _CATALOGO
        for nombre in sorted(a[seccion].keys() | b[seccion].keys())
        if a[seccion].get(nombre) != b[seccion].get(nombre)
    ]


async def _alembic(motor: AsyncEngine, comando, revision: str) -> None:
    config = _config()

    def _sync(conn: Connection) -> None:
        config.attributes["connection"] = conn
        comando(config, revision)

    async with motor.begin() as conn:
        await conn.run_sync(_sync)


async def _leer_catalogo(motor: AsyncEngine) -> dict[str, dict[str, str]]:
    async with motor.connect() as conn:
        return await conn.run_sync(_catalogo)


@pytest.fixture
async def motor_migraciones():
    """Base aparte y vacía (el nombre sigue conteniendo ``test``)."""
    url = make_url(TEST_DATABASE_URL)
    url = url.set(database=f"{url.database}_mig")
    await _crear_base_si_no_existe(url.render_as_string(hide_password=False))
    motor = create_async_engine(url, poolclass=NullPool)
    async with motor.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    yield motor
    await motor.dispose()


def test_alembic_tiene_una_sola_cabeza():  # C19: falla si otra migración cuelga de la misma base
    assert len(ScriptDirectory.from_config(_config()).get_heads()) == 1


@pytest.mark.integracion
async def test_cada_migracion_baja_y_vuelve_a_subir(motor_migraciones):  # P7.4
    def _escalera(conn: Connection) -> None:
        # Una sola conexión, con commit después de cada paso, como en un deploy.
        config = _config()
        config.attributes["connection"] = conn

        def _paso(accion):
            resultado = accion()
            conn.commit()
            return resultado

        for revision in _revisiones():
            antes = _paso(lambda: _catalogo(conn))
            try:
                _paso(lambda: command.upgrade(config, revision))
                _paso(lambda: command.downgrade(config, "-1"))
                despues = _paso(lambda: _catalogo(conn))
                _paso(lambda: command.upgrade(config, revision))
            except Exception as exc:  # noqa: BLE001 — se reporta con el nombre de la migración
                pytest.fail(f"{revision} no baja y vuelve a subir: {exc}")
            assert _diferencias(antes, despues) == [], (
                f"el downgrade de {revision} no deja el esquema anterior"
            )

    async with motor_migraciones.connect() as conn:
        await conn.run_sync(_escalera)


@pytest.mark.integracion
async def test_las_migraciones_dejan_el_esquema_de_los_modelos(engine, motor_migraciones):
    await _alembic(motor_migraciones, command.upgrade, "head")
    async with motor_migraciones.connect() as conn:
        diferencias = await conn.run_sync(
            lambda c: compare_metadata(
                MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata
            )
        )
        migrado = await conn.run_sync(_catalogo)
    modelos = await _leer_catalogo(engine)  # la base de tests, creada con `create_all`

    assert diferencias == []
    assert _diferencias(modelos, migrado) == []
