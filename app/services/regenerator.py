from app.services.editor import generate_editorial_post
from app.storage.articles import get_article_for_post
from app.storage.posts import update_post_caption, update_post_image
from app.types import ItemData


async def regenerate_post_for_channel(
    database_path: str,
    *,
    post_id: int,
    channel_slug: str,
) -> bool:
    article = await get_article_for_post(database_path, post_id)
    if not article:
        return False

    item = ItemData(
        url=article.get("canonical_url") or "",
        title=article.get("title") or "Sem título",
        text=article.get("extracted_text") or article.get("title") or "",
        source=article.get("source_name") or "Web",
        image_url=article.get("image_url"),
    )

    rendered = await generate_editorial_post(item, channel_slug)
    await update_post_caption(database_path, post_id, rendered.text)
    if rendered.image_url:
        await update_post_image(database_path, post_id, rendered.image_url)
    return True
