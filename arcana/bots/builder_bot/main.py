"""Arcana Builder Bot — autonomous coding agent over Telegram.

Wraps :class:`arcana.agents.builder_agent.BuilderAgent` in an aiogram
polling bot. Each Telegram message becomes one agent turn; tool calls and
intermediate text are streamed back by editing a placeholder reply
in-place. After the turn completes, crystals are deducted from the user's
wallet (the platform admin defined by ``ADMIN_USER_ID`` is exempt).

Phase 0: every non-admin user must verify their phone number (via
Telegram's request_contact button) before the agent will run. A user can
clear their data at any time with /unlink_phone.

The bot ships with first-class multilingual support (Arabic, English,
French, Spanish, Russian, Turkish). Each user can pick a language with
/lang; the choice is stored in the ``users.language`` column and falls
back to Telegram's reported language code on first message.

Required env:
    BUILDER_BOT_TOKEN          Telegram bot token (from BotFather)
Optional env (with defaults):
    ADMIN_USER_ID              Exempt from crystal billing (default "")
    BUILDER_TOKENS_PER_CRYSTAL Billing rate (default 5000)
    BUILDER_MIN_BALANCE        Refuse new turns below this (default 1)
    BUILDER_MAX_REPLY_LEN      Split outbound messages above this (default 3800)

Run from the project root::

    python -m arcana.bots.builder_bot.main
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import time
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import select as sa_select

from arcana.agents.builder_agent import BuilderAgent
from arcana.botfather import (
    BotFatherError,
    fetch_bot_profile,
    update_bot_profile,
)
from arcana.bots.builder_bot.locales import (
    DEFAULT_LANG,
    LANGUAGES,
    normalize_lang,
    t,
)
from arcana.bots.middleware import (
    DBSessionMiddleware,
    ThrottlingMiddleware,
    build_error_router,
    throttle,
)
from arcana.config import settings
from arcana.database.engine import AsyncSessionLocal
from arcana.database.models import Bot as BotModel
from arcana.database.models import User
from arcana.database.wallet import InsufficientCrystalsError, WalletService
from arcana.events.publisher import fire
from arcana.identity import (
    PhoneError,
    is_phone_verified,
    record_phone_verification,
    unlink_phone,
)
from arcana.services.broadcast import broadcast_text

# ─────────────── Config ───────────────

BOT_TOKEN = os.getenv("BUILDER_BOT_TOKEN", "").strip()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()
TOKENS_PER_CRYSTAL = max(100, int(os.getenv("BUILDER_TOKENS_PER_CRYSTAL", "5000")))
MIN_BALANCE = max(1, int(os.getenv("BUILDER_MIN_BALANCE", "1")))
MAX_REPLY_LEN = min(4090, int(os.getenv("BUILDER_MAX_REPLY_LEN", "3800")))

if not BOT_TOKEN:
    print("❌ BUILDER_BOT_TOKEN is required", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("builder_bot")


# ─────────────── Wiring ───────────────

bot = Bot(token=BOT_TOKEN)
router = Router()
agent = BuilderAgent()

# Per-user lock so concurrent messages from the same user are serialized
# (the agent's session history isn't safe under interleaved edits).
_user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# Process-local cache of the user's preferred language to avoid hitting
# the DB on every message just for translation lookup. Invalidated on
# explicit /lang change.
_lang_cache: dict[str, str] = {}


def tg_user_id(message: Message | CallbackQuery) -> str:
    """Map a Telegram user id to the canonical Arcana user id."""
    return f"tg-{message.from_user.id}"


def chunk_text(text: str, limit: int = MAX_REPLY_LEN) -> list[str]:
    """Split a long reply into chunks ≤ *limit* on paragraph / line boundaries."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


# ─────────────── Language helpers ───────────────


async def get_user_lang(user_id: str, telegram_lang: str | None = None) -> str:
    """Return the user's preferred language code.

    Resolution order:
      1. Process-local cache.
      2. ``users.language`` column.
      3. Telegram's reported ``language_code`` (if supported).
      4. :data:`DEFAULT_LANG`.

    The first DB hit also seeds the cache so subsequent messages skip it.
    """
    cached = _lang_cache.get(user_id)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        stored = user.language if user else None

    lang = normalize_lang(stored) if stored else normalize_lang(telegram_lang)
    _lang_cache[user_id] = lang
    return lang


