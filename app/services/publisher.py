from aiogram import Bot
from aiogram.types import LinkPreviewOptions, Message

PHOTO_CAPTION_LIMIT = 1024


def _is_http_url(value: str | None) -> bool:
    return bool(value) and (value.startswith("http://") or value.startswith("https://"))


async def publish_post(bot: Bot, chat_id: int, post: dict) -> list[int]:
    """Publica/preview o post. Retorna a lista de message_ids enviados.
    Estratégia (Bot API 9.5):
      - sem imagem: 1 mensagem (sendMessage, sem preview).
      - imagem + caption <=1024: 1 mensagem (sendPhoto com caption).
      - imagem URL HTTP + caption >1024: 1 mensagem (sendMessage com
        link_preview_options.prefer_large_media). Mantém tudo num bloco só.
      - imagem file_id + caption >1024: 2 mensagens (sendPhoto sem caption +
        sendMessage com texto completo). Evita perda silenciosa por truncamento.
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

        if _is_http_url(image_ref):
            sent = await bot.send_message(
                chat_id=chat_id,
                text=caption,
                link_preview_options=LinkPreviewOptions(
                    url=image_ref,
                    prefer_large_media=True,
                    show_above_text=True,
                ),
            )
            sent_ids.append(sent.message_id)
            return sent_ids

        # file_id + caption longa: 2 mensagens, sem perda de informação.
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
