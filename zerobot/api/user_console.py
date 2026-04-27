"""End-user FastAPI service: wallet top-ups and bot CRUD.

Mounted at the public user-facing URL. No authentication is enforced at
this layer — callers identify themselves via ``user_id`` path params and
the service trusts the layer in front of it (e.g. the Telegram bot) to
have authenticated the user.
"""

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.botfather import (
    BotCommand as BFCommand,
)
from zerobot.botfather import (
    BotFatherError,
    fetch_bot_profile,
    update_bot_profile,
)
from zerobot.config import settings
from zerobot.core.orchestrator import Orchestrator
from zerobot.database.engine import async_session_maker
from zerobot.database.models import Bot, User
from zerobot.database.wallet import WalletService
from zerobot.events.publisher import fire
from zerobot.identity import check_bot_quota, is_phone_verified

app = FastAPI(title="ZeroBot User Console")


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields a single ``AsyncSession``."""
    async with async_session_maker() as session:
        yield session


# ─────────────── Schemas ───────────────


class BotOut(BaseModel):
    """Public shape of a bot record returned by the API."""

    id: str
    user_id: str
    is_active: bool
    is_hibernated: bool
    port: int | None


class WalletOut(BaseModel):
    """Public wallet shape."""

    user_id: str
    balance: int


class CreateBotIn(BaseModel):
    """Request body for ``POST /users/{user_id}/bots``."""

    bot_id: str
    token: str


class TopupIn(BaseModel):
    """Request body for wallet top-ups."""

    amount: int


def _bot_out(bot: Bot) -> BotOut:
    """Project an ORM ``Bot`` to the public ``BotOut`` schema."""
    return BotOut(
        id=bot.id,
        user_id=bot.user_id,
        is_active=bot.is_active,
        is_hibernated=bot.is_hibernated,
        port=bot.port,
    )


# ─────────────── Health ───────────────


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness + readiness probe.

    Probes the database with a trivial ``SELECT 1``. Returns HTTP 503 when
    the database is unreachable so an upstream load balancer can drop the
    instance from rotation.
    """
    from sqlalchemy import text  # local import keeps module top clean

    db_ok = True
    db_error: str | None = None
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = f"{type(exc).__name__}: {exc}"

    body: dict = {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
    }
    if db_error:
        body["error"] = db_error
        raise HTTPException(status_code=503, detail=body)
    return body


# ─────────────── Wallet ───────────────


@app.get("/users/{user_id}/wallet", response_model=WalletOut)
async def get_wallet(user_id: str, session: AsyncSession = Depends(get_session)):
    """Return *user_id*'s wallet, auto-creating the user on first access."""
    user = await session.get(User, user_id)
    if not user:
        session.add(User(id=user_id))
        await session.commit()
        fire("user_registered", {"user_id": user_id, "source": "wallet"})

    wallet = await WalletService(session).get_wallet(user_id)
    return WalletOut(user_id=wallet.user_id, balance=wallet.balance)


@app.post("/users/{user_id}/wallet/topup", response_model=WalletOut)
async def topup_wallet(
    user_id: str,
    body: TopupIn,
    session: AsyncSession = Depends(get_session),
):
    """Add crystals to *user_id*'s wallet (positive amounts only)."""
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")

    user = await session.get(User, user_id)
    if not user:
        session.add(User(id=user_id))
        await session.commit()
        fire("user_registered", {"user_id": user_id, "source": "topup"})

    service = WalletService(session)
    await service.add(user_id, body.amount)
    wallet = await service.get_wallet(user_id)
    fire(
        "wallet_topup",
        {"user_id": user_id, "amount": body.amount, "balance": wallet.balance},
    )
    return WalletOut(user_id=wallet.user_id, balance=wallet.balance)


# ─────────────── Bots ───────────────


@app.get("/users/{user_id}/bots", response_model=list[BotOut])
async def list_user_bots(user_id: str, session: AsyncSession = Depends(get_session)):
    """Return every bot owned by *user_id*."""
    result = await session.execute(select(Bot).where(Bot.user_id == user_id))
    return [_bot_out(b) for b in result.scalars().all()]


