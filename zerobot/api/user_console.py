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

from zerobot.core.orchestrator import Orchestrator
from zerobot.database.engine import async_session_maker
from zerobot.database.models import Bot, User
from zerobot.database.wallet import WalletService
from zerobot.events.publisher import fire

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
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


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
    """Plant a new bot for *user_id*. Charges 1 crystal on success."""
    user = await session.get(User, user_id)
    if not user:
        session.add(User(id=user_id))
        await session.commit()
        fire("user_registered", {"user_id": user_id, "source": "create_bot"})

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
