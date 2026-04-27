"""Public ingress for Telegram webhooks.

The gateway is the only HTTP service Telegram talks to directly. It looks up
the target bot, applies the rate limit, optionally wakes a hibernating bot,
and forwards the update to the bot's local webhook port.

Background tasks
----------------
On startup, the FastAPI lifespan hook launches :py:meth:`Hibernator.monitor`
so idle bots are reaped automatically. The task is cancelled on shutdown.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import select, text

from arcana.analytics.tracker import Tracker
from arcana.core.delivery import DeliveryManager
from arcana.core.limiter import RateLimiter
from arcana.core.orchestrator import Orchestrator
from arcana.core.wake_buffer import wake_buffer
from arcana.database.engine import async_session_maker
from arcana.database.models import Bot
from arcana.hibernation.hibernator import Hibernator

log = logging.getLogger(__name__)

delivery = DeliveryManager()
limiter = RateLimiter()
tracker = Tracker()
hibernator = Hibernator()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Start background watchdogs on app boot; cancel them on shutdown."""
    monitor_task = asyncio.create_task(hibernator.monitor(async_session_maker))
    log.info("gateway: lifespan started, hibernator monitor task launched")
    try:
        yield
    finally:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        log.info("gateway: lifespan shutdown complete")


app = FastAPI(title="Arcana Gateway", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness + readiness probe.

    Returns ``status: "ok"`` when the database is reachable and
    ``status: "degraded"`` (HTTP 503) when it is not. The Hibernator monitor
    state is also surfaced so operators can spot a stuck watchdog.
    """
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
        "tracked_bots": len(hibernator.last_seen),
    }
    if db_error:
        body["error"] = db_error
        raise HTTPException(status_code=503, detail=body)
    return body


@app.post("/webhook/{bot_id}")
async def handle_update(bot_id: str, request: Request) -> dict:
    """Entry point for Telegram updates.

    Resolves the bot, wakes it if needed, throttles, and forwards.
    """
    update = await request.json()

    async with async_session_maker() as session:
        orchestrator = Orchestrator(session)

        result = await session.execute(select(Bot).where(Bot.id == bot_id))
        bot = result.scalar_one_or_none()

        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        if not bot.is_active:
            raise HTTPException(status_code=403, detail="Bot is inactive")

        if bot.is_hibernated:
            # Buffer the incoming update, wake the bot, then flush the queue.
            await wake_buffer.add(bot_id, update)

            await orchestrator.wake_bot(bot)
            await session.refresh(bot)

            buffered_updates = await wake_buffer.flush(bot_id)
            for upd in buffered_updates:
                await delivery.forward(bot.port, upd)

            return {"status": "woken", "delivered": len(buffered_updates)}

        # Throttle hot bots.
        if not limiter.allow(bot_id):
            raise HTTPException(status_code=429, detail="rate limited")

        # Record activity for analytics + hibernation timer.
        tracker.track(bot_id)
        hibernator.touch(bot_id)

        if bot.port is None:
            raise HTTPException(status_code=503, detail="Bot has no port assigned")

        await delivery.forward(bot.port, update)
        return {"status": "delivered"}
