"""ZeroBot Builder Bot — autonomous coding agent over Telegram.

Wraps :class:`zerobot.agents.builder_agent.BuilderAgent` in an aiogram
polling bot. Each Telegram message becomes one agent turn; tool calls and
intermediate text are streamed back by editing a placeholder reply
in-place. After the turn completes, crystals are deducted from the user's
wallet (the platform admin defined by ``ADMIN_USER_ID`` is exempt).

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
from aiogram.types import Message

from zerobot.agents.builder_agent import BuilderAgent
from zerobot.database.engine import AsyncSessionLocal
from zerobot.database.wallet import WalletService
from zerobot.events.publisher import fire

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
    is_admin = user_id == ADMIN_USER_ID
    balance = await get_balance(user_id)
    role = "👑 المالك" if is_admin else "مستخدم"
    await message.answer(
        "🤖 <b>Builder Agent</b> — مساعدك للبرمجة المستقلّة\n\n"
        f"الدور: {role}\n"
        f"الرصيد: <b>{balance}</b> كرستالة\n"
        f"التكلفة: 1 كرستالة لكل {TOKENS_PER_CRYSTAL} توكن"
        + (" (معفى)" if is_admin else "")
        + "\n\n"
        "اكتب طلبك مباشرة وسأبني/أعدّل/أصحّح بنفسي داخل sandbox خاص بك.\n\n"
        "<b>أوامر:</b>\n"
        "/balance — رصيدك الحالي\n"
        "/reset — مسح الذاكرة + sandbox\n"
        "/stats — إحصائيات جلستك\n\n"
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


# ─────────────── Main message handler ───────────────


@router.message(F.text)
async def on_message(message: Message) -> None:
    """Run a single agent turn for the user's free-form text message."""
    user_id = tg_user_id(message)
    is_admin = user_id == ADMIN_USER_ID

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
        "Builder Bot starting (admin=%s, rate=%s tok/crystal)",
        ADMIN_USER_ID or "none",
        TOKENS_PER_CRYSTAL,
    )
    await dp.start_polling(bot, handle_signals=False)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
