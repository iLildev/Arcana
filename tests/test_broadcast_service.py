"""Unit tests for the broadcast helper.

We don't talk to Telegram here — the ``Bot`` is a ``MagicMock`` so we can
assert exact send patterns and exercise both the FloodWait retry path and
the "user blocked the bot" cleanup hook.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from arcana.services.broadcast import broadcast_text


def _make_bot(send_impl) -> MagicMock:
    """Build a ``Bot`` stub whose ``send_message`` runs *send_impl*."""
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=send_impl)
    return bot


@pytest.mark.asyncio
async def test_broadcast_counts_successful_sends() -> None:
    sent: list[int] = []

    async def send(uid, text, parse_mode=None):
        sent.append(uid)

    bot = _make_bot(send)
    result = await broadcast_text(bot, [1, 2, 3], "hello", delay=0)

    assert sent == [1, 2, 3]
    assert result.sent == 3
    assert result.blocked == 0
    assert result.failed == 0
    assert result.total == 3


@pytest.mark.asyncio
async def test_broadcast_counts_blocked_users() -> None:
    """Users who blocked the bot bump ``blocked`` and skip the send."""

    async def send(uid, text, parse_mode=None):
        if uid == 2:
            raise TelegramForbiddenError(method=MagicMock(), message="user blocked")

    bot = _make_bot(send)
    result = await broadcast_text(bot, [1, 2, 3], "hi", delay=0)

    assert result.sent == 2
    assert result.blocked == 1
    assert result.failed == 0


@pytest.mark.asyncio
async def test_broadcast_invokes_on_blocked_callback() -> None:
    """The ``on_blocked`` hook fires once per blocked recipient."""
    blocked_seen: list[int] = []

    async def send(uid, text, parse_mode=None):
        if uid in (2, 4):
            raise TelegramForbiddenError(method=MagicMock(), message="blocked")

    async def on_blocked(uid):
        blocked_seen.append(uid)

    bot = _make_bot(send)
    result = await broadcast_text(bot, [1, 2, 3, 4], "hi", on_blocked=on_blocked, delay=0)

    assert blocked_seen == [2, 4]
    assert result.blocked == 2
    assert result.sent == 2


@pytest.mark.asyncio
async def test_broadcast_retries_after_floodwait() -> None:
    """A first FloodWait sleeps then retries; success counts as ``sent``."""
    attempts: dict[int, int] = {}

    async def send(uid, text, parse_mode=None):
        attempts[uid] = attempts.get(uid, 0) + 1
        if uid == 2 and attempts[uid] == 1:
            raise TelegramRetryAfter(
                method=MagicMock(),
                message="flood",
                retry_after=0,
            )

    bot = _make_bot(send)
    result = await broadcast_text(bot, [1, 2, 3], "hi", delay=0)

    assert attempts[2] == 2  # initial + one retry
    assert result.sent == 3
    assert result.failed == 0


@pytest.mark.asyncio
async def test_broadcast_counts_generic_api_errors_as_failed() -> None:
    """A generic TelegramAPIError doesn't crash the loop and counts as failed."""

    async def send(uid, text, parse_mode=None):
        if uid == 2:
            raise TelegramAPIError(method=MagicMock(), message="boom")

    bot = _make_bot(send)
    result = await broadcast_text(bot, [1, 2, 3], "hi", delay=0)

    assert result.sent == 2
    assert result.failed == 1
    assert result.blocked == 0


@pytest.mark.asyncio
async def test_broadcast_invokes_progress_callback() -> None:
    """``progress`` fires every ``progress_every`` deliveries."""
    snapshots: list[int] = []

    async def send(uid, text, parse_mode=None):
        return None

    async def progress(result):
        snapshots.append(result.total)

    bot = _make_bot(send)
    await broadcast_text(
        bot,
        list(range(10)),
        "hi",
        delay=0,
        progress=progress,
        progress_every=3,
    )

    # Fires at total=3, 6, 9.
    assert snapshots == [3, 6, 9]


@pytest.mark.asyncio
async def test_broadcast_supports_async_iterable() -> None:
    """An async generator (e.g. streamed DB cursor) is also accepted."""

    async def gen():
        for i in range(3):
            yield i + 100

    async def send(uid, text, parse_mode=None):
        return None

    bot = _make_bot(send)
    result = await broadcast_text(bot, gen(), "hi", delay=0)
    assert result.sent == 3
