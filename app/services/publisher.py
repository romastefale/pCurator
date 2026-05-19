from aiogram import Bot
from aiogram.enums import ParseMode

PHOTO_CAPTION_LIMIT = 1024


async def publish_post(bot: Bot, chat_id: int, post: dict) -> None:
    caption = post["caption_html"]
    image_ref = post.get("image_url")

    if image_ref:
        if len(caption) <= PHOTO_CAPTION_LIMIT:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_ref,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return

        await bot.send_photo(chat_id=chat_id, photo=image_ref)
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode=ParseMode.HTML,
    )
