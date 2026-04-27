"""ZeroBot Manager Bot — admin control plane over Telegram.

Runs as a standalone first-party process (not planted via the platform).
Polls Telegram for admin commands AND exposes an HTTP ``/events`` endpoint
that the platform pushes notifications to.

Required env:
    MANAGER_BOT_TOKEN      Telegram token for this bot
    MANAGER_ADMIN_CHAT_ID  Your Telegram chat id (admin only)
    ADMIN_TOKEN            Shared secret for the admin console
Optional env:
    ADMIN_CONSOLE_URL      Default ``http://127.0.0.1:8002``
    USER_CONSOLE_URL       Default ``http://127.0.0.1:8000``
    MANAGER_EVENT_PORT     Default ``8003``
"""

import asyncio
import json
import logging
import os
import sys

import httpx
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.types import Message
from aiohttp import web

from zerobot.events.publisher import SIGNATURE_HEADER, verify_signature

log = logging.getLogger(__name__)

# ─────────────── Config ───────────────

BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN", "").strip()
ADMIN_CHAT_ID_RAW = os.getenv("MANAGER_ADMIN_CHAT_ID", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
EVENT_SHARED_SECRET = os.getenv("EVENT_SHARED_SECRET", "").strip()
ADMIN_CONSOLE_URL = os.getenv("ADMIN_CONSOLE_URL", "http://127.0.0.1:8002")
USER_CONSOLE_URL = os.getenv("USER_CONSOLE_URL", "http://127.0.0.1:8000")
EVENT_PORT = int(os.getenv("MANAGER_EVENT_PORT", "8003"))

if not BOT_TOKEN:
    print("❌ MANAGER_BOT_TOKEN is required", file=sys.stderr)
    sys.exit(1)
if not ADMIN_CHAT_ID_RAW:
    print("❌ MANAGER_ADMIN_CHAT_ID is required", file=sys.stderr)
    sys.exit(1)
if not ADMIN_TOKEN:
    print("❌ ADMIN_TOKEN is required (must match admin_console)", file=sys.stderr)
    sys.exit(1)

ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)


# ─────────────── HTTP clients ───────────────

admin_http = httpx.AsyncClient(
    base_url=ADMIN_CONSOLE_URL,
    headers={"X-Admin-Token": ADMIN_TOKEN},
    timeout=10.0,
)
user_http = httpx.AsyncClient(base_url=USER_CONSOLE_URL, timeout=10.0)


# ─────────────── Bot & router ───────────────

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)


class AdminFilter(BaseFilter):
    """Allow only the configured admin chat to invoke commands."""

    async def __call__(self, message: Message) -> bool:
        return message.chat.id == ADMIN_CHAT_ID


admin_only = AdminFilter()


# ─────────────── Helpers ───────────────

FOOTER = "\n\n<i>Powered by @iLildev</i>"


def _split_args(command: CommandObject, n: int) -> list[str] | None:
    """Split the command's args into exactly *n* whitespace-separated parts."""
    if not command.args:
        return None
    parts = command.args.split(maxsplit=n - 1)
    if len(parts) != n:
        return None
    return parts


async def _api_error_text(r: httpx.Response) -> str:
    """Render a non-2xx response into a Telegram-friendly error message."""
    try:
        return f"❌ {r.status_code}: <code>{r.json().get('detail', r.text)}</code>"
    except Exception:
        return f"❌ {r.status_code}: <code>{r.text}</code>"


# ─────────────── Commands ───────────────


