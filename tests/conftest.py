"""Fixtures de tests (SPEC-01 NFR-07, NFR-08; Constitución P9).

- Los tests de integración corren contra PostgreSQL real (``TEST_DATABASE_URL``),
  nunca SQLite. Si la variable no está definida, se marcan como ``skip``.
- Aislamiento: el esquema se recrea una vez por sesión y las tablas se vacían
  (``TRUNCATE``) antes de cada test. Cada request HTTP usa su propia sesión,
  igual que en producción, lo que permite probar concurrencia real.
"""

import itertools
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

import pytest
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-no-usar-en-produccion-0123456789")

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.enums import EstadoCuenta, RolUsuario, SedeEnum  # noqa: E402
from app.core.security import crear_access_token, hash_password  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.config import models as _config_models  # noqa: E402, F401
from app.modules.config.models import ParametroGlobal  # noqa: E402
from app.modules.config.seed import PARAMETROS_SEMILLA  # noqa: E402
from app.modules.inventory import models as _inventory_models  # noqa: E402, F401
from app.modules.spaces import models as _spaces_models  # noqa: E402, F401
from app.modules.users.models import Usuario  # noqa: E402

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
PASSWORD = "Camara2026!"

_TABLAS = (
    "parametros_globales_historial, parametros_globales, usuarios_historial_estado, "
    "reservas_espacios, bloqueos_espacios, espacios, unidades_fisicas, equipamientos, "
    "categorias, usuarios"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL no definida: se omiten tests de integración.")
    for item in items:
        if "integracion" in item.keywords:
            item.add_marker(skip)


async def _crear_base_si_no_existe(url: str) -> None:
    destino = make_url(url)
    admin = create_async_engine(
        destino.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as conn:
        existe = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": destino.database}
        )
        if not existe:
            await conn.execute(text(f'CREATE DATABASE "{destino.database}"'))
    await admin.dispose()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    assert TEST_DATABASE_URL
    assert "test" in (make_url(TEST_DATABASE_URL).database or ""), (
        "Por seguridad, TEST_DATABASE_URL debe apuntar a una base cuyo nombre contenga 'test'."
    )
    await _crear_base_si_no_existe(TEST_DATABASE_URL)
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.execute(text("CREATE TYPE sede_enum AS ENUM ('Ushuaia', 'Río Grande')"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture(scope="session")
def sessionmaker_(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def db(
    engine: AsyncEngine, sessionmaker_: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncSession]:
    """Base limpia + parámetros semilla. Sesión para preparar datos y verificar."""
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_TABLAS} RESTART IDENTITY CASCADE"))
    async with sessionmaker_() as session:
        session.add_all(ParametroGlobal(**p) for p in PARAMETROS_SEMILLA)
        await session.commit()
        yield session


@pytest.fixture
async def client(
    db: AsyncSession, sessionmaker_: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx.AsyncClient]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


_secuencia = itertools.count(1)
_HASH_PASSWORD: str | None = None


def _hash_por_defecto() -> str:
    global _HASH_PASSWORD
    if _HASH_PASSWORD is None:
        _HASH_PASSWORD = hash_password(PASSWORD)
    return _HASH_PASSWORD


CrearUsuario = Callable[..., Awaitable[Usuario]]


@pytest.fixture
def crear_usuario(db: AsyncSession) -> CrearUsuario:
    """Fábrica: inserta un usuario directamente en la base (contraseña ``PASSWORD``)."""

    async def _crear(
        rol: RolUsuario = RolUsuario.ESTUDIANTE,
        sede: SedeEnum | None = SedeEnum.USHUAIA,
        estado: EstadoCuenta = EstadoCuenta.ACTIVO,
        *,
        email: str | None = None,
        nombre: str = "Ana",
        apellido: str | None = None,
        suspendido_hasta: datetime | None = None,
    ) -> Usuario:
        n = next(_secuencia)
        if rol == RolUsuario.SUPERADMIN:
            sede = None
        usuario = Usuario(
            email=email or f"usuario{n}@untdf.edu.ar",
            password_hash=_hash_por_defecto(),
            nombre=nombre,
            apellido=apellido or f"Apellido{n:04d}",
            dni=f"{30000000 + n}",
            rol=rol,
            sede=sede,
            estado=estado,
            suspendido_hasta=suspendido_hasta,
        )
        db.add(usuario)
        await db.commit()
        usuario._cache_auth = {  # type: ignore[attr-defined]
            "id": usuario.id,
            "rol": usuario.rol,
            "sede": usuario.sede,
            "token_version": usuario.token_version,
        }
        return usuario

    return _crear


def auth(usuario: Usuario) -> dict[str, str]:
    """Header ``Authorization`` con un token válido para ``usuario``.

    Usa el estado ya cargado (sin I/O): los atributos se leen del ``__dict__``
    aunque la instancia haya sido expirada por ``expire_all()`` en el test.
    """
    datos = usuario.__dict__
    attrs = ("id", "rol", "sede", "token_version")
    if not all(a in datos for a in attrs):
        datos = usuario._cache_auth  # type: ignore[attr-defined]
    token, _ = crear_access_token(
        usuario_id=datos["id"],
        rol=datos["rol"],
        sede=datos["sede"],
        token_version=datos["token_version"],
    )
    return {"Authorization": f"Bearer {token}"}
