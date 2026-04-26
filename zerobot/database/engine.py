"""Async SQLAlchemy engine + session factory.

A single ``AsyncEngine`` instance is created at import time using
``settings.DATABASE_URL``. ``AsyncSessionLocal`` is the canonical session
factory used everywhere; ``async_session_maker`` is kept as an alias to
preserve backwards compatibility with code that imports the old name.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from zerobot.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the project."""


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)

# Backwards-compatible alias used by the FastAPI dependency wiring.
async_session_maker = AsyncSessionLocal


async def get_session() -> AsyncSession:
    """Yield a single ``AsyncSession`` for use as a FastAPI dependency."""
    async with AsyncSessionLocal() as session:
        yield session