@router.message(CommandStart(), admin_only)
async def cmd_start(m: Message):
    """Show the admin command menu."""
    await m.answer(
        "👑 <b>ZeroBot Manager</b>\n\n"
        "<b>System:</b>\n"
        "/stats — system overview\n"
        "/ports — port registry summary\n\n"
        "<b>Users:</b>\n"
        "/users — list users\n"
        "/user <code>&lt;id&gt;</code> — user details\n"
        "/grant <code>&lt;user&gt; &lt;amt&gt;</code>\n"
        "/deduct <code>&lt;user&gt; &lt;amt&gt;</code>\n"
        "/promote <code>&lt;user&gt;</code> · /demote <code>&lt;user&gt;</code>\n\n"
        "<b>Identity:</b>\n"
        "/identity <code>&lt;user&gt;</code> — verification + quota status\n"
        "/unverify <code>&lt;user&gt;</code> — clear phone\n"
        "/unlink_session <code>&lt;user&gt;</code> — revoke MTProto link\n"
        "/setquota <code>&lt;user&gt; &lt;n&gt;</code> — override bot quota\n\n"
        "<b>Bots:</b>\n"
        "/bots — list all bots\n"
        "/bot <code>&lt;id&gt;</code> — bot details\n"
        "/wake <code>&lt;bot&gt;</code> · /hibernate <code>&lt;bot&gt;</code> · "
        "/restart <code>&lt;bot&gt;</code>\n\n"
        "<b>Official:</b>\n"
        "/official — list official bots" + FOOTER
    )


@router.message(Command("stats"), admin_only)
async def cmd_stats(m: Message):
    """Show platform-wide counters."""
    r = await admin_http.get("/admin/stats")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    s = r.json()
    await m.answer(
        f"📊 <b>System Stats</b>\n\n"
        f"👥 Users: <b>{s['users_total']}</b>\n"
        f"🤖 Bots: <b>{s['bots_total']}</b> "
        f"(active {s['bots_active']}, hibernated {s['bots_hibernated']}, "
        f"official {s['bots_official']})\n"
        f"🔌 Ports: <b>{s['ports_used']}</b>/{s['ports_total']} used "
        f"(free {s['ports_free']}, cooldown {s['ports_cooldown']})\n"
        f"💎 Crystals in circulation: <b>{s['crystals_in_circulation']}</b>" + FOOTER
    )


@router.message(Command("ports"), admin_only)
async def cmd_ports(m: Message):
    """Show only the port-registry summary."""
    r = await admin_http.get("/admin/stats")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    s = r.json()
    await m.answer(
        f"🔌 <b>Port Registry</b>\n\n"
        f"Total: {s['ports_total']}\n"
        f"Used: {s['ports_used']}\n"
        f"Free: {s['ports_free']}\n"
        f"Cooldown: {s['ports_cooldown']}" + FOOTER
    )


@router.message(Command("users"), admin_only)
async def cmd_users(m: Message):
    """List the first 30 users with their bot counts."""
    r = await admin_http.get("/admin/users")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    users = r.json()
    if not users:
        await m.answer("No users yet" + FOOTER)
        return

    lines = ["👥 <b>Users</b> (" + str(len(users)) + ")\n"]
    for u in users[:30]:
        admin_tag = " 👑" if u["is_admin"] else ""
        lines.append(
            f"• <code>{u['id']}</code>{admin_tag} — {u['bot_count']} bots · {u['balance']} 💎"
        )
    if len(users) > 30:
        lines.append(f"\n…and {len(users) - 30} more")
    await m.answer("\n".join(lines) + FOOTER)


@router.message(Command("user"), admin_only)
async def cmd_user(m: Message, command: CommandObject):
    """Show full details for one user (incl. identity status)."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/user &lt;user_id&gt;</code>")
        return

    user_id = args[0]
    r = await admin_http.get(f"/admin/users/{user_id}")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    u = r.json()
    bots_text = (
        "\n".join(
            f"  • <code>{b['id']}</code> — "
            f"{'🟢 active' if b['is_active'] else '😴 hibernated'}"
            f"{' 👑' if b['is_official'] else ''}"
            for b in u["bots"]
        )
        or "  (no bots)"
    )

    phone_status = "✅" if u.get("phone_verified") else "❌"
    session_status = "🔗" if u.get("telegram_session_linked") else "—"
    quota_text = u.get("bot_quota") if u.get("bot_quota") is not None else "default"

    await m.answer(
        f"👤 <b>User</b> <code>{u['id']}</code>{' 👑' if u['is_admin'] else ''}\n"
        f"💎 Balance: <b>{u['balance']}</b>\n"
        f"📱 Phone: {phone_status}  ·  🔌 MTProto: {session_status}  ·  "
        f"🎫 Quota: <b>{quota_text}</b>\n"
        f"📅 Created: {u['created_at']}\n\n"
        f"<b>Bots:</b>\n{bots_text}" + FOOTER
    )


# ─────────────── Identity admin commands (Phase 0) ───────────────


@router.message(Command("identity"), admin_only)
async def cmd_identity(m: Message, command: CommandObject):
    """Show identity / quota snapshot for a user."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/identity &lt;user_id&gt;</code>")
        return
    r = await admin_http.get(f"/admin/users/{args[0]}/identity")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    d = r.json()
    await m.answer(
        f"🆔 <b>Identity</b> <code>{d['user_id']}</code>\n"
        f"📱 Phone: {'✅ verified ' + (d.get('phone_verified_at') or '') if d['phone_verified'] else '❌ not verified'}\n"
        f"🔌 MTProto session: {'🔗 linked' if d['telegram_session_linked'] else '— not linked'}\n"
        f"🎫 Bots: <b>{d['bot_count']}</b> / {d['bot_quota']} "
        f"(remaining {d['bot_quota_remaining']})" + FOOTER
    )


