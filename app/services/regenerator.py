from app.services.article_cleaner import clean_extracted_text, compact_source_name, normalize_title
from app.services.post_validator import force_review, validate_public_post
from app.services.structured_editor import generate_structured_public_post
from app.services.telegram_renderer import render_public_post_html
from app.storage.articles import get_article_for_post
from app.storage.posts import update_post_caption, update_post_image
from app.types import ArticleIntake


async def regenerate_post_for_channel(
    database_path: str,
    *,
    post_id: int,
    channel_slug: str,
    risk_score: int = 100,
) -> bool:
    article = await get_article_for_post(database_path, post_id)
    if not article:
        return False

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

    public_post = await generate_structured_public_post(intake, channel_slug, risk_score=risk_score)
    is_valid, issues = validate_public_post(public_post, intake)
    if not is_valid:
        public_post = force_review(public_post, issues)

    caption_html = render_public_post_html(public_post)
    await update_post_caption(database_path, post_id, caption_html)

    if intake.image_url:
        await update_post_image(database_path, post_id, intake.image_url)

    return True