async def set_user_lang(user_id: str, lang: str) -> str:
    """Persist *lang* for *user_id* and refresh the cache. Returns the resolved code."""
    lang = normalize_lang(lang)
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(id=user_id, language=lang)
            session.add(user)
        else:
            user.language = lang
        await session.commit()
    _lang_cache[user_id] = lang
    return lang


def _tg_lang(message: Message | CallbackQuery) -> str | None:
    """Best-effort extraction of the user's Telegram-reported language code."""
    user = message.from_user
    return getattr(user, "language_code", None)


async def _lang_for(message: Message | CallbackQuery) -> str:
    """Shorthand: resolve the user's language from the message context."""
    return await get_user_lang(tg_user_id(message), telegram_lang=_tg_lang(message))


# ─────────────── Identity gate ───────────────


def _contact_kb(lang: str) -> ReplyKeyboardMarkup:
    """Reply-keyboard with a localized contact-share button."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("phone_share_button", lang), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _prompt_phone_share(message: Message, lang: str) -> None:
    """Ask the user to share their phone via Telegram's contact button."""
    await message.answer(
        t("phone_prompt", lang),
        parse_mode="HTML",
        reply_markup=_contact_kb(lang),
    )


def _is_admin(user_id: str) -> bool:
    """Phone gate is bypassed for the platform admin."""
    return bool(ADMIN_USER_ID) and user_id == ADMIN_USER_ID


async def _ensure_verified(message: Message, lang: str) -> bool:
    """Return True iff the user has a verified phone (admin always passes)."""
    user_id = tg_user_id(message)
    if _is_admin(user_id) or not settings.REQUIRE_PHONE_VERIFICATION:
        return True
    async with AsyncSessionLocal() as session:
        verified = await is_phone_verified(session, user_id)
    if not verified:
        await _prompt_phone_share(message, lang)
        return False
    return True


# ─────────────── Wallet helpers ───────────────


async def get_balance(user_id: str) -> int:
    """Fetch the current crystal balance for *user_id*."""
    async with AsyncSessionLocal() as session:
        wallet = await WalletService(session).get_wallet(user_id)
        return wallet.balance


async def charge(user_id: str, amount: int) -> int:
    """Deduct *amount* crystals from *user_id*; return the new balance.

    The Builder Agent has already consumed billable LLM tokens by the time
    we get here, so refusing to charge would simply socialize the cost.
    Instead, we delegate to :class:`WalletService` (the canonical mutator)
    when the wallet can cover the full amount; on shortfall we drain to
    zero and emit a structured warning so operators can spot under-billing.
    """
    if amount <= 0:
        return await get_balance(user_id)

    async with AsyncSessionLocal() as session:
        service = WalletService(session)
        try:
            await service.charge(user_id, amount)
        except InsufficientCrystalsError as exc:
            wallet = await service.get_wallet(user_id)
            shortfall = exc.requested - exc.available
            if wallet.balance > 0:
                wallet.balance = 0
                await session.commit()
            log.warning(
                "wallet shortfall: user=%s requested=%d available=%d shortfall=%d",
                user_id,
                exc.requested,
                exc.available,
                shortfall,
            )
        wallet = await service.get_wallet(user_id)
        return wallet.balance


