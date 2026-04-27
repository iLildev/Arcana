"""ZeroBot Builder Bot — autonomous coding agent over Telegram.

Wraps :class:`zerobot.agents.builder_agent.BuilderAgent` in an aiogram
polling bot. Each Telegram message becomes one agent turn; tool calls and
intermediate text are streamed back by editing a placeholder reply
in-place. After the turn completes, crystals are deducted from the user's
wallet (the platform admin defined by ``ADMIN_USER_ID`` is exempt).

Phase 0: every non-admin user must verify their phone number (via
Telegram's request_contact button) before the agent will run. A user can
clear their data at any time with /unlink_phone.

Required env:
    BUILDER_BOT_TOKEN          Telegram bot token (from BotFather)
Optional env (with defaults):
    ADMIN_USER_ID              Exempt from crystal billing (default "")
    BUILDER_TOKENS_PER_CRYSTAL Billing rate (default 5000)
    BUILDER_MIN_BALANCE        Refuse new turns below this (default 1)
    BUILDER_MAX_REPLY_LEN      Split outbound messages above this (default 3800)

Run from the project root::

    python -m zerobot.bots.builder_bot.main
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
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy import select as sa_select

from zerobot.agents.builder_agent import BuilderAgent
from zerobot.botfather import (
    BotFatherError,
    fetch_bot_profile,
    update_bot_profile,
)
from zerobot.config import settings
from zerobot.database.engine import AsyncSessionLocal
from zerobot.database.models import Bot as BotModel
from zerobot.database.wallet import WalletService
from zerobot.events.publisher import fire
from zerobot.identity import (
    PhoneError,
    is_phone_verified,
    record_phone_verification,
    unlink_phone,
)

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


def tg_user_id(message: Message) -> str:
    """Map a Telegram user id to the canonical ZeroBot user id."""
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


# ─────────────── Identity gate ───────────────

# Reply-keyboard offering the contact-share button. Telegram guarantees
# that a Contact produced by request_contact is the user's own verified
# phone number — it cannot be spoofed.
_CONTACT_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 شارك رقمي للتحقق", request_contact=True)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


async def _prompt_phone_share(message: Message) -> None:
    """Ask the user to share their phone via Telegram's contact button."""
    await message.answer(
        "🔒 <b>تحقّق سريع قبل البدء</b>\n\n"
        "قبل استخدام Builder Agent، يرجى التحقّق من حسابك عبر مشاركة رقمك من Telegram.\n\n"
        "<b>لماذا؟</b>\n"
        "• حماية المنصّة من السبام والحسابات الوهمية\n"
        "• حدّ عادل للموارد لكل مستخدم\n"
        "• تمكين إدارة بوتاتك لاحقاً عبر BotFather آلياً\n\n"
        "اضغط الزرّ بالأسفل. يمكنك حذف بياناتك في أي وقت بالأمر /unlink_phone",
        parse_mode="HTML",
        reply_markup=_CONTACT_KB,
    )


def _is_admin(user_id: str) -> bool:
    """Phone gate is bypassed for the platform admin."""
    return bool(ADMIN_USER_ID) and user_id == ADMIN_USER_ID


async def _ensure_verified(message: Message) -> bool:
    """Return True iff the user has a verified phone (admin always passes).

    On a verification miss, sends the contact-share prompt and returns False
    so the caller can short-circuit cleanly.
    """
    user_id = tg_user_id(message)
    if _is_admin(user_id) or not settings.REQUIRE_PHONE_VERIFICATION:
        return True
    async with AsyncSessionLocal() as session:
        verified = await is_phone_verified(session, user_id)
    if not verified:
        await _prompt_phone_share(message)
        return False
    return True


# ─────────────── Wallet helpers ───────────────


async def get_balance(user_id: str) -> int:
    """Fetch the current crystal balance for *user_id*."""
    async with AsyncSessionLocal() as session:
        wallet = await WalletService(session).get_wallet(user_id)
        return wallet.balance


