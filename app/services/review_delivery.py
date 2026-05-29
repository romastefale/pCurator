import logging

from aiogram import Bot

from app.services.preview import send_post_preview
from app.services.regenerator import UNIFIED_TONE, regenerate_post_for_channel
from app.storage.posts import get_post
from app.storage.session import set_last_preview_message_ids
from app.ui import review_keyboard

logger = logging.getLogger(__name__)

__all__ = ["UNIFIED_TONE", "generation_warning", "generate_and_deliver_review"]


def generation_warning(metadata: dict) -> str | None:
    if not metadata.get("ok"):
        return "⚠️ Não consegui gerar a prévia editorial. Verifique os logs do Railway."

    engine = metadata.get("engine")
    if engine == "mira":
        return None

    notes = ", ".join(metadata.get("quality_notes") or []) or "sem detalhes"
    if engine == "openai":
        return f"⚠️ Mira não respondeu. Foi usado fallback OpenAI.\nMotivo: {notes}"

    return f"⚠️ Mira e OpenAI não foram usadas com sucesso. Foi usado fallback local.\nMotivo: {notes}"


async def generate_and_deliver_review(
    bot: Bot,
    database_path: str,
    *,
    chat_id: int,
    user_id: int,
    post_id: int,
    status_message_id: int | None = None,
) -> dict:
    """Gera a prévia editorial com o tom único e entrega o review_keyboard.

    Centraliza o fluxo (geração → prévia → instrução) usado tanto pelo intake
    manual de link quanto pela regeneração de duplicata. Devolve o metadata da
    geração. Mensagens efêmeras são rastreadas pra limpeza posterior."""
    metadata = await regenerate_post_for_channel(
        database_path, post_id=post_id, channel_slug=UNIFIED_TONE, bot=bot,
    )
    post = await get_post(database_path, post_id)

    tracked: list[int] = []
    if status_message_id is not None:
        tracked.append(status_message_id)

    if metadata.get("ok") and post:
        tracked.extend(await send_post_preview(bot, chat_id, post))

    warning = generation_warning(metadata)
    if warning:
        warn = await bot.send_message(chat_id=chat_id, text=warning)
        tracked.append(warn.message_id)

    if metadata.get("ok"):
        instruction = (
            "Acima está a prévia exata.\n"
            "Você pode editar o texto, trocar a imagem ou avançar para escolher o canal de publicação."
        )
    else:
        instruction = (
            "Não foi possível gerar a prévia automaticamente.\n"
            "Você pode editar o texto manualmente ou trocar a imagem."
        )
    instr = await bot.send_message(chat_id=chat_id, text=instruction, reply_markup=review_keyboard())
    tracked.append(instr.message_id)

    await set_last_preview_message_ids(database_path, user_id, tracked)
    return metadata
