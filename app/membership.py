"""Detecção automática de canais via my_chat_member.

O Telegram NÃO deixa um bot listar os canais que administra. A única forma
nativa de descobrir é reagir ao update `my_chat_member`, disparado quando o
status do próprio bot muda num chat (foi promovido a admin, removido, etc.).
Aqui registramos/desabilitamos o canal conforme o bot ganha/perde admin.
"""

import logging

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from app.settings import get_settings
from app.storage.channels import set_channel_enabled, upsert_channel

logger = logging.getLogger(__name__)
router = Router()

_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
# Só faz sentido publicar em canais/supergrupos.
_POSTABLE_CHAT_TYPES = {"channel", "supergroup"}


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    chat = event.chat
    if chat.type not in _POSTABLE_CHAT_TYPES:
        return

    settings = get_settings()
    new_status = event.new_chat_member.status

    if new_status in _ADMIN_STATUSES:
        await upsert_channel(
            settings.database_path,
            chat_id=chat.id,
            title=chat.title or str(chat.id),
            username=chat.username,
        )
        logger.info("channel_registered chat_id=%s title=%s", chat.id, chat.title)
    else:
        # Removido, banido ou rebaixado a membro comum: não dá mais pra postar.
        await set_channel_enabled(settings.database_path, chat.id, False)
        logger.info("channel_disabled chat_id=%s status=%s", chat.id, new_status)
