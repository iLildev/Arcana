"""Inject an :class:`~sqlalchemy.ext.asyncio.AsyncSession` into every handler.

Saves us the boilerplate of opening ``AsyncSessionLocal()`` in every handler
body. A handler signals it wants the session by accepting a ``session``
keyword argument; aiogram's dependency-injection layer reads it out of the
``data`` dict we populate.

The session lifecycle is bound to the handler call:

* opened when the middleware is entered;
* explicitly rolled back if the handler raises (so a partial mutation
  cannot leak out);
* closed (and any pending transaction committed by the surrounding ``async
  with``) on the way out.

Handlers are expected to call :pymeth:`session.commit()` themselves when
they want to persist changes, exactly as they do today.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from arcana.database.engine import AsyncSessionLocal


class DBSessionMiddleware(BaseMiddleware):
    """Open a fresh :class:`AsyncSession` for the duration of every handler."""

    def __init__(self, sessionmaker: async_sessionmaker | None = None) -> None:
        # Tests inject a sqlite-backed sessionmaker; production code uses
        # the package-level singleton bound to Postgres.
        self._sessionmaker = sessionmaker or AsyncSessionLocal

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._sessionmaker() as session:
            data["session"] = session
            try:
                return await handler(event, data)
            except Exception:
                await session.rollback()
                raise
