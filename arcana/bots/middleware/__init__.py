"""Reusable aiogram 3 middlewares shared across the platform's bots.

Each middleware here is intentionally bot-agnostic: it operates on the
generic ``TelegramObject`` + ``data`` contract aiogram defines, so the
Builder Bot and the Manager Bot can share a single implementation.

Available middlewares:

* :class:`ThrottlingMiddleware` — per-(user, handler) rate limiter that
  silently drops events arriving faster than the configured rate.
* :class:`DBSessionMiddleware` — opens a fresh ``AsyncSession`` for the
  duration of each handler and rolls back on uncaught exceptions.
* :class:`ErrorCatcherRouter` (via :func:`build_error_router`) — catches
  un-handled exceptions raised inside any handler, logs them, and fires
  a ``bot_error`` event to the platform's event bus so admins are
  notified through the Manager Bot.
"""

from arcana.bots.middleware.db_session import DBSessionMiddleware
from arcana.bots.middleware.error_catcher import build_error_router
from arcana.bots.middleware.throttling import ThrottlingMiddleware, throttle

__all__ = [
    "DBSessionMiddleware",
    "ThrottlingMiddleware",
    "build_error_router",
    "throttle",
]
