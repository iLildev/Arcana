"""Broadcast a message to many Telegram chats with FloodWait + dead-chat handling.

The original ``aiogram-template`` shipped a ``broadcast`` helper that mixed
business logic (DB updates, progress messages) with the network loop. We
keep it cleaner by exposing a pure helper that takes:

* a ``Bot`` (so the same function works for any of the platform's bots);
* an iterable of Telegram user-ids (sync or async — admins typically pass
  a small list, automated jobs pass an async generator from the DB);
* the text + parse mode;
* an optional ``on_blocked`` async callback so callers can mark the
  user inactive in the DB without coupling this module to any model.

Returns a :class:`BroadcastResult` so callers can show ``"sent N, blocked M,
failed K"`` in their UI.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

log = logging.getLogger(__name__)


@dataclass
class BroadcastResult:
    """Aggregated outcome of a broadcast pass.

    ``sent``    — messages that Telegram acknowledged.
    ``blocked`` — recipients who blocked / deleted the bot.
    ``failed``  — every other failure (RetryAfter that retried-then-failed,
                  generic API errors). These are *not* retried again here so
                  the broadcast has a deterministic upper bound.
    """

    sent: int = 0
    blocked: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        """Total recipients we attempted to deliver to."""
        return self.sent + self.blocked + self.failed


async def _to_async_iter(
    user_ids: Iterable[int] | AsyncIterable[int],
) -> AsyncIterable[int]:
    """Adapt a sync iterable into an async one so the loop is uniform."""
    if hasattr(user_ids, "__aiter__"):
        async for uid in user_ids:  # type: ignore[union-attr]
            yield uid
    else:
        for uid in user_ids:  # type: ignore[union-attr]
            yield uid
            # Yield to the event loop so we don't starve other tasks even
            # when the iterable is a 10k-item list in memory.
            await asyncio.sleep(0)


async def broadcast_text(
    bot: Bot,
    user_ids: Iterable[int] | AsyncIterable[int],
    text: str,
    *,
    parse_mode: str | None = "HTML",
    delay: float = 0.05,
    on_blocked: Callable[[int], Awaitable[None]] | None = None,
    progress: Callable[[BroadcastResult], Awaitable[None]] | None = None,
    progress_every: int = 25,
) -> BroadcastResult:
    """Send *text* to every Telegram ``user_id``, returning aggregated counts.

    The function honours Telegram's :class:`TelegramRetryAfter` by sleeping
    for the requested duration and then retrying *once*. ``TelegramForbidden``
    (user blocked the bot, or deactivated their account) increments
    ``blocked`` and triggers ``on_blocked`` so the caller can update its
    DB. ``delay`` enforces a tiny gap between sends (default 50ms) which is
    well below Telegram's per-bot global rate limit.
    """
    result = BroadcastResult()

    async for user_id in _to_async_iter(user_ids):
        try:
            await bot.send_message(user_id, text, parse_mode=parse_mode)
            result.sent += 1
        except TelegramRetryAfter as e:
            log.warning(
                "broadcast: floodwait %ss for user=%s, sleeping then retrying",
                e.retry_after,
                user_id,
            )
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(user_id, text, parse_mode=parse_mode)
                result.sent += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("broadcast: retry failed for %s: %s", user_id, exc)
                result.failed += 1
        except TelegramForbiddenError:
            result.blocked += 1
            if on_blocked is not None:
                with contextlib.suppress(Exception):
                    await on_blocked(user_id)
        except TelegramAPIError as exc:
            log.warning("broadcast: API error for %s: %s", user_id, exc)
            result.failed += 1

        if progress is not None and result.total and result.total % progress_every == 0:
            with contextlib.suppress(Exception):
                await progress(result)

        if delay > 0:
            await asyncio.sleep(delay)

    return result
