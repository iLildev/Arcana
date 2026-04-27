"""Unit tests for the per-user, per-handler throttling middleware."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from arcana.bots.middleware.throttling import ThrottlingMiddleware, throttle


class _RealHandler:
    """Mimic aiogram's HandlerObject by exposing a ``callback`` attribute."""

    def __init__(self, fn) -> None:
        self.callback = fn


def _data(user_id: int, callback) -> dict:
    """Build the ``data`` dict aiogram passes to middlewares."""
    return {
        "event_from_user": SimpleNamespace(id=user_id),
        "handler": _RealHandler(callback),
    }


@pytest.mark.asyncio
async def test_throttling_drops_rapid_calls() -> None:
    """A second call within the rate window is silently swallowed."""
    mw = ThrottlingMiddleware(default_rate=1.0)
    calls = 0

    async def handler(event, data):
        nonlocal calls
        calls += 1
        return "ok"

    await mw(handler, object(), _data(42, handler))
    await mw(handler, object(), _data(42, handler))
    await mw(handler, object(), _data(42, handler))
    assert calls == 1


@pytest.mark.asyncio
async def test_throttling_lets_calls_through_after_delay() -> None:
    """Once the window elapses, the next call is accepted."""
    mw = ThrottlingMiddleware(default_rate=0.05)
    calls = 0

    async def handler(event, data):
        nonlocal calls
        calls += 1

    await mw(handler, object(), _data(42, handler))
    await asyncio.sleep(0.1)
    await mw(handler, object(), _data(42, handler))
    assert calls == 2


@pytest.mark.asyncio
async def test_throttling_isolates_users() -> None:
    """Different users share neither counters nor cool-downs."""
    mw = ThrottlingMiddleware(default_rate=10.0)  # large window so we'd notice leaks
    calls = 0

    async def handler(event, data):
        nonlocal calls
        calls += 1

    await mw(handler, object(), _data(1, handler))
    await mw(handler, object(), _data(2, handler))
    assert calls == 2


@pytest.mark.asyncio
async def test_throttling_isolates_handlers() -> None:
    """The same user hitting two distinct handlers doesn't trip either limiter."""
    mw = ThrottlingMiddleware(default_rate=10.0)
    a_called = b_called = False

    async def handler_a(event, data):
        nonlocal a_called
        a_called = True

    async def handler_b(event, data):
        nonlocal b_called
        b_called = True

    await mw(handler_a, object(), _data(1, handler_a))
    await mw(handler_b, object(), _data(1, handler_b))
    assert a_called and b_called


@pytest.mark.asyncio
async def test_throttling_skips_when_no_user() -> None:
    """Service updates without an associated user must always pass through."""
    mw = ThrottlingMiddleware(default_rate=10.0)
    calls = 0

    async def handler(event, data):
        nonlocal calls
        calls += 1

    data = {"event_from_user": None, "handler": _RealHandler(handler)}
    await mw(handler, object(), data)
    await mw(handler, object(), data)
    assert calls == 2


@pytest.mark.asyncio
async def test_throttle_decorator_overrides_default_rate() -> None:
    """A handler decorated with ``@throttle(0)`` is never blocked."""

    @throttle(0)
    async def handler(event, data):
        return "ok"

    mw = ThrottlingMiddleware(default_rate=10.0)
    for _ in range(3):
        result = await mw(handler, object(), _data(1, handler))
        assert result == "ok"


def test_throttle_decorator_sets_attribute() -> None:
    """The decorator attaches the rate so the middleware can read it."""

    @throttle(2.5)
    async def handler():
        return None

    assert handler.throttling_rate == 2.5
