import logging

from aiogram import Bot

from app.services.article_extractor_v2 import extract_article_intake
from app.services.fetcher import fetch_html
from app.services.image_validation import head_confirms_image
from app.services.linkpreview import fetch_linkpreview
from app.services.regenerator import UNIFIED_TONE, regenerate_post_for_channel
from app.services.text_utils import clean_url, stable_hash
from app.storage.items import find_duplicate_item, save_item_with_flag
from app.storage.posts import save_post
from app.types import ArticleIntake

logger = logging.getLogger(__name__)


async def create_auto_draft(
    bot: Bot,
    *,
    database_path: str,
    raw_url: str,
    linkpreview_key: str | None = None,
    default_channel: str = UNIFIED_TONE,
    discovered_topic: str | None = None,
) -> tuple[int, ArticleIntake] | None:
    """Cria um rascunho a partir de URL descoberta automaticamente.

    Espelha o pipeline de link_flow.handle_possible_link mas sem dependência
    de Message (roda em background). Devolve (post_id, intake) ou None se
    extração falhou ou item já é duplicado."""
    canonical_url = clean_url(raw_url)
    html = await fetch_html(canonical_url)
    intake = extract_article_intake(canonical_url, html)

    if not intake or not intake.image_url:
        preview_data = await fetch_linkpreview(canonical_url, linkpreview_key)
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
        logger.info(
            "auto_draft_extraction_failed topic=%s url=%s", discovered_topic, canonical_url
        )
        return None

    if intake.image_url and not await head_confirms_image(intake.image_url):
        intake.image_url = None

    text_hash = stable_hash(intake.clean_text if intake.clean_text else canonical_url)

    duplicate = await find_duplicate_item(
        database_path, canonical_url=canonical_url, text_hash=text_hash,
    )
    if duplicate:
        logger.info(
            "auto_draft_duplicate topic=%s url=%s existing_id=%s",
            discovered_topic, canonical_url, duplicate["id"],
        )
        return None

    item_id, was_new = await save_item_with_flag(
        database_path,
        canonical_url=canonical_url,
        title=intake.clean_title,
        source_name=intake.source,
        image_url=intake.image_url,
        extracted_text=intake.clean_text,
        text_hash=text_hash,
        auto_drafted=True,
    )
    if not was_new:
        # Corrida vs outro ciclo de discovery ou flow manual: artigo já existia
        # quando o INSERT rodou. Não cria post duplicado pro mesmo article_id.
        logger.info(
            "auto_draft_race_lost topic=%s url=%s existing_id=%s",
            discovered_topic, canonical_url, item_id,
        )
        return None

    post_id = await save_post(
        database_path,
        article_id=item_id,
        channel_slug=default_channel,
        caption_html="Rascunho automático — gerando legenda final...",
        image_url=intake.image_url,
    )

    metadata = await regenerate_post_for_channel(
        database_path, post_id=post_id, channel_slug=default_channel, bot=bot,
    )
    if not metadata.get("ok"):
        logger.warning(
            "auto_draft_regenerate_failed post=%s notes=%s",
            post_id, metadata.get("quality_notes"),
        )

    return post_id, intake