def crystals_for(tokens: int) -> int:
    """Convert raw tokens to crystals using ``TOKENS_PER_CRYSTAL`` (min 1)."""
    return max(1, tokens // TOKENS_PER_CRYSTAL)


# ─────────────── Commands ───────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Show the welcome screen with role, balance, and a hint to /help."""
    lang = await _lang_for(message)
    user_id = tg_user_id(message)
    is_admin = _is_admin(user_id)
    balance = await get_balance(user_id)
    async with AsyncSessionLocal() as session:
        verified = await is_phone_verified(session, user_id)

    role = t("role_admin", lang) if is_admin else t("role_user", lang)
    verified_label = (
        t("status_verified", lang) if verified or is_admin else t("status_unverified", lang)
    )
    exempt = t("exempt_marker", lang) if is_admin else ""

    await message.answer(
        t(
            "start_welcome",
            lang,
            role=role,
            verified=verified_label,
            balance=balance,
            rate=TOKENS_PER_CRYSTAL,
            exempt=exempt,
        ),
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Send the comprehensive user guide in the user's language."""
    lang = await _lang_for(message)
    await message.answer(t("help_full", lang), parse_mode="HTML")


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    """Reply with the user's current crystal balance."""
    lang = await _lang_for(message)
    balance = await get_balance(tg_user_id(message))
    await message.answer(t("balance_reply", lang, balance=balance), parse_mode="HTML")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Wipe the user's workspace and conversation history."""
    lang = await _lang_for(message)
    agent.reset(tg_user_id(message))
    await message.answer(t("reset_done", lang))


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show quick session stats (turns, tokens, equivalent crystals)."""
    lang = await _lang_for(message)
    user_id = tg_user_id(message)
    session = agent.sessions.get(user_id)
    turns = sum(1 for m in session.messages if m["role"] == "user")
    total_tokens = session.total_input_tokens + session.total_output_tokens
    await message.answer(
        t(
            "stats_template",
            lang,
            turns=turns,
            input_tokens=session.total_input_tokens,
            output_tokens=session.total_output_tokens,
            crystals=crystals_for(total_tokens),
        ),
        parse_mode="HTML",
    )


# ─────────────── Language selection ───────────────


def _lang_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard with one button per supported language."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code, name in LANGUAGES.items():
        row.append(InlineKeyboardButton(text=name, callback_data=f"lang:{code}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("lang"))
async def cmd_lang(message: Message) -> None:
    """Show the language menu, or change directly when an arg is given.

    Usage:
        /lang             → interactive menu
        /lang <code>      → set immediately (e.g. /lang en)
    """
    lang = await _lang_for(message)
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        target = parts[1].strip().lower()
        if target not in LANGUAGES:
            await message.answer(
                t("lang_invalid", lang, codes=", ".join(LANGUAGES)),
                parse_mode="HTML",
            )
            return
        new_lang = await set_user_lang(tg_user_id(message), target)
        await message.answer(
            t("lang_changed", new_lang, name=LANGUAGES[new_lang]),
            parse_mode="HTML",
        )
        return

    await message.answer(
        t("lang_choose", lang, current=LANGUAGES.get(lang, lang)),
        parse_mode="HTML",
        reply_markup=_lang_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def on_lang_callback(call: CallbackQuery) -> None:
    """Apply a language choice from the inline keyboard."""
    code = (call.data or "").split(":", 1)[1] if call.data else ""
    if code not in LANGUAGES:
        await call.answer("?", show_alert=False)
        return
    new_lang = await set_user_lang(tg_user_id(call), code)
    with contextlib.suppress(TelegramBadRequest):
        await call.message.edit_text(
            t("lang_changed", new_lang, name=LANGUAGES[new_lang]),
            parse_mode="HTML",
        )
    await call.answer()


# ─────────────── BotFather automation (Phase 1.ج) ───────────────


def _split_args(message: Message, *, expected: int) -> list[str] | None:
    """Return the command arguments, or None if the wrong number was supplied."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=expected)
    return parts[1:] if len(parts) > expected else None


async def _resolve_my_bot(user_id: str, bot_id: str) -> BotModel | None:
    """Return the bot iff *user_id* owns it."""
    async with AsyncSessionLocal() as session:
        bot_row = await session.get(BotModel, bot_id)
    return bot_row if bot_row and bot_row.user_id == user_id else None


@router.message(Command("mybots"))
async def cmd_mybots(message: Message) -> None:
    """List the bots owned by the caller."""
    lang = await _lang_for(message)
    if not await _ensure_verified(message, lang):
        return
    user_id = tg_user_id(message)
    async with AsyncSessionLocal() as session:
        rows = (
            (await session.execute(sa_select(BotModel).where(BotModel.user_id == user_id)))
            .scalars()
            .all()
        )
    if not rows:
        await message.answer(t("mybots_empty", lang))
        return
    unnamed = t("mybots_unnamed", lang)
    lines = [t("mybots_header", lang), ""]
    for b in rows:
        status = "🟢" if b.is_active else ("💤" if b.is_hibernated else "⚪️")
        lines.append(f"{status} <code>{b.id}</code> — {b.name or unnamed}")
    lines += ["", t("mybots_hint", lang)]
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    """Show a bot's live profile (name, descriptions, commands)."""
    lang = await _lang_for(message)
    if not await _ensure_verified(message, lang):
        return
    args = _split_args(message, expected=1)
    if not args:
        await message.answer(t("profile_usage", lang), parse_mode="HTML")
        return
    user_id = tg_user_id(message)
    bot_id = args[0]
    async with AsyncSessionLocal() as session:
        try:
            profile = await fetch_bot_profile(session, user_id, bot_id)
        except BotFatherError as exc:
            await message.answer(t("profile_read_failed", lang, error=str(exc)))
            return
    empty = t("profile_empty_field", lang)
    cmds = "\n".join(f"  /{c.command} — {c.description}" for c in profile.commands) or t(
        "profile_no_commands", lang
    )
    await message.answer(
        t(
            "profile_template",
            lang,
            username=profile.username or "?",
            name=profile.name or empty,
            about=profile.short_description or empty,
            desc=profile.description or empty,
            cmds=cmds,
        ),
        parse_mode="HTML",
    )


async def _apply_profile_update(message: Message, lang: str, bot_id: str, **fields: object) -> None:
    """Shared helper for /setname, /setdesc, /setabout."""
    user_id = tg_user_id(message)
    if await _resolve_my_bot(user_id, bot_id) is None:
        await message.answer(t("bot_not_found", lang))
        return
    async with AsyncSessionLocal() as session:
        try:
            results = await update_bot_profile(session, user_id, bot_id, **fields)
        except BotFatherError as exc:
            await message.answer(t("update_warn", lang, detail=str(exc)))
            return
    line = next(iter(results.values()), "no-op")
    if line == "ok":
        await message.answer(t("update_ok", lang))
    else:
        await message.answer(t("update_warn", lang, detail=line))


@router.message(Command("setname"))
async def cmd_setname(message: Message) -> None:
    """Rename a bot. Usage: /setname <bot_id> <new name…>"""
    lang = await _lang_for(message)
    if not await _ensure_verified(message, lang):
        return
    args = _split_args(message, expected=2)
    if not args or len(args) < 2 or not args[1].strip():
        await message.answer(t("setname_usage", lang), parse_mode="HTML")
        return
    await _apply_profile_update(message, lang, args[0], name=args[1].strip())


@router.message(Command("setdesc"))
async def cmd_setdesc(message: Message) -> None:
    """Update the long description. Usage: /setdesc <bot_id> <description…>"""
    lang = await _lang_for(message)
    if not await _ensure_verified(message, lang):
        return
    args = _split_args(message, expected=2)
    if not args or len(args) < 2 or not args[1].strip():
        await message.answer(t("setdesc_usage", lang), parse_mode="HTML")
        return
    await _apply_profile_update(message, lang, args[0], description=args[1].strip())


@router.message(Command("setabout"))
async def cmd_setabout(message: Message) -> None:
    """Update the short "about" line. Usage: /setabout <bot_id> <text…>"""
    lang = await _lang_for(message)
    if not await _ensure_verified(message, lang):
        return
    args = _split_args(message, expected=2)
    if not args or len(args) < 2 or not args[1].strip():
        await message.answer(t("setabout_usage", lang), parse_mode="HTML")
        return
    await _apply_profile_update(message, lang, args[0], short_description=args[1].strip())


@router.message(Command("unlink_phone"))
async def cmd_unlink_phone(message: Message) -> None:
    """Wipe the user's verified phone (GDPR-style "delete my data")."""
    lang = await _lang_for(message)
    user_id = tg_user_id(message)
    async with AsyncSessionLocal() as session:
        cleared = await unlink_phone(session, user_id, source="user_command")
    if cleared:
        fire("phone_unlinked", {"user_id": user_id})
        await message.answer(
            t("phone_unlinked", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(t("phone_no_record", lang))


# ─────────────── Contact handler ───────────────


async def _fetch_profile_photo_id(tg_user_id_int: int) -> str | None:
    """Return the user's biggest available profile-photo ``file_id`` or ``None``.

    ``file_id`` from ``getUserProfilePhotos`` is reusable across bots that
    share the same Bot API server, so the Manager Bot can re-send it as a
    ``send_photo`` without re-uploading. Failures are non-fatal — we'd
    rather log a "new user" event without a picture than fail the contact
    handler.
    """
    try:
        photos = await bot.get_user_profile_photos(tg_user_id_int, limit=1)
    except Exception:  # noqa: BLE001
        log.debug("could not fetch profile photos for %s", tg_user_id_int)
        return None
    if not photos.total_count or not photos.photos:
        return None
    # Each entry in photos.photos is a list of PhotoSize from smallest to
    # largest; the last item is the highest resolution.
    sizes = photos.photos[0]
    return sizes[-1].file_id if sizes else None


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    """Handle the contact-share that completes phone verification."""
    lang = await _lang_for(message)
    contact = message.contact
    # Telegram's request_contact button always returns the sender's own
    # contact, with `user_id` set. Reject manually-forwarded cards.
    if contact is None or contact.user_id != message.from_user.id:
        await message.answer(t("phone_only_own", lang))
        return

    user_id = tg_user_id(message)
    is_new_user = False
    try:
        async with AsyncSessionLocal() as session:
            # Detect first-time registration *before* recording the phone
            # so we can fire ``user_registered`` once and only once. We
            # don't touch the row here — ``record_phone_verification``
            # will create/update it transactionally below.
            existing = await session.get(User, user_id)
            is_new_user = existing is None

            await record_phone_verification(
                session,
                user_id,
                contact.phone_number,
                source="telegram_contact",
                ip_hash=None,
            )
    except PhoneError as exc:
        await message.answer(t("phone_dup_error", lang, error=str(exc)))
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("phone verification failed for %s", user_id)
        await message.answer(t("phone_internal_error", lang, error=type(exc).__name__))
        return

    fire("phone_verified", {"user_id": user_id, "source": "builder_bot"})

    if is_new_user:
        # Enrich the registration event with the data the Manager Bot
        # needs to render a friendly "new user" card (avatar + handle).
        from_user = message.from_user
        photo_file_id = await _fetch_profile_photo_id(from_user.id)
        full_name = " ".join(
            part for part in (from_user.first_name, from_user.last_name) if part
        ).strip() or None
        fire(
            "user_registered",
            {
                "user_id": user_id,
                "telegram_user_id": from_user.id,
                "username": from_user.username,
                "full_name": full_name,
                "language": lang,
                "photo_file_id": photo_file_id,
                "source": "builder_bot",
            },
        )

    await message.answer(
        t("phone_verified_ok", lang),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


# ─────────────── Block / unblock tracking ───────────────


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    """Detect when a user blocks or unblocks the bot.

    Telegram delivers a ``my_chat_member`` update whenever the bot's
    membership in a chat changes; for private chats that means the user
    either started/un-blocked us (status ``member``) or stopped/blocked
    us (status ``kicked``). We fire a typed event so the Manager Bot can
    notify the admin and the broadcast service can skip dead chats.
    """
    if event.chat.type != "private":
        return
    user_id = f"tg-{event.from_user.id}"
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    if old_status == new_status:
        return
    if new_status == "kicked":
        fire(
            "user_blocked_bot",
            {
                "user_id": user_id,
                "telegram_user_id": event.from_user.id,
                "username": event.from_user.username,
                "source": "builder_bot",
            },
        )
    elif new_status == "member" and old_status == "kicked":
        fire(
            "user_unblocked_bot",
            {
                "user_id": user_id,
                "telegram_user_id": event.from_user.id,
                "username": event.from_user.username,
                "source": "builder_bot",
            },
        )


# ─────────────── /broadcast (admin-only) ───────────────


@router.message(Command("broadcast"))
@throttle(5.0)
async def cmd_broadcast(message: Message) -> None:
    """Send a free-form message to every verified user. Admin-only."""
    lang = await _lang_for(message)
    user_id = tg_user_id(message)
    if not _is_admin(user_id):
        await message.answer(t("admin_only", lang))
        return

    # Strip the leading "/broadcast" command and keep the raw payload.
    text = message.text or ""
    body = text.partition(" ")[2].strip()
    if not body:
        await message.answer(t("broadcast_usage", lang), parse_mode="HTML")
        return

    # Collect every verified user that has a Telegram numeric id.
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                sa_select(User.id).where(User.phone_verified_at.is_not(None))
            )
        ).all()
    recipients: list[int] = []
    for (uid,) in rows:
        if uid and uid.startswith("tg-"):
            try:
                recipients.append(int(uid[3:]))
            except ValueError:
                continue

    if not recipients:
        await message.answer(t("broadcast_no_recipients", lang))
        return

    await message.answer(t("broadcast_started", lang, count=len(recipients)))
    result = await broadcast_text(bot, recipients, body, parse_mode="HTML")
    fire(
        "broadcast_completed",
        {
            "user_id": user_id,
            "sent": result.sent,
            "blocked": result.blocked,
            "failed": result.failed,
            "total": result.total,
        },
    )
    await message.answer(
        t(
            "broadcast_done",
            lang,
            sent=result.sent,
            blocked=result.blocked,
            failed=result.failed,
        )
    )


# ─────────────── Main message handler ───────────────


@router.message(F.text)
async def on_message(message: Message) -> None:
    """Run a single agent turn for the user's free-form text message."""
    lang = await _lang_for(message)
    # Phase 0 gate: phone verification before any agent turn.
    if not await _ensure_verified(message, lang):
        return

    user_id = tg_user_id(message)
    is_admin = _is_admin(user_id)

    # Pre-flight balance check (admins exempt).
    if not is_admin:
        balance = await get_balance(user_id)
        if balance < MIN_BALANCE:
            await message.answer(t("agent_no_balance", lang))
            return

    # Per-user serialization to keep the agent's session consistent.
    async with _user_locks[user_id]:
        placeholder = await message.answer(t("agent_thinking", lang))
        progress_state = {"last_edit": 0.0, "lines": []}

        async def on_progress(line: str) -> None:
            progress_state["lines"].append(line)
            now = time.time()
            if now - progress_state["last_edit"] < 1.5:
                return
            preview_lines = progress_state["lines"][-6:]
            preview = "\n".join(_truncate(line_, 200) for line_ in preview_lines)
            preview = preview[: MAX_REPLY_LEN - 50]
            try:
                await placeholder.edit_text(f"⏳\n{preview}")
                progress_state["last_edit"] = now
            except TelegramBadRequest:
                pass  # message unchanged or too-old; ignore

        try:
            result = await agent.run_turn(user_id, message.text, on_progress=on_progress)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent turn failed for %s", user_id)
            text = t("agent_error", lang, kind=type(exc).__name__, detail=str(exc))
            try:
                await placeholder.edit_text(text)
            except TelegramBadRequest:
                await message.answer(text)
            return

        # Billing.
        crystal_cost = 0
        new_balance: int | None = None
        if not is_admin:
            crystal_cost = crystals_for(result.total_tokens)
            new_balance = await charge(user_id, crystal_cost)
            fire(
                "builder_turn_billed",
                {
                    "user_id": user_id,
                    "tokens": result.total_tokens,
                    "crystals": crystal_cost,
                    "balance": new_balance,
                },
            )

        # Replace the placeholder with the final reply (chunked if long).
        chunks = chunk_text(result.reply)
        try:
            await placeholder.edit_text(chunks[0])
        except TelegramBadRequest:
            await message.answer(chunks[0])
        for extra in chunks[1:]:
            await message.answer(extra)

        # Footer with stats + billing line in user's language.
        footer_parts = [
            f"🔁 {result.iterations}",
            f"🛠 {result.tool_calls}",
            f"🧮 {result.total_tokens}",
        ]
        if is_admin:
            footer_parts.append(t("footer_admin", lang))
        else:
            footer_parts.append(t("footer_billed", lang, cost=crystal_cost, balance=new_balance))
        await message.answer("· " + "  ·  ".join(footer_parts))


def _truncate(s: str, n: int) -> str:
    """Shorten *s* to at most *n* chars and collapse newlines."""
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


# ─────────────── Entrypoint ───────────────


async def main() -> None:
    """Start long-polling Telegram for messages."""
    dp = Dispatcher()

    # Middlewares run outer→inner, so:
    #   1. Throttling drops abusive events first (cheapest possible reject).
    #   2. The error router catches anything the handlers raise and emits
    #      a ``bot_error`` event so admins see the trace in real time.
    dp.message.middleware(ThrottlingMiddleware(default_rate=0.3))
    dp.callback_query.middleware(ThrottlingMiddleware(default_rate=0.3))
    dp.include_router(build_error_router(bot_label="builder_bot"))
    dp.include_router(router)

    log.info(
        "Builder Bot starting (admin=%s, rate=%s tok/crystal, phone_gate=%s, "
        "default_lang=%s, supported=%s)",
        ADMIN_USER_ID or "none",
        TOKENS_PER_CRYSTAL,
        settings.REQUIRE_PHONE_VERIFICATION,
        DEFAULT_LANG,
        ",".join(LANGUAGES),
    )
    await dp.start_polling(bot, handle_signals=False)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
