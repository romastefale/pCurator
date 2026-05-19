import re

from aiogram import Router
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.services.extractor import extract_item
from app.services.fetcher import fetch_html
from app.services.formatting import build_caption
from app.services.linkpreview import fetch_linkpreview
from app.services.preview import send_post_preview
from app.services.text_utils import clean_url, stable_hash
from app.settings import get_settings
from app.storage.items import save_item
from app.storage.posts import get_post, save_post
from app.storage.session import set_active_post
from app.types import ItemData
from app.ui import channel_keyboard

router = Router()

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _preview_body(text: str) -> str:
    if not text:
        return "Texto ainda pendente de revisão editorial."
    return text[:360].strip()


@router.message()
async def handle_possible_link(message: Message) -> None:
    if not message.text:
        return

    match = URL_RE.search(message.text)
    if not match:
        return

    if await reject_message_if_not_owner(message):
        return

    raw_url = match.group(0).strip()
    canonical_url = clean_url(raw_url)
    settings = get_settings()

    await message.answer("🔎 Link recebido. Extraindo matéria...")

    html = await fetch_html(canonical_url)
    item = extract_item(canonical_url, html)

    if not item or not item.image_url:
        preview_data = await fetch_linkpreview(canonical_url, settings.linkpreview_key)
        if preview_data:
            item = ItemData(
                url=canonical_url,
                title=(item.title if item else None) or preview_data.get("title") or "Sem título",
                text=(item.text if item else "") or preview_data.get("description") or "",
                source=(item.source if item else None) or preview_data.get("site_name") or "Web",
                image_url=(item.image_url if item else None) or preview_data.get("image"),
            )

    title = item.title if item else None
    source_name = item.source if item else None
    image_url = item.image_url if item else None
    extracted_text = item.text if item else None
    text_hash = stable_hash(extracted_text if extracted_text else canonical_url)

    item_id = await save_item(
        settings.database_path,
        canonical_url=canonical_url,
        title=title,
        source_name=source_name,
        image_url=image_url,
        extracted_text=extracted_text,
        text_hash=text_hash,
    )

    if item:
        caption = build_caption(
            hashtags=["Notícia", "Atualidade", "Curadoria"],
            title=item.title,
            subtitle="Prévia editorial gerada a partir da matéria original.",
            body=_preview_body(item.text),
            source_name=item.source,
            url=canonical_url,
        )
        post_id = await save_post(
            settings.database_path,
            article_id=item_id,
            channel_slug="manual",
            caption_html=caption,
            image_url=item.image_url,
        )
        await set_active_post(
            settings.database_path,
            user_id=message.from_user.id,
            post_id=post_id,
            mode="review",
        )

        image_status = "imagem encontrada" if item.image_url else "sem imagem confiável ainda"
        await message.answer(
            "<b>Matéria extraída.</b>\n\n"
            f"Item #{item_id}\n"
            f"Post #{post_id}\n"
            f"Fonte: {item.source}\n"
            f"Título: {item.title}\n"
            f"Status: {image_status}\n\n"
            "Prévia abaixo. Depois escolha o canal para continuar.",
            parse_mode="HTML",
        )

        post = await get_post(settings.database_path, post_id)
        if post:
            await send_post_preview(message.bot, message.chat.id, post)

        await message.answer("Escolha o canal para continuar.", reply_markup=channel_keyboard())
        return

    await message.answer(
        "<b>Link salvo, mas a extração falhou.</b>\n\n"
        f"Item #{item_id}\n"
        "Será necessário revisar manualmente ou tentar outro link.",
        parse_mode="HTML",
    )
