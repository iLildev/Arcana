"""Privileged admin FastAPI service.

Every ``/admin/*`` route is gated by the ``X-Admin-Token`` header and the
matching ``settings.ADMIN_TOKEN`` value. ``/healthz`` is always public so
that a process supervisor can probe the service without credentials.
"""

import contextlib
import shutil
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.config import settings
from zerobot.core.orchestrator import Orchestrator
from zerobot.database.engine import async_session_maker
from zerobot.database.models import Bot, User, Wallet
from zerobot.database.port_registry import Port
from zerobot.database.wallet import WalletService
from zerobot.events.publisher import fire
from zerobot.isolation.venv_manager import VenvManager

app = FastAPI(title="ZeroBot Admin Console")


# ─────────────── Dependencies ───────────────


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields one ``AsyncSession`` per request."""
    async with async_session_maker() as session:
        yield session


async def require_admin(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> bool:
    """Reject the request unless the caller presents the configured admin token."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Admin disabled: ADMIN_TOKEN is not set in environment",
        )
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True


AdminGuard = Depends(require_admin)


# ─────────────── Schemas ───────────────


class BotOut(BaseModel):
    """Public projection of a ``Bot`` row."""

    id: str
    user_id: str
    is_active: bool
    is_hibernated: bool
    is_official: bool
    name: str | None
    description: str | None
    port: int | None
    created_at: str | None


class UserOut(BaseModel):
    """Summary of a user (used by the user-list endpoint)."""

    id: str
    is_admin: bool
    bot_count: int
    balance: int
    created_at: str | None


class UserDetailOut(BaseModel):
    """Detailed user view with embedded bot list."""

    id: str
    is_admin: bool
    balance: int
    bots: list[BotOut]
    created_at: str | None


class WalletOut(BaseModel):
    """Wallet snapshot for crystal-management responses."""

    user_id: str
    balance: int


class StatsOut(BaseModel):
    """Aggregate platform stats reported by ``GET /admin/stats``."""

    users_total: int
    bots_total: int
    bots_active: int
    bots_hibernated: int
    bots_official: int
    ports_total: int
    ports_used: int
    ports_free: int
    ports_cooldown: int
    crystals_in_circulation: int


class PortOut(BaseModel):
    """One row from the port registry."""

    port_number: int
    bot_id: str | None
    status: str
    last_used: str | None


class AmountIn(BaseModel):
    """Request body for grant / deduct endpoints."""

    amount: int


class CreateOfficialBotIn(BaseModel):
    """Request body for ``POST /admin/official-bots``."""

    bot_id: str
    token: str
    name: str | None = None
    description: str | None = None


class PatchBotIn(BaseModel):
    """Request body for ``PATCH /admin/bots/{bot_id}``."""

    name: str | None = None
    description: str | None = None
    is_official: bool | None = None


def _bot_out(bot: Bot) -> BotOut:
    """Project an ORM ``Bot`` into the public ``BotOut`` schema."""
    return BotOut(
        id=bot.id,
        user_id=bot.user_id,
        is_active=bool(bot.is_active),
        is_hibernated=bool(bot.is_hibernated),
        is_official=bool(getattr(bot, "is_official", False)),
        name=getattr(bot, "name", None),
        description=getattr(bot, "description", None),
        port=bot.port,
        created_at=bot.created_at.isoformat() if bot.created_at else None,
    )


