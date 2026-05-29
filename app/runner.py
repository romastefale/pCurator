import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.app_factory import create_dispatcher
from app.services.discovery_scheduler import discovery_loop
from app.settings import Settings, get_settings
from app.storage.channels import upsert_channel
from app.storage.database import init_db

logger = logging.getLogger(__name__)


async def _seed_channels(bot: Bot, settings: Settings) -> None:
    """Cadastra/atualiza os canais já configurados (CHANNEL_1_ID/CHANNEL_2_ID)
    buscando o nome real via get_chat. Canais novos são detectados sozinhos
    pelo handler de my_chat_member quando o bot vira admin."""
    for chat_id in (settings.channel_1_id, settings.channel_2_id):
        if not chat_id:
            continue
        try:
            chat = await bot.get_chat(chat_id)
            await upsert_channel(
                settings.database_path,
                chat_id=chat.id,
                title=chat.title or str(chat.id),
                username=chat.username,
            )
            logger.info("channel_seeded chat_id=%s title=%s", chat.id, chat.title)
        except Exception as exc:
            logger.warning(
                "channel_seed_failed chat_id=%s err=%s", chat_id, type(exc).__name__
            )


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
    await _seed_channels(bot, settings)
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
