"""Per-(user, handler) throttling middleware.

A pure-Python sliding-window limiter that needs no external dependency
(unlike the original ``aiolimiter``-based implementation in the upstream
template). When a user sends events faster than the configured rate for
a given handler, extra events are silently dropped and an ``INFO`` line
is logged so operators can spot abusive patterns.

A handler can opt into a custom rate by attaching ``throttling_rate`` to
its callable, either directly::

    async def cmd(message): ...
    cmd.throttling_rate = 2.0  # at most one /cmd every 2 seconds

…or via the :func:`throttle` decorator::

    @throttle(2.0)
    async def cmd(message): ...
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

log = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Drop events that arrive faster than ``rate`` seconds for the same
    ``(user, handler)`` pair.

    The limiter is purely process-local and uses ``time.monotonic``; restart
    the bot to clear all counters. ``default_rate`` is the floor applied to
    handlers that don't override it.
    """

    def __init__(self, default_rate: float = 0.3) -> None:
        self.default_rate = float(default_rate)
        # key: ``"<tg_user_id>:<handler_qualname>"`` → last accepted timestamp.
        self._last_call: dict[str, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            # Service updates (e.g. chat-member changes from admins) are not
            # subject to throttling: dropping them silently would be confusing.
            return await handler(event, data)

        real_handler = data.get("handler")
        callback = getattr(real_handler, "callback", None)
        rate = float(getattr(callback, "throttling_rate", self.default_rate))
        if rate <= 0:
            return await handler(event, data)

        callback_name = getattr(callback, "__qualname__", None) or repr(callback)
        key = f"{user.id}:{callback_name}"

        now = time.monotonic()
        last = self._last_call.get(key, 0.0)
        if now - last < rate:
            log.info("throttled user=%s key=%s rate=%.2fs", user.id, callback_name, rate)
            return None

        self._last_call[key] = now
        return await handler(event, data)


def throttle(rate: float) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that attaches a custom throttling rate to a handler."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.throttling_rate = float(rate)  # type: ignore[attr-defined]
        return fn

    return deco
