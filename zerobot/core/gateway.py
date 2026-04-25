from fastapi import FastAPI, Request, HTTPException
from sqlalchemy import select

from database.engine import async_session_maker
from database.models import Bot
from core.delivery import DeliveryManager
from core.limiter import RateLimiter
from core.orchestrator import Orchestrator
from core.wake_buffer import wake_buffer
from analytics.tracker import Tracker
from hibernation.hibernator import Hibernator


app = FastAPI(title="ZeroBot Gateway")
delivery = DeliveryManager()
limiter = RateLimiter()
tracker = Tracker()
hibernator = Hibernator()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/webhook/{bot_id}")
async def handle_update(bot_id: str, request: Request):
    update = await request.json()

    async with async_session_maker() as session:
        orchestrator = Orchestrator(session)

        result = await session.execute(
            select(Bot).where(Bot.id == bot_id)
        )
        bot = result.scalar_one_or_none()

        if not bot:
            raise HTTPException(status_code=404, detail="Bot not found")

        if not bot.is_active:
            raise HTTPException(status_code=403, detail="Bot is inactive")

        if bot.is_hibernated:
            await wake_buffer.add(bot_id, update)

            # 🔥 إيقاظ البوت فعليًا
            await orchestrator.wake_bot(bot)

            # 🔥 تفريغ الرسائل بعد الاستيقاظ
            buffered_updates = await wake_buffer.flush(bot_id)

            for upd in buffered_updates:
                await delivery.forward(bot.port, upd)

            return {"status": "woken up - Powered by @iLildev"}

        # Rate limit
        if not limiter.allow(bot_id):
            return {"error": "rate limited - Powered by @iLildev"}

        # سجل النشاط
        tracker.track(bot_id)
        hibernator.touch(bot_id)

        if bot.port is None:
            raise HTTPException(status_code=503, detail="Bot has no port assigned")

        await delivery.forward(bot.port, update)
        return {"status": "delivered"}