@router.message(Command("unverify"), admin_only)
async def cmd_unverify(m: Message, command: CommandObject):
    """Force-clear a user's phone verification (admin override)."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/unverify &lt;user_id&gt;</code>")
        return
    r = await admin_http.post(f"/admin/users/{args[0]}/identity/unverify")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    d = r.json()
    if d.get("cleared"):
        await m.answer(f"🗑️ Phone unverified for <code>{args[0]}</code>" + FOOTER)
    else:
        await m.answer(f"ℹ️ <code>{args[0]}</code> had no phone on file" + FOOTER)


@router.message(Command("unlink_session"), admin_only)
async def cmd_unlink_session(m: Message, command: CommandObject):
    """Revoke a user's stored MTProto session (admin override)."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/unlink_session &lt;user_id&gt;</code>")
        return
    r = await admin_http.post(f"/admin/users/{args[0]}/identity/unlink_session")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    d = r.json()
    if d.get("revoked"):
        await m.answer(f"🔌 MTProto session revoked for <code>{args[0]}</code>" + FOOTER)
    else:
        await m.answer(f"ℹ️ <code>{args[0]}</code> had no active session" + FOOTER)


@router.message(Command("setquota"), admin_only)
async def cmd_setquota(m: Message, command: CommandObject):
    """Override the bot quota for a user."""
    args = _split_args(command, 2)
    if not args or not args[1].isdigit():
        await m.answer("Usage: <code>/setquota &lt;user_id&gt; &lt;n&gt;</code>")
        return
    user_id, quota = args[0], int(args[1])
    r = await admin_http.post(
        f"/admin/users/{user_id}/quota", json={"quota": quota}
    )
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    d = r.json()
    await m.answer(
        f"🎫 Quota set for <code>{user_id}</code> → "
        f"<b>{d['bot_count']}</b> / {d['bot_quota']}" + FOOTER
    )


@router.message(Command("grant"), admin_only)
async def cmd_grant(m: Message, command: CommandObject):
    """Grant crystals to a user."""
    args = _split_args(command, 2)
    if not args or not args[1].lstrip("-").isdigit():
        await m.answer("Usage: <code>/grant &lt;user_id&gt; &lt;amount&gt;</code>")
        return

    user_id, amount = args[0], int(args[1])
    r = await admin_http.post(f"/admin/users/{user_id}/wallet/grant", json={"amount": amount})
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    d = r.json()
    await m.answer(f"✅ <code>{user_id}</code> +{amount} 💎 → <b>{d['balance']}</b>" + FOOTER)


@router.message(Command("deduct"), admin_only)
async def cmd_deduct(m: Message, command: CommandObject):
    """Deduct crystals from a user."""
    args = _split_args(command, 2)
    if not args or not args[1].lstrip("-").isdigit():
        await m.answer("Usage: <code>/deduct &lt;user_id&gt; &lt;amount&gt;</code>")
        return

    user_id, amount = args[0], int(args[1])
    r = await admin_http.post(f"/admin/users/{user_id}/wallet/deduct", json={"amount": amount})
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    d = r.json()
    await m.answer(f"✅ <code>{user_id}</code> -{amount} 💎 → <b>{d['balance']}</b>" + FOOTER)


