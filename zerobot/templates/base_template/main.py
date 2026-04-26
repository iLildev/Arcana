"""Default ZeroBot starter template.

Spins up an aiohttp webhook receiver that hands every Telegram update off
to an aiogram dispatcher. This file is copied into a fresh bot's
directory by the orchestrator; users are expected to extend it.
"""

import logging
import os

from aiogram import Bot, Dispatcher, types
from aiohttp import web

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("BOT_PORT", "8080"))

bot = Bot(token=TOKEN)
dp = Dispatcher()


# 🧠 Example handler.
@dp.message()
async def echo_handler(message: types.Message):
    """Echo every incoming text message back to the sender."""
    await message.answer(f"Echo: {message.text}")


# 🌐 Webhook handler.
async def handle_webhook(request: web.Request):
    """Forward an inbound Telegram update to the aiogram dispatcher."""
    data = await request.json()

    update = types.Update.model_validate(data)

    await dp.feed_update(bot, update)

    return web.Response(text="ok")


# 🚀 App definition.
app = web.Application()
app.router.add_post("/webhook", handle_webhook)


if __name__ == "__main__":
    web.run_app(app, port=PORT)
