import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.database import Base, DATABASE_URL

# Importar todos los módulos de modelos para que sus tablas queden
# registradas en Base.metadata antes del autogenerate.
from app.core import models as _core_models  # noqa: F401  SPEC-11
from app.modules.config import models as _config_models  # noqa: F401
from app.modules.files import models as _files_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.loans import models as _loans_models  # noqa: F401
from app.modules.notifications import models as _notifications_models  # noqa: F401
from app.modules.notifications import portada as _portada_momentaneo  # noqa: F401  MOMENTÁNEO (SPEC-10 M-02)
from app.modules.spaces import models as _spaces_models  # noqa: F401
from app.modules.users import models as _users_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Migraciones en modo offline (genera SQL sin conectar)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # Una conexión pasada por `config.attributes` (tests/test_migraciones.py) se usa tal
    # cual; sin ella, se conecta a DATABASE_URL como siempre.
    conexion = config.attributes.get("connection")
    if conexion is not None:
        do_run_migrations(conexion)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
