from aiogram import F, Router
from aiogram.types import Message

from app.services.mira_bridge import resolve_mira_response
from app.settings import get_settings

router = Router()


async def _is_mira_group(message: Message) -> bool:
    settings = get_settings()
    return message.chat.id == settings.mira_group_id


@router.message(F.reply_to_message)
async def handle_mira_answer(message: Message) -> None:
    if not await _is_mira_group(message):
        return

    base = getattr(message, "reply_to_message", None)
    if not base:
        return

    base_text = getattr(base, "text", None) or getattr(base, "caption", None)
    answer_text = getattr(message, "text", None) or getattr(message, "caption", None)
    await resolve_mira_response(base_text, answer_text)