@app.post("/users/{user_id}/bots", response_model=BotOut, status_code=201)
async def create_bot(
    user_id: str,
    body: CreateBotIn,
    session: AsyncSession = Depends(get_session),
):
    """Plant a new bot for *user_id*. Charges 1 crystal on success.

    Phase 0 enforces:
    - the user must have a verified phone (unless admin or
      ``REQUIRE_PHONE_VERIFICATION`` is disabled);
    - the user must be under their per-user bot quota.
    """
    user = await session.get(User, user_id)
    if not user:
        session.add(User(id=user_id))
        await session.commit()
        fire("user_registered", {"user_id": user_id, "source": "create_bot"})
        user = await session.get(User, user_id)

    # ── Phase 0 gates ────────────────────────────────────────────────────
    if (
        settings.REQUIRE_PHONE_VERIFICATION
        and not (user and user.is_admin)
        and not await is_phone_verified(session, user_id)
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "phone_verification_required: share your phone via Telegram "
                "before creating a bot"
            ),
        )

    if not (user and user.is_admin):
        quota = await check_bot_quota(session, user_id)
        if not quota.allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"bot_quota_exceeded: {quota.current}/{quota.quota} bots used. "
                    "Upgrade or ask an admin for more."
                ),
            )

    existing = await session.get(Bot, body.bot_id)
    if existing:
        raise HTTPException(status_code=409, detail="bot_id already exists")

    orchestrator = Orchestrator(session)

    try:
        await orchestrator.plant_bot(
            bot_id=body.bot_id,
            user_id=user_id,
            token=body.token,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    bot = await session.get(Bot, body.bot_id)
    fire("bot_created", {"bot_id": bot.id, "user_id": user_id})
    return _bot_out(bot)


@app.get("/bots/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Return a single bot by id."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return _bot_out(bot)


@app.delete("/bots/{bot_id}")
async def stop_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Reap a bot and mark it hibernated."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    orchestrator = Orchestrator(session)
    await orchestrator.reap_bot(bot_id)

    bot.is_active = False
    bot.is_hibernated = True
    bot.port = None
    await session.commit()

    return {"status": "stopped"}


# ─────────────────────────────────────────────────────────────────────────
# BotFather automation (Phase 1.ج, Bot API portion)
# ─────────────────────────────────────────────────────────────────────────


class CommandIn(BaseModel):
    command: str
    description: str


class BotProfileIn(BaseModel):
    """Partial profile update — only set the fields you want changed."""

    name: str | None = None
    description: str | None = None
    short_description: str | None = None
    commands: list[CommandIn] | None = None
    language_code: str = ""


@app.get("/users/{user_id}/bots/{bot_id}/profile")
async def get_bot_profile(
    user_id: str,
    bot_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Fetch the bot's live profile (name, descriptions, commands) from Telegram."""
    try:
        profile = await fetch_bot_profile(session, user_id, bot_id)
    except BotFatherError as exc:
        status = exc.code if isinstance(exc.code, int) and 400 <= exc.code < 600 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return profile.to_dict()


@app.patch("/users/{user_id}/bots/{bot_id}/profile")
async def patch_bot_profile(
    user_id: str,
    bot_id: str,
    body: BotProfileIn,
    session: AsyncSession = Depends(get_session),
):
    """Apply a partial profile update to the bot via the Telegram Bot API."""
    user = await session.get(User, user_id)
    if (
        settings.REQUIRE_PHONE_VERIFICATION
        and not (user and user.is_admin)
        and not await is_phone_verified(session, user_id)
    ):
        raise HTTPException(
            status_code=403,
            detail="phone_verification_required: share your phone before managing bots",
        )

    payload = body.model_dump(exclude_unset=True)
    commands = payload.pop("commands", None)
    if commands is not None:
        commands = [BFCommand(**c) for c in commands]

    try:
        results = await update_bot_profile(
            session,
            user_id,
            bot_id,
            commands=commands,
            **{k: v for k, v in payload.items() if k != "language_code"},
            language_code=payload.get("language_code", ""),
        )
    except BotFatherError as exc:
        status = exc.code if isinstance(exc.code, int) and 400 <= exc.code < 600 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"results": results}