async def charge(user_id: str, amount: int) -> int:
    """Deduct *amount* crystals; returns new balance. Caps at zero on shortfall."""
    async with AsyncSessionLocal() as session:
        service = WalletService(session)
        wallet = await service.get_wallet(user_id)
        deducted = min(amount, wallet.balance)
        wallet.balance -= deducted
        await session.commit()
        return wallet.balance


def crystals_for(tokens: int) -> int:
    """Convert raw tokens to crystals using ``TOKENS_PER_CRYSTAL`` (min 1)."""
    return max(1, tokens // TOKENS_PER_CRYSTAL)


# ─────────────── Commands ───────────────


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Show the welcome screen with role, balance, and command list."""
    user_id = tg_user_id(message)
    is_admin = _is_admin(user_id)
    balance = await get_balance(user_id)
    async with AsyncSessionLocal() as session:
        verified = await is_phone_verified(session, user_id)

    role = "👑 المالك" if is_admin else "مستخدم"
    verified_line = (
        "✅ رقمك موثّق"
        if verified or is_admin
        else "🔒 لم يتم التحقّق بعد — أرسل أي رسالة لبدء التحقّق"
    )
    await message.answer(
        "🤖 <b>Builder Agent</b> — مساعدك للبرمجة المستقلّة\n\n"
        f"الدور: {role}\n"
        f"الحالة: {verified_line}\n"
        f"الرصيد: <b>{balance}</b> كرستالة\n"
        f"التكلفة: 1 كرستالة لكل {TOKENS_PER_CRYSTAL} توكن"
        + (" (معفى)" if is_admin else "")
        + "\n\n"
        "اكتب طلبك مباشرة وسأبني/أعدّل/أصحّح بنفسي داخل sandbox خاص بك.\n\n"
        "<b>أوامر:</b>\n"
        "/balance — رصيدك الحالي\n"
        "/reset — مسح الذاكرة + sandbox\n"
        "/stats — إحصائيات جلستك\n"
        "/unlink_phone — حذف رقمك من المنصّة\n\n"
        "<i>Powered by @iLildev</i>",
        parse_mode="HTML",
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    """Reply with the user's current crystal balance."""
    user_id = tg_user_id(message)
    balance = await get_balance(user_id)
    await message.answer(f"💎 رصيدك: <b>{balance}</b> كرستالة", parse_mode="HTML")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Wipe the user's workspace and conversation history."""
    user_id = tg_user_id(message)
    agent.reset(user_id)
    await message.answer("🧹 تمّ مسح الذاكرة وتفريغ مساحة العمل.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show quick session stats (turns, tokens, equivalent crystals)."""
    user_id = tg_user_id(message)
    session = agent.sessions.get(user_id)
    turns = sum(1 for m in session.messages if m["role"] == "user")
    await message.answer(
        f"📊 جلستك:\n"
        f"  الأدوار: {turns}\n"
        f"  Tokens: {session.total_input_tokens} input + "
        f"{session.total_output_tokens} output\n"
        f"  مكافئ: ~{crystals_for(session.total_input_tokens + session.total_output_tokens)} كرستالة"
    )


# ─────────────── BotFather automation (Phase 1.ج) ───────────────


def _split_args(message: Message, *, expected: int) -> list[str] | None:
    """Return the command arguments, or None if the wrong number was supplied."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=expected)
    return parts[1:] if len(parts) > expected else None


async def _resolve_my_bot(user_id: str, bot_id: str) -> BotModel | None:
    """Return the bot iff *user_id* owns it."""
    async with AsyncSessionLocal() as session:
        bot = await session.get(BotModel, bot_id)
    return bot if bot and bot.user_id == user_id else None


@router.message(Command("mybots"))
async def cmd_mybots(message: Message) -> None:
    """List the bots owned by the caller."""
    if not await _ensure_verified(message):
        return
    user_id = tg_user_id(message)
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                sa_select(BotModel).where(BotModel.user_id == user_id)
            )
        ).scalars().all()
    if not rows:
        await message.answer(
            "📭 لا توجد بوتات بعد. استخدم Builder Agent لإنشاء أوّل بوت."
        )
        return
    lines = ["🤖 <b>بوتاتك:</b>", ""]
    for b in rows:
        status = "🟢" if b.is_active else ("💤" if b.is_hibernated else "⚪️")
        lines.append(f"{status} <code>{b.id}</code> — {b.name or '(بلا اسم)'}")
    lines += ["", "أوامر الإدارة: /profile · /setname · /setdesc · /setabout"]
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    """Show a bot's live profile (name, descriptions, commands)."""
    if not await _ensure_verified(message):
        return
    args = _split_args(message, expected=1)
    if not args:
        await message.answer("الاستخدام: <code>/profile &lt;bot_id&gt;</code>", parse_mode="HTML")
        return
    user_id = tg_user_id(message)
    bot_id = args[0]
    async with AsyncSessionLocal() as session:
        try:
            profile = await fetch_bot_profile(session, user_id, bot_id)
        except BotFatherError as exc:
            await message.answer(f"❌ تعذّر القراءة: {exc}")
            return
    cmds = "\n".join(f"  /{c.command} — {c.description}" for c in profile.commands) or "  (لا يوجد)"
    await message.answer(
        f"🪪 <b>@{profile.username or '?'}</b>\n"
        f"الاسم: {profile.name or '(فارغ)'}\n"
        f"About: {profile.short_description or '(فارغ)'}\n"
        f"الوصف: {profile.description or '(فارغ)'}\n"
        f"الأوامر:\n{cmds}",
        parse_mode="HTML",
    )


async def _apply_profile_update(
    message: Message, bot_id: str, **fields
) -> None:
    """Shared helper for /setname, /setdesc, /setabout."""
    user_id = tg_user_id(message)
    if await _resolve_my_bot(user_id, bot_id) is None:
        await message.answer("❌ لم أجد هذا البوت ضمن بوتاتك.")
        return
    async with AsyncSessionLocal() as session:
        try:
            results = await update_bot_profile(session, user_id, bot_id, **fields)
        except BotFatherError as exc:
            await message.answer(f"❌ {exc}")
            return
    line = next(iter(results.values()), "no-op")
    if line == "ok":
        await message.answer("✅ تم.")
    else:
        await message.answer(f"⚠️ {line}")


@router.message(Command("setname"))
async def cmd_setname(message: Message) -> None:
    """Rename a bot. Usage: /setname <bot_id> <new name…>"""
    if not await _ensure_verified(message):
        return
    args = _split_args(message, expected=2)
    if not args or len(args) < 2 or not args[1].strip():
        await message.answer(
            "الاستخدام: <code>/setname &lt;bot_id&gt; &lt;الاسم الجديد&gt;</code>",
            parse_mode="HTML",
        )
        return
    await _apply_profile_update(message, args[0], name=args[1].strip())


@router.message(Command("setdesc"))
async def cmd_setdesc(message: Message) -> None:
    """Update the long description. Usage: /setdesc <bot_id> <description…>"""
    if not await _ensure_verified(message):
        return
    args = _split_args(message, expected=2)
    if not args or len(args) < 2 or not args[1].strip():
        await message.answer(
            "الاستخدام: <code>/setdesc &lt;bot_id&gt; &lt;الوصف&gt;</code>",
            parse_mode="HTML",
        )
        return
    await _apply_profile_update(message, args[0], description=args[1].strip())


@router.message(Command("setabout"))
async def cmd_setabout(message: Message) -> None:
    """Update the short "about" line (≤120 chars). Usage: /setabout <bot_id> <text…>"""
    if not await _ensure_verified(message):
        return
    args = _split_args(message, expected=2)
    if not args or len(args) < 2 or not args[1].strip():
        await message.answer(
            "الاستخدام: <code>/setabout &lt;bot_id&gt; &lt;النصّ&gt;</code>",
            parse_mode="HTML",
        )
        return
    await _apply_profile_update(message, args[0], short_description=args[1].strip())


@router.message(Command("unlink_phone"))
async def cmd_unlink_phone(message: Message) -> None:
    """Wipe the user's verified phone (GDPR-style "delete my data")."""
    user_id = tg_user_id(message)
    async with AsyncSessionLocal() as session:
        cleared = await unlink_phone(session, user_id, source="user_command")
    if cleared:
        fire("phone_unlinked", {"user_id": user_id})
        await message.answer(
            "🗑️ تم حذف رقمك من المنصّة. ستحتاج إلى التحقّق مجدّداً قبل الاستخدام المتقدّم.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer("ℹ️ لا يوجد رقم مسجّل لحسابك.")


# ─────────────── Contact handler ───────────────


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    """Handle the contact-share that completes phone verification."""
    contact = message.contact
    # Telegram's request_contact button always returns the sender's own
    # contact, with `user_id` set. Reject manually-forwarded cards.
    if contact is None or contact.user_id != message.from_user.id:
        await message.answer(
            "⚠️ يجب مشاركة رقمك أنت، لا رقم شخص آخر. "
            "اضغط زرّ المشاركة بدلاً من إرسال جهة اتصال يدوياً."
        )
        return

    user_id = tg_user_id(message)
    try:
        async with AsyncSessionLocal() as session:
            await record_phone_verification(
                session,
                user_id,
                contact.phone_number,
                source="telegram_contact",
                ip_hash=None,
            )
    except PhoneError as exc:
        await message.answer(
            f"❌ تعذّر التحقّق: {exc}\n\nإن كنت قد سجّلت بحساب آخر، استخدم /unlink_phone هناك أوّلاً."
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("phone verification failed for %s", user_id)
        await message.answer(f"❌ خطأ داخلي أثناء التحقّق: {type(exc).__name__}")
        return

    fire("phone_verified", {"user_id": user_id, "source": "builder_bot"})
    await message.answer(
        "✅ <b>تم التحقّق بنجاح</b>\n\n"
        "يمكنك الآن استخدام Builder Agent. أرسل طلبك متى شئت.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


# ─────────────── Main message handler ───────────────


@router.message(F.text)
async def on_message(message: Message) -> None:
    """Run a single agent turn for the user's free-form text message."""
    # Phase 0 gate: phone verification before any agent turn.
    if not await _ensure_verified(message):
        return

    user_id = tg_user_id(message)
    is_admin = _is_admin(user_id)

    # Pre-flight balance check (admins exempt).
    if not is_admin:
        balance = await get_balance(user_id)
        if balance < MIN_BALANCE:
            await message.answer("🚫 لا يوجد رصيد كافٍ. اشحن محفظتك ثم أعد المحاولة.")
            return

    # Per-user serialization to keep the agent's session consistent.
    async with _user_locks[user_id]:
        placeholder = await message.answer("🤖 يفكّر…")
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
            try:
                await placeholder.edit_text(f"❌ خطأ: {type(exc).__name__}: {exc}")
            except TelegramBadRequest:
                await message.answer(f"❌ خطأ: {type(exc).__name__}: {exc}")
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

        # Footer with stats.
        footer_parts = [
            f"🔁 {result.iterations} iter",
            f"🛠 {result.tool_calls} tools",
            f"🧮 {result.total_tokens} tokens",
        ]
        if not is_admin:
            footer_parts.append(f"💎 -{crystal_cost} (متبقي {new_balance})")
        else:
            footer_parts.append("👑 معفى")
        await message.answer("· " + "  ·  ".join(footer_parts))


def _truncate(s: str, n: int) -> str:
    """Shorten *s* to at most *n* chars and collapse newlines."""
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


# ─────────────── Entrypoint ───────────────


async def main() -> None:
    """Start long-polling Telegram for messages."""
    dp = Dispatcher()
    dp.include_router(router)
    log.info(
        "Builder Bot starting (admin=%s, rate=%s tok/crystal, phone_gate=%s)",
        ADMIN_USER_ID or "none",
        TOKENS_PER_CRYSTAL,
        settings.REQUIRE_PHONE_VERIFICATION,
    )
    await dp.start_polling(bot, handle_signals=False)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
