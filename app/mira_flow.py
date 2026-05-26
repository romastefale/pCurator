from aiogram import Router
from aiogram.types import Message

from app.services.mira_bridge import resolve_mira_response
from app.settings import get_settings

router = Router()


async def _is_mira_reply(message: Message) -> bool:
    if message.reply_to_message is None:
        return False
    return message.chat.id == get_settings().mira_group_id


@router.message(_is_mira_reply)
async def handle_mira_answer(message: Message) -> None:
    base = message.reply_to_message
    if base is None:
        return
    base_text = base.text or base.caption
    answer_text = message.text or message.caption
    await resolve_mira_response(base_text, answer_text)
