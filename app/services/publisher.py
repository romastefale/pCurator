import logging

from aiogram import Bot
from aiogram.types import LinkPreviewOptions, Message

logger = logging.getLogger(__name__)

PHOTO_CAPTION_LIMIT = 1024


async def publish_post(bot: Bot, chat_id: int, post: dict) -> list[int]:
    """Publica/preview o post. Retorna a lista de message_ids enviados.
    Estratégia (Bot API 9.5):
      - sem imagem: 1 sendMessage (sem preview).
      - imagem + caption <=1024: 1 sendPhoto com caption.
      - imagem + caption >1024: 2 mensagens (sendPhoto sem caption + sendMessage
        com texto completo). Vale para URL HTTP e para file_id.

    Por que sempre sendPhoto (e não link_preview_options para URL longa):
    o servidor de preview do Telegram tem fetch próprio (User-Agent, faixa de
    IP, hotlink protection diferentes do nosso HEAD/GET), então URL válida
    no nosso lado pode silenciosamente não renderizar no preview. sendPhoto
    força o Telegram a baixar e exibir — sem lacuna silenciosa.
    """
    caption = post["caption_html"]
    image_ref = post.get("image_url")
    sent_ids: list[int] = []

    if image_ref:
        if len(caption) <= PHOTO_CAPTION_LIMIT:
            sent: Message = await bot.send_photo(
                chat_id=chat_id, photo=image_ref, caption=caption
            )
            sent_ids.append(sent.message_id)
            return sent_ids

        logger.warning(
            "caption_over_limit length=%d limit=%d — enviando 2 mensagens (foto + texto)",
            len(caption),
            PHOTO_CAPTION_LIMIT,
        )
        photo_msg = await bot.send_photo(chat_id=chat_id, photo=image_ref)
        sent_ids.append(photo_msg.message_id)
        text_msg = await bot.send_message(
            chat_id=chat_id,
            text=caption,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        sent_ids.append(text_msg.message_id)
        return sent_ids

    sent = await bot.send_message(
        chat_id=chat_id,
        text=caption,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    sent_ids.append(sent.message_id)
    return sent_ids
