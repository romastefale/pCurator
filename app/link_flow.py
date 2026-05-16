import re

from aiogram import Router
from aiogram.types import Message

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

    item_id = await save_item(
        settings.database_path,
        canonical_url=canonical_url,
        title=None,
        source_name=None,
        text_hash=stable_hash(canonical_url),
    )

    await message.answer(
        "<b>Link recebido.</b>\n\n"
        f"Item #{item_id} salvo para curadoria manual.\n"
        "Próxima etapa: análise, imagem e escolha de canal.",
        parse_mode="HTML",
    )
