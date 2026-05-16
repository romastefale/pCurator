from aiogram.types import CallbackQuery, Message

from app.settings import get_settings


def is_owner_id(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return user_id == get_settings().owner_id


async def reject_message_if_not_owner(message: Message) -> bool:
    if is_owner_id(message.from_user.id if message.from_user else None):
        return False
    await message.answer("Acesso restrito.")
    return True


async def reject_callback_if_not_owner(callback: CallbackQuery) -> bool:
    if is_owner_id(callback.from_user.id if callback.from_user else None):
        return False
    await callback.answer("Acesso restrito.", show_alert=True)
    return True
