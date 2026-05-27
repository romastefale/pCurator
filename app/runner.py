import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.app_factory import create_dispatcher
from app.services.discovery_scheduler import discovery_loop
from app.settings import get_settings
from app.storage.database import init_db

logger = logging.getLogger(__name__)


async def run_polling() -> None:
    settings = get_settings()
    await init_db(settings.database_path)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    dispatcher = create_dispatcher()

    discovery_task = asyncio.create_task(
        discovery_loop(bot, settings), name="discovery_loop"
    )

    try:
        await dispatcher.start_polling(bot)
    finally:
        discovery_task.cancel()
        try:
            await discovery_task
        except (asyncio.CancelledError, Exception):
            pass
        await bot.session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run_polling())