@router.message(Command("promote"), admin_only)
async def cmd_promote(m: Message, command: CommandObject):
    """Promote a user to admin."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/promote &lt;user_id&gt;</code>")
        return
    r = await admin_http.post(f"/admin/users/{args[0]}/promote")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    await m.answer(f"👑 <code>{args[0]}</code> promoted to admin" + FOOTER)


@router.message(Command("demote"), admin_only)
async def cmd_demote(m: Message, command: CommandObject):
    """Demote an admin back to a regular user."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/demote &lt;user_id&gt;</code>")
        return
    r = await admin_http.post(f"/admin/users/{args[0]}/demote")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    await m.answer(f"⬇️ <code>{args[0]}</code> demoted" + FOOTER)


@router.message(Command("bots"), admin_only)
async def cmd_bots(m: Message):
    """List the first 30 bots across the platform."""
    r = await admin_http.get("/admin/bots")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return

    bots = r.json()
    if not bots:
        await m.answer("No bots planted yet" + FOOTER)
        return

    lines = [f"🤖 <b>Bots</b> ({len(bots)})\n"]
    for b in bots[:30]:
        state = "🟢" if b["is_active"] else "😴"
        official = " 👑" if b["is_official"] else ""
        lines.append(
            f"{state} <code>{b['id']}</code>{official} — owner <code>{b['user_id']}</code>"
        )
    if len(bots) > 30:
        lines.append(f"\n…and {len(bots) - 30} more")
    await m.answer("\n".join(lines) + FOOTER)


@router.message(Command("bot"), admin_only)
async def cmd_bot(m: Message, command: CommandObject):
    """Show full details for one bot."""
    args = _split_args(command, 1)
    if not args:
        await m.answer("Usage: <code>/bot &lt;bot_id&gt;</code>")
        return
    r = await admin_http.get(f"/admin/bots/{args[0]}")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    b = r.json()
    await m.answer(
        f"🤖 <b>{b['name'] or b['id']}</b>{' 👑' if b['is_official'] else ''}\n"
        f"<code>{b['id']}</code>\n\n"
        f"Owner: <code>{b['user_id']}</code>\n"
        f"State: {'🟢 active' if b['is_active'] else '😴 hibernated'}\n"
        f"Port: {b['port'] if b['port'] is not None else '—'}\n"
        f"Created: {b['created_at']}\n"
        f"Description: {b['description'] or '—'}" + FOOTER
    )


async def _bot_action(m: Message, command: CommandObject, action: str, label: str):
    """Run a /wake | /hibernate | /restart command against the admin API."""
    args = _split_args(command, 1)
    if not args:
        await m.answer(f"Usage: <code>/{action} &lt;bot_id&gt;</code>")
        return
    r = await admin_http.post(f"/admin/bots/{args[0]}/{action}")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    b = r.json()
    await m.answer(
        f"{label} <code>{b['id']}</code> → "
        f"{'🟢 active' if b['is_active'] else '😴 hibernated'}" + FOOTER
    )


@router.message(Command("wake"), admin_only)
async def cmd_wake(m: Message, command: CommandObject):
    """Force-wake a hibernating bot."""
    await _bot_action(m, command, "wake", "⏰")


@router.message(Command("hibernate"), admin_only)
async def cmd_hibernate(m: Message, command: CommandObject):
    """Force-hibernate a running bot."""
    await _bot_action(m, command, "hibernate", "😴")


@router.message(Command("restart"), admin_only)
async def cmd_restart(m: Message, command: CommandObject):
    """Restart a bot (reap then wake)."""
    await _bot_action(m, command, "restart", "🔄")


@router.message(Command("official"), admin_only)
async def cmd_official(m: Message):
    """List official (developer-owned) bots."""
    r = await admin_http.get("/admin/official-bots")
    if r.status_code != 200:
        await m.answer(await _api_error_text(r))
        return
    bots = r.json()
    if not bots:
        await m.answer("No official bots yet" + FOOTER)
        return
    lines = [f"👑 <b>Official Bots</b> ({len(bots)})\n"]
    for b in bots:
        state = "🟢" if b["is_active"] else "😴"
        lines.append(f"{state} <code>{b['id']}</code> — {b['name'] or '—'}")
    await m.answer("\n".join(lines) + FOOTER)


