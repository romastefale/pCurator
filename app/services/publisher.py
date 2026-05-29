import logging

from aiogram import Bot
from aiogram.types import InputMediaPhoto, LinkPreviewOptions, Message

from app.storage.posts import post_image_refs

logger = logging.getLogger(__name__)

PHOTO_CAPTION_LIMIT = 1024


async def publish_post(bot: Bot, chat_id: int, post: dict) -> list[int]:
    """Publica/preview o post. Retorna a lista de message_ids enviados.
    Estratégia (Bot API 10.0):
      - sem imagem: 1 sendMessage (sem preview).
      - 1 imagem + caption <=1024: 1 sendPhoto com caption.
      - 2 a 4 imagens + caption <=1024: 1 sendMediaGroup (álbum), caption na 1ª foto.
      - caption >1024 (qualquer caso com imagem): foto(s) sem caption + sendMessage
        com texto completo. Vale para URL HTTP e para file_id.

    Por que sempre sendPhoto/sendMediaGroup (e não link_preview_options para URL
    longa): o servidor de preview do Telegram tem fetch próprio (User-Agent, faixa
    de IP, hotlink protection diferentes do nosso HEAD/GET), então URL válida no
    nosso lado pode silenciosamente não renderizar no preview. Enviar a foto força
    o Telegram a baixar e exibir — sem lacuna silenciosa.
    """
    caption = post["caption_html"]
    image_refs = post_image_refs(post)
    sent_ids: list[int] = []

    if not image_refs:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=caption,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        sent_ids.append(sent.message_id)
        return sent_ids

    caption_fits = len(caption) <= PHOTO_CAPTION_LIMIT
    if not caption_fits:
        logger.warning(
            "caption_over_limit length=%d limit=%d — enviando imagem(ns) + texto à parte",
            len(caption),
            PHOTO_CAPTION_LIMIT,
        )

    # Álbum (2 a 4 fotos): sendMediaGroup, caption só na primeira (se couber).
    if len(image_refs) > 1:
        media = [
            InputMediaPhoto(
                media=ref,
                caption=caption if (i == 0 and caption_fits) else None,
            )
            for i, ref in enumerate(image_refs)
        ]
        album = await bot.send_media_group(chat_id=chat_id, media=media)
        sent_ids.extend(msg.message_id for msg in album)
        if not caption_fits:
            text_msg = await bot.send_message(
                chat_id=chat_id,
                text=caption,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            sent_ids.append(text_msg.message_id)
        return sent_ids

    # Foto única.
    image_ref = image_refs[0]
    if caption_fits:
        sent: Message = await bot.send_photo(
            chat_id=chat_id, photo=image_ref, caption=caption
        )
        sent_ids.append(sent.message_id)
        return sent_ids

    photo_msg = await bot.send_photo(chat_id=chat_id, photo=image_ref)
    sent_ids.append(photo_msg.message_id)
    text_msg = await bot.send_message(
        chat_id=chat_id,
        text=caption,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    sent_ids.append(text_msg.message_id)
    return sent_ids
