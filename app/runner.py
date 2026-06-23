import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.app_factory import create_dispatcher
from app.services.discovery_scheduler import discovery_loop
from app.settings import Settings, get_settings
from app.services.channel_recovery import recover_channels
from app.storage.database import init_db

logger = logging.getLogger(__name__)


async def _seed_channels(bot: Bot, settings: Settings) -> None:
    """Revalida canais conhecidos no boot sem postar teste.

    A fonte não é mais apenas CHANNEL_1_ID/CHANNEL_2_ID: o motor combina env,
    tabela channels, posts publicados e tabelas de reação para recuperar
    hipóteses de canal. No boot a prova é passiva; /pcrecuperar faz prova ativa.
    """
    try:
        results = await recover_channels(
            bot,
            settings.database_path,
            env_chat_ids=[settings.channel_1_id, settings.channel_2_id],
            active_probe=False,
            limit=50,
        )
        for result in results:
            logger.info(
                "channel_boot_probe chat_id=%s ok=%s state=%s reason=%s",
                result.chat_id,
                result.ok,
                result.state,
                result.reason,
            )
    except Exception as exc:
        logger.warning("channel_boot_probe_failed err=%s", type(exc).__name__)


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
    allowed_updates = dispatcher.resolve_used_update_types()
    logger.info("allowed_updates=%s", allowed_updates)

    discovery_task = asyncio.create_task(
        discovery_loop(bot, settings), name="discovery_loop"
    )

    try:
        await dispatcher.start_polling(bot, allowed_updates=allowed_updates)
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
