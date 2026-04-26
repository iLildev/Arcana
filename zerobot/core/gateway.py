"""Public ingress for Telegram webhooks.

The gateway is the only HTTP service Telegram talks to directly. It looks up
the target bot, applies the rate limit, optionally wakes a hibernating bot,
and forwards the update to the bot's local webhook port.
"""

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import select

from zerobot.analytics.tracker import Tracker
from zerobot.core.delivery import DeliveryManager
from zerobot.core.limiter import RateLimiter
from zerobot.core.orchestrator import Orchestrator
from zerobot.core.wake_buffer import wake_buffer
from zerobot.database.engine import async_session_maker
from zerobot.database.models import Bot
from zerobot.hibernation.hibernator import Hibernator

app = FastAPI(title="ZeroBot Gateway")
delivery = DeliveryManager()
limiter = RateLimiter()
tracker = Tracker()
hibernator = Hibernator()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


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

            return {"status": "woken up - Powered by @iLildev"}

        # Throttle hot bots.
        if not limiter.allow(bot_id):
            return {"error": "rate limited - Powered by @iLildev"}

        # Record activity for analytics + hibernation timer.
        tracker.track(bot_id)
        hibernator.touch(bot_id)

        if bot.port is None:
            raise HTTPException(status_code=503, detail="Bot has no port assigned")

        await delivery.forward(bot.port, update)
        return {"status": "delivered"}