# ─────────────── Event listener ───────────────


def _format_event(event: str, p: dict) -> str | None:
    """Render an event payload as a human-readable HTML snippet."""
    if event == "user_registered":
        return (
            f"🆕 <b>New user registered</b>\n"
            f"ID: <code>{p.get('user_id')}</code>\n"
            f"Source: {p.get('source', '?')}"
        )
    if event == "bot_created":
        return (
            f"🤖 <b>Bot planted</b>\n"
            f"Bot: <code>{p.get('bot_id')}</code>\n"
            f"Owner: <code>{p.get('user_id')}</code>"
        )
    if event == "official_bot_created":
        return (
            f"👑 <b>Official bot created</b>\n"
            f"Bot: <code>{p.get('bot_id')}</code>\n"
            f"Name: {p.get('name') or '—'}"
        )
    if event == "bot_deleted":
        return f"🗑️ Bot deleted: <code>{p.get('bot_id')}</code>"
    if event == "user_deleted":
        return (
            f"🗑️ User deleted: <code>{p.get('user_id')}</code> "
            f"({p.get('bots_removed', 0)} bots removed)"
        )
    if event == "wallet_grant":
        return (
            f"💎+ <b>Granted</b> {p.get('amount')} to "
            f"<code>{p.get('user_id')}</code> → balance <b>{p.get('balance')}</b>"
        )
    if event == "wallet_deduct":
        return (
            f"💎- <b>Deducted</b> {p.get('amount')} from "
            f"<code>{p.get('user_id')}</code> → balance <b>{p.get('balance')}</b>"
        )
    if event == "wallet_topup":
        return (
            f"💎 <b>User topup</b> <code>{p.get('user_id')}</code> "
            f"+{p.get('amount')} → balance <b>{p.get('balance')}</b>"
        )
    if event == "bot_state_changed":
        return f"⚙️ Bot <code>{p.get('bot_id')}</code> {p.get('action', 'changed')}"
    return f"📬 <b>{event}</b>\n<code>{p}</code>"


async def handle_event(request: web.Request) -> web.Response:
    """Receive an event from the platform and forward it to the admin chat.

    When ``EVENT_SHARED_SECRET`` is configured, every request must carry a
    valid HMAC-SHA256 signature in the ``X-ZeroBot-Signature`` header
    (``sha256=<hex>``). Unsigned requests are rejected with 401.
    """
    body = await request.read()

    if EVENT_SHARED_SECRET:
        sig = request.headers.get(SIGNATURE_HEADER, "")
        if not verify_signature(EVENT_SHARED_SECRET, body, sig):
            log.warning("rejected event from %s: bad signature", request.remote)
            return web.json_response({"ok": False, "error": "bad signature"}, status=401)

    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    event = data.get("event", "")
    payload = data.get("payload", {}) or {}

    text = _format_event(event, payload)
    if text:
        try:
            await bot.send_message(ADMIN_CHAT_ID, text + FOOTER)
        except Exception as e:
            print(f"⚠️  Failed to notify admin: {e}", file=sys.stderr)

    return web.json_response({"ok": True})


async def start_event_server() -> None:
    """Start the small aiohttp server that receives platform events."""
    app = web.Application()
    app.router.add_post("/events", handle_event)
    app.router.add_get("/healthz", lambda _: web.json_response({"ok": True}))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", EVENT_PORT)
    await site.start()
    print(f"📡 Event listener on http://0.0.0.0:{EVENT_PORT}/events")


# ─────────────── Main ───────────────


async def main() -> None:
    """Start the event listener and begin polling Telegram."""
    await start_event_server()

    try:
        await bot.send_message(
            ADMIN_CHAT_ID,
            "🚀 <b>ZeroBot Manager online</b>\nSend /start for the menu." + FOOTER,
        )
    except Exception as e:
        print(f"⚠️  Could not message admin chat on startup: {e}", file=sys.stderr)

    print("🤖 Manager bot polling Telegram…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
