from aiogram import F, Router
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.services.preview import send_post_preview
from app.settings import get_settings
from app.storage.events import log_event
from app.storage.posts import get_post, update_post_caption
from app.storage.session import get_active_post, set_active_post
from app.ui import review_keyboard

router = Router()


@router.message(F.text)
async def handle_edit_text(message: Message) -> None:
    settings = get_settings()
    post_id, mode = await get_active_post(settings.database_path, message.from_user.id)

    if mode != "edit_text" or post_id is None:
        return

    if await reject_message_if_not_owner(message):
        return

    await update_post_caption(settings.database_path, post_id, message.text)
    await log_event(
        settings.database_path,
        event_type="caption_updated",
        payload={"user_id": message.from_user.id, "post_id": post_id},
    )
    await set_active_post(
        settings.database_path,
        user_id=message.from_user.id,
        post_id=post_id,
        mode="review",
    )

    await message.answer(f"✏️ Legenda do post #{post_id} atualizada. Veja como vai ficar:")
    post = await get_post(settings.database_path, post_id)
    if post:
        await send_post_preview(message.bot, message.chat.id, post)
    await message.answer(
        "Confirme a publicação ou edite novamente.",
        reply_markup=review_keyboard(),
    )
