"""Global error catcher for bot handlers.

Exposes :func:`build_error_router`, which returns an aiogram ``Router``
that, once included on a dispatcher, intercepts every un-handled
exception raised inside any handler. The error is:

* logged with full stack-trace at ``ERROR`` level;
* re-published as a ``bot_error`` event so the Manager Bot's ``/events``
  endpoint can surface it to the human admin in real time;
* (optionally) acknowledged to the originating user with a localized
  apology, so the chat doesn't go silent on a crash.

Acknowledging the user is opt-in via the ``apology_text`` argument so
production deployments can choose between full silence (cleanest UX
when bugs are temporary) and a "something went wrong" reply.
"""

from __future__ import annotations

import logging
import traceback

from aiogram import Bot, Router
from aiogram.types import CallbackQuery, ErrorEvent, Message

from arcana.events.publisher import fire

log = logging.getLogger(__name__)

# Trim the trace to keep the event payload small and Telegram-safe.
_MAX_TRACE_CHARS = 1500


def _extract_user_id(event: ErrorEvent) -> str | None:
    """Best-effort extraction of the originating user's canonical id."""
    update = event.update
    src: Message | CallbackQuery | None = (
        update.message
        or update.callback_query
        or update.edited_message
        or update.my_chat_member
        or update.chat_member
    )
    if src is None or src.from_user is None:
        return None
    return f"tg-{src.from_user.id}"


def build_error_router(
    *,
    bot_label: str,
    apology_text: str | None = None,
) -> Router:
    """Return a router that catches every un-handled exception.

    Parameters
    ----------
    bot_label:
        Short identifier emitted with the event so admins can see which
        bot raised the error (e.g. ``"builder_bot"``).
    apology_text:
        If provided, the router answers the originating chat with this
        text after logging. Pass ``None`` to stay silent.
    """
    router = Router(name=f"errors:{bot_label}")

    @router.errors()
    async def _on_error(event: ErrorEvent, bot: Bot) -> bool:
        exc = event.exception
        update = event.update
        log.exception("[%s] unhandled error in handler", bot_label, exc_info=exc)

        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        fire(
            "bot_error",
            {
                "bot": bot_label,
                "error": f"{type(exc).__name__}: {exc}",
                "user_id": _extract_user_id(event),
                "update_id": update.update_id,
                "trace": trace[-_MAX_TRACE_CHARS:],
            },
        )

        # Don't crash on inability to apologise (admin chat only / no user).
        if apology_text:
            try:
                msg = update.message or (
                    update.callback_query.message if update.callback_query else None
                )
                if msg is not None:
                    await msg.answer(apology_text)
            except Exception:  # noqa: BLE001
                log.debug("[%s] could not send apology to user", bot_label)

        # Returning ``True`` tells aiogram we've handled the error so it
        # doesn't re-raise and tear down the polling loop.
        return True

    return router