# ═══════════════════════════ HEALTH ═══════════════════════════


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness probe (also reports whether admin auth is configured)."""
    return {"status": "ok", "admin_enabled": bool(settings.ADMIN_TOKEN)}


# ═══════════════════════════ SYSTEM OVERVIEW ═══════════════════════════


@app.get("/admin/stats", response_model=StatsOut, dependencies=[AdminGuard])
async def system_stats(session: AsyncSession = Depends(get_session)):
    """Return platform-wide counters (users, bots, ports, crystals)."""

    async def count(stmt):
        return (await session.execute(stmt)).scalar() or 0

    return StatsOut(
        users_total=await count(select(func.count(User.id))),
        bots_total=await count(select(func.count(Bot.id))),
        bots_active=await count(select(func.count(Bot.id)).where(Bot.is_active.is_(True))),
        bots_hibernated=await count(select(func.count(Bot.id)).where(Bot.is_hibernated.is_(True))),
        bots_official=await count(select(func.count(Bot.id)).where(Bot.is_official.is_(True))),
        ports_total=await count(select(func.count(Port.port_number))),
        ports_used=await count(select(func.count(Port.port_number)).where(Port.status == "used")),
        ports_free=await count(select(func.count(Port.port_number)).where(Port.status == "free")),
        ports_cooldown=await count(
            select(func.count(Port.port_number)).where(Port.status == "cooldown")
        ),
        crystals_in_circulation=await count(select(func.coalesce(func.sum(Wallet.balance), 0))),
    )


# ═══════════════════════════ USERS ═══════════════════════════


@app.get("/admin/users", response_model=list[UserOut], dependencies=[AdminGuard])
async def list_users(session: AsyncSession = Depends(get_session)):
    """Return every user with their bot count and crystal balance."""
    users = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    out: list[UserOut] = []
    wallet_service = WalletService(session)

    for u in users:
        bot_count = (
            await session.execute(select(func.count(Bot.id)).where(Bot.user_id == u.id))
        ).scalar() or 0
        wallet = await wallet_service.get_wallet(u.id)
        out.append(
            UserOut(
                id=u.id,
                is_admin=bool(u.is_admin),
                bot_count=bot_count,
                balance=wallet.balance,
                created_at=u.created_at.isoformat() if u.created_at else None,
            )
        )
    return out


@app.get("/admin/users/{user_id}", response_model=UserDetailOut, dependencies=[AdminGuard])
async def get_user(user_id: str, session: AsyncSession = Depends(get_session)):
    """Detailed view of a single user, including every owned bot."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    bots = (await session.execute(select(Bot).where(Bot.user_id == user_id))).scalars().all()
    wallet = await WalletService(session).get_wallet(user_id)

    return UserDetailOut(
        id=user.id,
        is_admin=bool(user.is_admin),
        balance=wallet.balance,
        bots=[_bot_out(b) for b in bots],
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


@app.post(
    "/admin/users/{user_id}/wallet/grant",
    response_model=WalletOut,
    dependencies=[AdminGuard],
)
async def grant_crystals(
    user_id: str, body: AmountIn, session: AsyncSession = Depends(get_session)
):
    """Credit *amount* crystals to *user_id* (creates the user if missing)."""
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")

    user = await session.get(User, user_id)
    if not user:
        session.add(User(id=user_id))
        await session.commit()

    service = WalletService(session)
    await service.add(user_id, body.amount)
    wallet = await service.get_wallet(user_id)
    fire(
        "wallet_grant",
        {"user_id": user_id, "amount": body.amount, "balance": wallet.balance},
    )
    return WalletOut(user_id=user_id, balance=wallet.balance)


@app.post(
    "/admin/users/{user_id}/wallet/deduct",
    response_model=WalletOut,
    dependencies=[AdminGuard],
)
async def deduct_crystals(
    user_id: str, body: AmountIn, session: AsyncSession = Depends(get_session)
):
    """Charge *amount* crystals from an existing user."""
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")

    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    service = WalletService(session)
    try:
        await service.charge(user_id, body.amount)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e

    wallet = await service.get_wallet(user_id)
    fire(
        "wallet_deduct",
        {"user_id": user_id, "amount": body.amount, "balance": wallet.balance},
    )
    return WalletOut(user_id=user_id, balance=wallet.balance)


@app.post("/admin/users/{user_id}/promote", dependencies=[AdminGuard])
async def promote_user(user_id: str, session: AsyncSession = Depends(get_session)):
    """Flag *user_id* as a platform admin."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.is_admin = True
    await session.commit()
    return {"user_id": user_id, "is_admin": True}


@app.post("/admin/users/{user_id}/demote", dependencies=[AdminGuard])
async def demote_user(user_id: str, session: AsyncSession = Depends(get_session)):
    """Remove the admin flag from *user_id*."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.is_admin = False
    await session.commit()
    return {"user_id": user_id, "is_admin": False}


@app.delete("/admin/users/{user_id}", dependencies=[AdminGuard])
async def delete_user(user_id: str, session: AsyncSession = Depends(get_session)):
    """Reap every bot owned by *user_id*, then delete the user + wallet rows."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    bots = (await session.execute(select(Bot).where(Bot.user_id == user_id))).scalars().all()

    orchestrator = Orchestrator(session)
    venv = VenvManager()

    for b in bots:
        # Bot may already be dead; ignore reaping errors.
        with contextlib.suppress(Exception):
            await orchestrator.reap_bot(b.id)
        bot_path = venv.get_bot_path(b.id)
        if bot_path.exists():
            shutil.rmtree(bot_path, ignore_errors=True)
        await session.delete(b)

    wallet = (
        await session.execute(select(Wallet).where(Wallet.user_id == user_id))
    ).scalar_one_or_none()
    if wallet:
        await session.delete(wallet)

    await session.delete(user)
    await session.commit()
    fire("user_deleted", {"user_id": user_id, "bots_removed": len(bots)})
    return {"status": "deleted", "user_id": user_id, "bots_removed": len(bots)}


# ═══════════════════════════ BOTS (all users) ═══════════════════════════


@app.get("/admin/bots", response_model=list[BotOut], dependencies=[AdminGuard])
async def list_bots(
    is_active: bool | None = Query(None),
    is_hibernated: bool | None = Query(None),
    is_official: bool | None = Query(None),
    user_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """List every bot, with optional state / ownership filters."""
    q = select(Bot)
    if is_active is not None:
        q = q.where(Bot.is_active.is_(is_active))
    if is_hibernated is not None:
        q = q.where(Bot.is_hibernated.is_(is_hibernated))
    if is_official is not None:
        q = q.where(Bot.is_official.is_(is_official))
    if user_id is not None:
        q = q.where(Bot.user_id == user_id)

    bots = (await session.execute(q.order_by(Bot.created_at))).scalars().all()
    return [_bot_out(b) for b in bots]


@app.get("/admin/bots/{bot_id}", response_model=BotOut, dependencies=[AdminGuard])
async def get_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Return a single bot by id."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")
    return _bot_out(bot)


@app.post("/admin/bots/{bot_id}/wake", response_model=BotOut, dependencies=[AdminGuard])
async def force_wake(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Force a hibernating bot to wake up immediately."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    orchestrator = Orchestrator(session)
    await orchestrator.wake_bot(bot)
    await session.refresh(bot)
    fire("bot_state_changed", {"bot_id": bot.id, "action": "woken"})
    return _bot_out(bot)


@app.post(
    "/admin/bots/{bot_id}/hibernate",
    response_model=BotOut,
    dependencies=[AdminGuard],
)
async def force_hibernate(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Reap a running bot and mark it hibernated."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    orchestrator = Orchestrator(session)
    with contextlib.suppress(Exception):
        await orchestrator.reap_bot(bot.id)

    bot.is_active = False
    bot.is_hibernated = True
    bot.port = None
    await session.commit()
    fire("bot_state_changed", {"bot_id": bot.id, "action": "hibernated"})
    return _bot_out(bot)


@app.post("/admin/bots/{bot_id}/restart", response_model=BotOut, dependencies=[AdminGuard])
async def restart_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Reap and re-launch a bot in one step."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    orchestrator = Orchestrator(session)

    with contextlib.suppress(Exception):
        await orchestrator.reap_bot(bot.id)

    bot.is_active = False
    bot.port = None
    await session.commit()

    await orchestrator.wake_bot(bot)
    await session.refresh(bot)
    fire("bot_state_changed", {"bot_id": bot.id, "action": "restarted"})
    return _bot_out(bot)


@app.delete("/admin/bots/{bot_id}", dependencies=[AdminGuard])
async def delete_bot(bot_id: str, session: AsyncSession = Depends(get_session)):
    """Reap a bot, wipe its venv, and remove the database row."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    orchestrator = Orchestrator(session)
    with contextlib.suppress(Exception):
        await orchestrator.reap_bot(bot.id)

    bot_path = VenvManager().get_bot_path(bot.id)
    if bot_path.exists():
        shutil.rmtree(bot_path, ignore_errors=True)

    await session.delete(bot)
    await session.commit()
    fire("bot_deleted", {"bot_id": bot_id})
    return {"status": "deleted", "bot_id": bot_id}


@app.patch("/admin/bots/{bot_id}", response_model=BotOut, dependencies=[AdminGuard])
async def patch_bot(bot_id: str, body: PatchBotIn, session: AsyncSession = Depends(get_session)):
    """Update editable bot metadata (name / description / official flag)."""
    bot = await session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    if body.name is not None:
        bot.name = body.name
    if body.description is not None:
        bot.description = body.description
    if body.is_official is not None:
        bot.is_official = body.is_official

    await session.commit()
    return _bot_out(bot)


# ═══════════════════════════ OFFICIAL BOTS (developer's own) ═══════════════════════════


@app.get("/admin/official-bots", response_model=list[BotOut], dependencies=[AdminGuard])
async def list_official_bots(session: AsyncSession = Depends(get_session)):
    """Return every bot flagged ``is_official``."""
    bots = (
        (
            await session.execute(
                select(Bot).where(Bot.is_official.is_(True)).order_by(Bot.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_bot_out(b) for b in bots]


@app.post(
    "/admin/official-bots",
    response_model=BotOut,
    status_code=201,
    dependencies=[AdminGuard],
)
async def create_official_bot(
    body: CreateOfficialBotIn, session: AsyncSession = Depends(get_session)
):
    """Plant a new bot owned by the platform admin (free of charge)."""
    if not settings.ADMIN_USER_ID:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_USER_ID not set — cannot own official bots",
        )

    user_id = settings.ADMIN_USER_ID

    user = await session.get(User, user_id)
    if not user:
        session.add(User(id=user_id, is_admin=True))
        await session.commit()
    elif not user.is_admin:
        user.is_admin = True
        await session.commit()

    existing = await session.get(Bot, body.bot_id)
    if existing:
        raise HTTPException(409, "bot_id already exists")

    # Official bots are free for the developer: pre-credit 1 crystal so the
    # plant_bot charge nets to zero (we don't touch the closed orchestrator).
    wallet_service = WalletService(session)
    await wallet_service.add(user_id, 1)

    orchestrator = Orchestrator(session)
    try:
        await orchestrator.plant_bot(
            bot_id=body.bot_id,
            user_id=user_id,
            token=body.token,
        )
    except RuntimeError as e:
        # Roll back the pre-credit so the wallet balance is unchanged.
        with contextlib.suppress(Exception):
            await wallet_service.charge(user_id, 1)
        raise HTTPException(400, str(e)) from e

    bot = await session.get(Bot, body.bot_id)
    bot.is_official = True
    bot.name = body.name
    bot.description = body.description
    await session.commit()

    fire(
        "official_bot_created",
        {"bot_id": bot.id, "name": body.name, "description": body.description},
    )
    return _bot_out(bot)


# ═══════════════════════════ PORT REGISTRY ═══════════════════════════


@app.get("/admin/ports", response_model=list[PortOut], dependencies=[AdminGuard])
async def list_ports(
    status_filter: str | None = Query(None, alias="status"),
    session: AsyncSession = Depends(get_session),
):
    """Inspect the port registry, optionally filtered by status."""
    q = select(Port).order_by(Port.port_number)
    if status_filter is not None:
        q = q.where(Port.status == status_filter)

    ports = (await session.execute(q)).scalars().all()
    return [
        PortOut(
            port_number=p.port_number,
            bot_id=p.bot_id,
            status=p.status,
            last_used=p.last_used.isoformat() if p.last_used else None,
        )
        for p in ports
    ]


@app.post("/admin/ports/{port_number}/release", dependencies=[AdminGuard])
async def force_release_port(port_number: int, session: AsyncSession = Depends(get_session)):
    """Manually mark a port back as ``free`` (recovery escape hatch)."""
    port = await session.get(Port, port_number)
    if not port:
        raise HTTPException(404, "Port not found")

    port.status = "free"
    port.bot_id = None
    port.last_used = None
    await session.commit()
    return {"port_number": port_number, "status": "free"}
