import re

from aiogram import F, Router
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.services.article_extractor_v2 import extract_article_intake
from app.services.fetcher import fetch_html
from app.services.linkpreview import fetch_linkpreview
from app.services.risk import assess_link_risk
from app.services.text_utils import clean_url, stable_hash
from app.settings import get_settings
from app.storage.items import find_duplicate_item, save_item
from app.storage.posts import save_post
from app.storage.session import set_active_post
from app.types import ArticleIntake
from app.ui import channel_keyboard, duplicate_keyboard

router = Router()

URL_PATTERN = r"https?://\S+"
URL_RE = re.compile(URL_PATTERN, re.IGNORECASE)


@router.message(F.text.regexp(URL_PATTERN))
async def handle_possible_link(message: Message) -> None:
    match = URL_RE.search(message.text or "")
    if not match:
        return

    if await reject_message_if_not_owner(message):
        return

    raw_url = match.group(0).strip()
    canonical_url = clean_url(raw_url)
    settings = get_settings()

    await message.answer("🔎 Link recebido. Extraindo matéria...")

    html = await fetch_html(canonical_url)
    intake = extract_article_intake(canonical_url, html)

    if not intake or not intake.image_url:
        preview_data = await fetch_linkpreview(canonical_url, settings.linkpreview_key)
        if preview_data:
            if intake:
                if not intake.image_url:
                    intake.image_url = preview_data.get("image")
            else:
                intake = ArticleIntake(
                    url=canonical_url,
                    raw_title=preview_data.get("title") or "Sem título",
                    clean_title=preview_data.get("title") or "Sem título",
                    clean_text=preview_data.get("description") or "",
                    source=preview_data.get("site_name") or "Web",
                    image_url=preview_data.get("image"),
                )

    if not intake:
        await message.answer(
            "<b>Extração falhou.</b>\n\n"
            "Não consegui obter título ou texto suficiente para criar rascunho.",
            parse_mode="HTML",
        )
        return

    text_hash = stable_hash(intake.clean_text if intake.clean_text else canonical_url)

    duplicate = await find_duplicate_item(
        settings.database_path,
        canonical_url=canonical_url,
        text_hash=text_hash,
    )
    if duplicate:
        await message.answer(
            "⚠️ Matéria potencialmente duplicada detectada.\n\n"
            f"Item existente: #{duplicate['id']}\n"
            f"Título: {duplicate.get('title') or 'Sem título'}\n"
            f"Fonte: {duplicate.get('source_name') or 'Web'}\n\n"
            "Quer gerar um novo rascunho mesmo assim?",
            reply_markup=duplicate_keyboard(int(duplicate["id"])),
        )
        return

    risk = assess_link_risk(intake.clean_title, intake.clean_text)
    if risk["should_hold"]:
        flags = ", ".join(risk["flags"]) or "sem detalhes"
        await message.answer(
            "⚠️ Conteúdo marcado para revisão manual forte.\n\n"
            f"Risco: {risk['score']}\n"
            f"Sinais: {flags}"
        )

    item_id = await save_item(
        settings.database_path,
        canonical_url=canonical_url,
        title=intake.clean_title,
        source_name=intake.source,
        image_url=intake.image_url,
        extracted_text=intake.clean_text,
        text_hash=text_hash,
    )

    post_id = await save_post(
        settings.database_path,
        article_id=item_id,
        channel_slug="manual",
        caption_html="Rascunho interno criado. Escolha C1 ou C2 para gerar o post editorial final.",
        image_url=intake.image_url,
    )
    await set_active_post(
        settings.database_path,
        user_id=message.from_user.id,
        post_id=post_id,
        mode="review",
    )

    image_status = "imagem encontrada" if intake.image_url else "sem imagem confiável ainda"
    await message.answer(
        "<b>Matéria recebida para curadoria.</b>\n\n"
        f"Item #{item_id}\n"
        f"Post #{post_id}\n"
        f"Fonte: {intake.source}\n"
        f"Título limpo: {intake.clean_title}\n"
        f"Texto extraído: {len(intake.clean_text)} caracteres\n"
        f"Imagem: {image_status}\n"
        f"Risco editorial: {risk['score']}\n\n"
        "Escolha o canal para gerar a legenda editorial final.",
        parse_mode="HTML",
        reply_markup=channel_keyboard(),
    )
