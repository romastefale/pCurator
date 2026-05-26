from aiogram import F, Router
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.services.preview import send_post_preview
from app.settings import get_settings
from app.storage.events import log_event
from app.storage.posts import get_post, update_post_image
from app.storage.session import get_active_post, set_active_post, set_last_preview_message_ids
from app.ui import review_keyboard

router = Router()


@router.message(F.photo)
async def handle_manual_image(message: Message) -> None:
    settings = get_settings()
    post_id, mode = await get_active_post(settings.database_path, message.from_user.id)

    if mode != "edit_image" or post_id is None:
        return

    if await reject_message_if_not_owner(message):
        return

    image_ref = message.photo[-1].file_id
    await update_post_image(settings.database_path, post_id, image_ref)
    await log_event(
        settings.database_path,
        event_type="image_updated",
        payload={"user_id": message.from_user.id, "post_id": post_id},
    )
    await set_active_post(
        settings.database_path,
        user_id=message.from_user.id,
        post_id=post_id,
        mode="review",
    )

    header = await message.answer(
        f"🖼 Imagem do post #{post_id} atualizada. Veja como vai ficar:"
    )
    tracked: list[int] = [header.message_id]
    post = await get_post(settings.database_path, post_id)
    if post:
        tracked.extend(await send_post_preview(message.bot, message.chat.id, post))
    footer = await message.answer(
        "Confirme a publicação ou edite novamente.",
        reply_markup=review_keyboard(),
    )
    tracked.append(footer.message_id)
    await set_last_preview_message_ids(settings.database_path, message.from_user.id, tracked)
