"""Unit tests for the AsyncSession-injection middleware."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from arcana.bots.middleware.db_session import DBSessionMiddleware
from arcana.database.engine import Base
from arcana.database.models import User


@pytest_asyncio.fixture
async def sessionmaker():
    """Spin up a sqlite-backed sessionmaker with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_db_session_middleware_injects_session(sessionmaker) -> None:
    """Handlers receive a live session under the ``session`` key."""
    mw = DBSessionMiddleware(sessionmaker)
    captured = {}

    async def handler(event, data):
        captured["session"] = data.get("session")
        # Sanity check that the session can actually run a query.
        user = User(id="tg-1")
        data["session"].add(user)
        await data["session"].commit()
        return "ok"

    result = await mw(handler, object(), {})
    assert result == "ok"
    assert captured["session"] is not None


@pytest.mark.asyncio
async def test_db_session_middleware_persists_committed_changes(sessionmaker) -> None:
    """Anything the handler commits is visible after the middleware exits."""
    mw = DBSessionMiddleware(sessionmaker)

    async def handler(event, data):
        data["session"].add(User(id="tg-42"))
        await data["session"].commit()

    await mw(handler, object(), {})

    async with sessionmaker() as session:
        user = await session.get(User, "tg-42")
        assert user is not None


@pytest.mark.asyncio
async def test_db_session_middleware_rolls_back_on_exception(sessionmaker) -> None:
    """An uncaught exception inside the handler must roll back uncommitted writes."""
    mw = DBSessionMiddleware(sessionmaker)

    async def handler(event, data):
        data["session"].add(User(id="tg-99"))
        # Note: NOT committed before the exception.
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await mw(handler, object(), {})

    async with sessionmaker() as session:
        user = await session.get(User, "tg-99")
        assert user is None
