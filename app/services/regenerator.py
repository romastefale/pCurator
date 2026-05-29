import logging

from aiogram import Bot

from app.services.article_cleaner import clean_extracted_text, compact_source_name, normalize_title
from app.services.image_validation import head_confirms_image
from app.services.mira_bridge import request_mira_public_post
from app.services.post_validator import force_review, validate_public_post
from app.services.structured_editor import generate_structured_public_post
from app.services.telegram_renderer import render_public_post_html
from app.storage.articles import get_article_for_post
from app.storage.posts import update_post_caption, update_post_image
from app.types import ArticleIntake

logger = logging.getLogger(__name__)

# Tom editorial ÚNICO (neutro: claro e direto, nem pop demais nem formal demais).
# Substitui a antiga escolha c1/c2; o mesmo tom serve pros dois canais e a escolha
# de canal vira só destino de publicação. Definido aqui (orquestrador de geração)
# pra ser importável por todo o pipeline sem dependências pesadas.
UNIFIED_TONE = "geral"


def _engine_from_notes(quality_notes: list[str]) -> str:
    if "mira_used" in quality_notes:
        return "mira"
    if any(note.startswith("openai_") or note.startswith("fallback_") for note in quality_notes):
        return "fallback"
    return "openai"


async def regenerate_post_for_channel(
    database_path: str,
    *,
    post_id: int,
    channel_slug: str,
    risk_score: int = 100,
    bot: Bot | None = None,
) -> dict:
    article = await get_article_for_post(database_path, post_id)
    if not article:
        return {"ok": False, "engine": "none", "quality_notes": ["article_not_found"]}

    raw_title = article.get("title") or "Sem título"
    extracted_text = article.get("extracted_text") or ""

    intake = ArticleIntake(
        url=article.get("canonical_url") or "",
        raw_title=raw_title,
        clean_title=normalize_title(raw_title),
        clean_text=clean_extracted_text(extracted_text),
        source=compact_source_name(article.get("source_name") or "Web"),
        image_url=article.get("image_url"),
    )

    if bot is not None:
        try:
            public_post = await request_mira_public_post(bot, intake, channel_slug, risk_score=risk_score)
        except Exception as exc:
            logger.exception("Mira editorial generation failed: %s", type(exc).__name__)
            public_post = await generate_structured_public_post(intake, channel_slug, risk_score=risk_score)
            public_post.quality_notes.append(f"mira_error:{type(exc).__name__}")
    else:
        public_post = await generate_structured_public_post(intake, channel_slug, risk_score=risk_score)
        public_post.quality_notes.append("mira_unavailable:no_bot")

    is_valid, issues = validate_public_post(public_post, intake)
    if not is_valid:
        public_post = force_review(public_post, issues)

    caption_html = render_public_post_html(public_post)
    await update_post_caption(database_path, post_id, caption_html)

    if intake.image_url:
        if await head_confirms_image(intake.image_url):
            await update_post_image(database_path, post_id, intake.image_url)
        else:
            await update_post_image(database_path, post_id, None)
            public_post.quality_notes.append("image_head_invalid")

    quality_notes = list(public_post.quality_notes)
    engine = _engine_from_notes(quality_notes)
    return {
        "ok": True,
        "engine": engine,
        "used_mira": engine == "mira",
        "used_openai": engine == "openai",
        "needs_review": public_post.needs_review,
        "quality_notes": quality_notes,
    }
