from aiogram.types import CallbackQuery, Message

from app.settings import get_settings
from app.storage.authorized_users import is_authorized


def is_owner_id(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id == get_settings().owner_id


async def is_allowed_user(user_id: int | None) -> bool:
    """Dono OU co-autor ativo. Quem pode operar o fluxo editorial."""
    if user_id is None:
        return False
    if is_owner_id(user_id):
        return True
    return await is_authorized(get_settings().database_path, user_id)


async def reject_message_if_not_allowed(message: Message) -> bool:
    if await is_allowed_user(message.from_user.id if message.from_user else None):
        return False
    await message.answer("Acesso restrito.")
    return True


async def reject_callback_if_not_allowed(callback: CallbackQuery) -> bool:
    if await is_allowed_user(callback.from_user.id if callback.from_user else None):
        return False
    await callback.answer("Acesso restrito.", show_alert=True)
    return True


async def reject_message_if_not_owner(message: Message) -> bool:
    """Estrito: só o dono. Usado na gestão da equipe (autorizar/revogar)."""
    if is_owner_id(message.from_user.id if message.from_user else None):
        return False
    await message.answer("Apenas o dono do bot pode usar este comando.")
    return True


async def reject_callback_if_not_owner(callback: CallbackQuery) -> bool:
    if is_owner_id(callback.from_user.id if callback.from_user else None):
        return False
    await callback.answer("Apenas o dono do bot.", show_alert=True)
    return True
