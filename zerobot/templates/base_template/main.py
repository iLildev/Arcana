import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart


logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["BOT_TOKEN"]

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def on_start(message: types.Message):
    await message.answer("👋 Hello from your ZeroBot!")


@dp.message()
async def on_message(message: types.Message):
    await message.answer(message.text or "")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
