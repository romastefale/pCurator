import asyncio

from aiogram import Bot

from app.app_factory import create_dispatcher
from app.settings import get_settings
from app.storage.database import init_db


async def run_polling() -> None:
    settings = get_settings()
    await init_db(settings.database_path)

    bot = Bot(token=settings.bot_token)
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_polling())
