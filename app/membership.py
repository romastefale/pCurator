"""Detecção automática de canais via my_chat_member.

O Telegram não permite ao bot listar todos os canais que administra. Este
handler registra evidência quando o status do próprio bot muda e, junto do
motor de recuperação, mantém a tabela local coerente com a permissão real.
"""

import json
import logging

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from app.settings import get_settings
from app.storage.channels import update_channel_access_state, upsert_channel

logger = logging.getLogger(__name__)
router = Router()

_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
_POSTABLE_CHAT_TYPES = {"channel", "supergroup"}


def _flag(member: object, name: str) -> bool | None:
    value = getattr(member, name, None)
    if value is None:
        return None
    return bool(value)


def _status_text(status: object) -> str:
    value = getattr(status, "value", None)
    return str(value if value is not None else status)


def _can_publish(chat_type: str, status: ChatMemberStatus, can_post_messages: bool | None) -> bool:
    if status == ChatMemberStatus.CREATOR:
        return True
    if status != ChatMemberStatus.ADMINISTRATOR:
        return False
    if chat_type == "channel":
        return can_post_messages is True
    return can_post_messages is not False


@router.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    chat = event.chat
    if chat.type not in _POSTABLE_CHAT_TYPES:
        return

    settings = get_settings()
    new_member = event.new_chat_member
    new_status = new_member.status
    status_label = _status_text(new_status)
    can_post = _flag(new_member, "can_post_messages")
    can_edit = _flag(new_member, "can_edit_messages")
    can_delete = _flag(new_member, "can_delete_messages")

    if new_status in _ADMIN_STATUSES and _can_publish(chat.type, new_status, can_post):
        await upsert_channel(
            settings.database_path,
            chat_id=chat.id,
            title=chat.title or str(chat.id),
            username=chat.username,
            access_state="my_chat_member_restored",
            access_reason=(
                f"status={status_label}; can_post_messages={can_post}; "
                "update=my_chat_member"
            ),
            recovery_score=100,
            recovery_evidence=json.dumps(["my_chat_member"], ensure_ascii=False),
            bot_member_status=status_label,
            can_post_messages=can_post,
            can_edit_messages=can_edit,
            can_delete_messages=can_delete,
        )
        logger.info("channel_registered chat_id=%s title=%s", chat.id, chat.title)
    else:
        reason = f"status={status_label}; can_post_messages={can_post}; update=my_chat_member"
        await update_channel_access_state(
            settings.database_path,
            chat.id,
            is_enabled=False,
            state="my_chat_member_not_publishable",
            reason=reason,
            bot_member_status=status_label,
            can_post_messages=can_post,
            can_edit_messages=can_edit,
            can_delete_messages=can_delete,
        )
        logger.info("channel_disabled chat_id=%s reason=%s", chat.id, reason)
