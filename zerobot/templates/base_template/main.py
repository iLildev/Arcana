import os
import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher, types

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("BOT_PORT", 8080))

bot = Bot(token=TOKEN)
dp = Dispatcher()


# 🧠 مثال handler
@dp.message()
async def echo_handler(message: types.Message):
    await message.answer(f"Echo: {message.text}")


# 🌐 webhook handler
async def handle_webhook(request: web.Request):
    data = await request.json()

    update = types.Update.model_validate(data)

    await dp.feed_update(bot, update)

    return web.Response(text="ok")


# 🚀 app
app = web.Application()
app.router.add_post("/webhook", handle_webhook)


if __name__ == "__main__":
    web.run_app(app, port=PORT)
