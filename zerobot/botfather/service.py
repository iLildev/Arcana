"""High-level BotFather service: ownership checks + audit logging.

Wraps :class:`BotFatherClient` so callers (HTTP API, Builder Bot, future
Mini App) don't need to think about:

- verifying that ``user_id`` actually owns ``bot_id``;
- writing one ``BotFatherOperation`` audit row per attempted op;
- skipping unchanged fields when the caller passes a partial update;
- collapsing per-field errors into a single response.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.botfather.client import BotCommand, BotFatherClient, BotFatherError
from zerobot.database.models import Bot, BotFatherOperation


class _OwnershipError(BotFatherError):
    """403-style error: bot exists but is not owned by *user_id*."""


class _NotFoundError(BotFatherError):
    """404-style error: bot_id does not exist."""


# ── Read model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BotProfile:
    """The publicly-editable profile of a bot, as fetched from Telegram."""

    bot_id: str
    username: str | None
    name: str
    description: str
    short_description: str
    commands: list[BotCommand] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["commands"] = [c if isinstance(c, dict) else c.__dict__ for c in self.commands]
        return d


# ── Helpers ──────────────────────────────────────────────────────────────


async def _resolve_bot(session: AsyncSession, user_id: str, bot_id: str) -> Bot:
    """Look up the bot and verify ownership, raising typed errors."""
    bot = await session.get(Bot, bot_id)
    if bot is None:
        raise _NotFoundError(f"bot not found: {bot_id}", code=404)
    if bot.user_id != user_id:
        raise _OwnershipError(
            f"user {user_id} does not own bot {bot_id}", code=403
        )
    return bot


def _summarize(value: str | list | None) -> str | None:
    """Compact summary stored in the audit log (never the full payload)."""
    if value is None:
        return None
    if isinstance(value, list):
        return f"<{len(value)} items>"
    s = str(value)
    return s if len(s) <= 80 else s[:77] + "…"


async def _log_op(
    session: AsyncSession,
    user_id: str,
    bot_id: str,
    op_type: str,
    *,
    payload_summary: str | None,
    success: bool,
    error: str | None = None,
) -> None:
    """Append an audit row. Caller is responsible for committing."""
    session.add(
        BotFatherOperation(
            user_id=user_id,
            bot_id=bot_id,
            op_type=op_type,
            payload_summary=payload_summary,
            success=success,
            error=error,
        )
    )


# ── Public service surface ───────────────────────────────────────────────


async def fetch_bot_profile(
    session: AsyncSession,
    user_id: str,
    bot_id: str,
    *,
    http: httpx.AsyncClient | None = None,
) -> BotProfile:
    """Read the live profile of *bot_id* from Telegram.

    Raises :class:`BotFatherError` (with ``.code``) on ownership / lookup
    failures or any upstream API error.
    """
    bot = await _resolve_bot(session, user_id, bot_id)
    async with BotFatherClient(bot.token, http=http) as client:
        try:
            me = await client.get_me()
            name = await client.get_my_name()
            description = await client.get_my_description()
            short_description = await client.get_my_short_description()
            commands = await client.get_my_commands()
        except BotFatherError as exc:
            await _log_op(
                session,
                user_id,
                bot_id,
                "fetch_profile",
                payload_summary=None,
                success=False,
                error=str(exc),
            )
            await session.commit()
            raise

    await _log_op(
        session,
        user_id,
        bot_id,
        "fetch_profile",
        payload_summary=None,
        success=True,
    )
    await session.commit()
    return BotProfile(
        bot_id=bot.id,
        username=me.get("username"),
        name=name,
        description=description,
        short_description=short_description,
        commands=commands,
    )


async def update_bot_profile(
    session: AsyncSession,
    user_id: str,
    bot_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    short_description: str | None = None,
    commands: list[BotCommand | dict] | None = None,
    language_code: str = "",
    http: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    """Apply any subset of profile fields to *bot_id*.

    Returns a per-field result dict (``{"name": "ok", "description":
    "failed: <error>"}``). A field is omitted from the response if the
    caller did not supply it. Each attempted op writes one audit row.
    """
    bot = await _resolve_bot(session, user_id, bot_id)
    results: dict[str, str] = {}

    # The order matters only for predictable error messages; each call
    # is independent and Telegram applies them atomically per-method.
    operations = [
        ("name", "set_name", name, "set_my_name"),
        ("description", "set_description", description, "set_my_description"),
        ("short_description", "set_short_description", short_description, "set_my_short_description"),
        ("commands", "set_commands", commands, "set_my_commands"),
    ]

    async with BotFatherClient(bot.token, http=http) as client:
        for field_name, op_type, value, method in operations:
            if value is None:
                continue
            try:
                await getattr(client, method)(value, language_code=language_code)
                results[field_name] = "ok"
                await _log_op(
                    session,
                    user_id,
                    bot_id,
                    op_type,
                    payload_summary=_summarize(value),
                    success=True,
                )
            except BotFatherError as exc:
                results[field_name] = f"failed: {exc}"
                await _log_op(
                    session,
                    user_id,
                    bot_id,
                    op_type,
                    payload_summary=_summarize(value),
                    success=False,
                    error=str(exc),
                )

    # Mirror the live name/description back into the local Bot row so
    # admin lists stay consistent without an extra round-trip.
    if results.get("name") == "ok":
        bot.name = name
    if results.get("description") == "ok":
        bot.description = description

    await session.commit()
    return results
