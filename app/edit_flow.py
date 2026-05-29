from aiogram import F, Router
from aiogram.types import Message

from app.access import is_owner_id, reject_message_if_not_allowed
from app.published import apply_published_text_edit
from app.services.preview import send_post_preview
from app.settings import get_settings
from app.storage.events import log_event
from app.storage.posts import get_post, update_post_caption
from app.storage.session import get_active_post, set_active_post, set_last_preview_message_ids
from app.ui import review_keyboard

router = Router()


@router.message(F.text)
async def handle_edit_text(message: Message) -> None:
    settings = get_settings()
    post_id, mode = await get_active_post(settings.database_path, message.from_user.id)

    if post_id is None:
        return

    # Edição de publicação JÁ no ar (owner-only). O modo só é setado pelo botão
    # owner-only da notificação, mas reforçamos aqui por segurança.
    if mode == "edit_published_text":
        if not is_owner_id(message.from_user.id):
            return
        new_html = message.html_text if message.text else (message.caption or "")
        ok, info = await apply_published_text_edit(
            message.bot, message.from_user.id, post_id, new_html
        )
        if ok:
            await set_active_post(
                settings.database_path,
                user_id=message.from_user.id,
                post_id=None,
                mode=None,
                clear_channel=True,
            )
        await message.answer(info)
        return

    if mode != "edit_text":
        return

    if await reject_message_if_not_allowed(message):
        return

    new_caption = message.html_text if message.text else (message.caption or "")
    await update_post_caption(settings.database_path, post_id, new_caption)
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

    header = await message.answer(
        f"✏️ Legenda do post #{post_id} atualizada. Veja como vai ficar:"
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
