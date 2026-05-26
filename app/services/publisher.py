from aiogram import Bot
from aiogram.types import LinkPreviewOptions

PHOTO_CAPTION_LIMIT = 1024
TRUNCATION_MARK = "\n…"


def _is_http_url(value: str | None) -> bool:
    return bool(value) and (value.startswith("http://") or value.startswith("https://"))


def _truncate_caption_for_photo(caption: str) -> str:
    """Trunca a legenda preservando blockquote/HTML válido para caber em <=1024.
    Usado apenas em caso extremo (imagem file_id + legenda longa), mantendo a
    publicação em uma única mensagem (foto+legenda)."""
    if len(caption) <= PHOTO_CAPTION_LIMIT:
        return caption

    limit = PHOTO_CAPTION_LIMIT - len(TRUNCATION_MARK)
    closing = ""
    body_open = "<blockquote expandable><i>"
    if body_open in caption:
        closing = "</i></blockquote>"

    available = limit - len(closing)
    head = caption[:available]
    # quebra preferencialmente em fim de frase / linha
    for sep in ("\n", ". ", "! ", "? "):
        idx = head.rfind(sep)
        if idx > available * 0.5:
            head = head[: idx + len(sep)].rstrip()
            break
    return head + TRUNCATION_MARK + closing


async def publish_post(bot: Bot, chat_id: int, post: dict) -> None:
    caption = post["caption_html"]
    image_ref = post.get("image_url")

    if image_ref:
        if len(caption) <= PHOTO_CAPTION_LIMIT:
            # Caso ideal: imagem + legenda em uma única mensagem (foto com caption).
            await bot.send_photo(chat_id=chat_id, photo=image_ref, caption=caption)
            return

        if _is_http_url(image_ref):
            # Legenda longa, mas imagem é URL HTTP: usa link preview grande acima do texto,
            # mantendo tudo numa mensagem só.
            await bot.send_message(
                chat_id=chat_id,
                text=caption,
                link_preview_options=LinkPreviewOptions(
                    url=image_ref,
                    prefer_large_media=True,
                    show_above_text=True,
                ),
            )
            return

        # Legenda longa + imagem é file_id do Telegram: não dá pra usar link preview
        # (file_id não é URL pública). Mantém 1 mensagem só truncando a legenda
        # no limite de 1024 caracteres, em quebra de frase.
        await bot.send_photo(
            chat_id=chat_id,
            photo=image_ref,
            caption=_truncate_caption_for_photo(caption),
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
