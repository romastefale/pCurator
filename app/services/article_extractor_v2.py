import trafilatura

from app.services.article_cleaner import clean_extracted_text, compact_source_name, normalize_title
from app.services.extractor import extract_item
from app.types import ArticleIntake


def extract_article_intake(url: str, html: str) -> ArticleIntake | None:
    if not html:
        return None

    fallback = extract_item(url, html)

    extracted = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        deduplicate=True,
        favor_precision=True,
        output_format="txt",
    )

    raw_title = fallback.title if fallback else "Sem título"
    source = compact_source_name(fallback.source if fallback else "Web")
    image_url = fallback.image_url if fallback else None

    clean_title = normalize_title(raw_title)
    clean_text = clean_extracted_text(extracted or (fallback.text if fallback else ""))

    if not clean_title and not clean_text:
        return None

    return ArticleIntake(
        url=url,
        raw_title=raw_title,
        clean_title=clean_title or raw_title or "Sem título",
        clean_text=clean_text,
        source=source,
        image_url=image_url,
    )
