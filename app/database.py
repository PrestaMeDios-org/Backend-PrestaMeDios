"""Configuración de la capa de persistencia (SQLAlchemy 2.0 async).

Este módulo es compartido por todos los módulos de dominio del monolito.
Cada módulo define sus propios modelos heredando de ``Base``.
"""

import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/prestamedios",
)

# Engine asincrónico principal (asyncpg).
engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# Fábrica de sesiones asincrónicas.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Clase base declarativa de la que heredan todos los modelos ORM."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI que provee una sesión async por request.

    Uso:
        @router.get("/...")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
