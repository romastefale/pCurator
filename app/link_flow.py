import re

from aiogram import Router
from aiogram.types import Message

from app.services.extractor import extract_item
from app.services.fetcher import fetch_html
from app.services.text_utils import clean_url, stable_hash
from app.settings import get_settings
from app.storage.items import save_item

router = Router()

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@router.message()
async def handle_possible_link(message: Message) -> None:
    if not message.text:
        return

    match = URL_RE.search(message.text)
    if not match:
        return

    raw_url = match.group(0).strip()
    canonical_url = clean_url(raw_url)
    settings = get_settings()

    await message.answer("🔎 Link recebido. Extraindo matéria...")

    html = await fetch_html(canonical_url)
    item = extract_item(canonical_url, html)

    title = item.title if item else None
    source_name = item.source if item else None
    image_url = item.image_url if item else None
    text_hash = stable_hash(item.text if item and item.text else canonical_url)

    item_id = await save_item(
        settings.database_path,
        canonical_url=canonical_url,
        title=title,
        source_name=source_name,
        image_url=image_url,
        text_hash=text_hash,
    )

    if item:
        image_status = "imagem encontrada" if item.image_url else "sem imagem confiável ainda"
        await message.answer(
            "<b>Matéria extraída.</b>\n\n"
            f"Item #{item_id}\n"
            f"Fonte: {item.source}\n"
            f"Título: {item.title}\n"
            f"Status: {image_status}\n\n"
            "Próxima etapa: escolha de canal e geração editorial.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        "<b>Link salvo, mas a extração falhou.</b>\n\n"
        f"Item #{item_id}\n"
        "Será necessário revisar manualmente ou tentar outro link.",
        parse_mode="HTML",
    )
