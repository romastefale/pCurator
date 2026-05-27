import re

from app.types import ArticleIntake, PublicPost

FORBIDDEN_TERMS = (
    "prévia editorial",
    "via:",
    "oferecido por",
    "por redação",
    "atualizado",
    "publicado",
    "continua após a publicidade",
)

SOURCE_TITLE_SUFFIX_RE = re.compile(r"\s+[|\-–—]\s+(G1|UOL|CNN|GE|Folha|Estadão|BBC|Reuters|AFP)\s*$", re.IGNORECASE)


def _contains_forbidden(value: str) -> list[str]:
    lowered = value.lower()
    return [term for term in FORBIDDEN_TERMS if term in lowered]


def _too_similar_to_extraction(post_body: str, article_text: str) -> bool:
    body = re.sub(r"\s+", " ", post_body.lower()).strip()
    source = re.sub(r"\s+", " ", article_text.lower()).strip()
    if not body or not source:
        return False
    return body[:180] in source[:800]


def validate_public_post(post: PublicPost, article: ArticleIntake) -> tuple[bool, list[str]]:
    issues: list[str] = []
    combined = "\n".join([post.title, post.subtitle, post.body])

    forbidden = _contains_forbidden(combined)
    if forbidden:
        issues.append("forbidden_terms:" + ",".join(forbidden))

    if SOURCE_TITLE_SUFFIX_RE.search(post.title):
        issues.append("source_suffix_in_title")

    if len(post.hashtags) < 3 or len(post.hashtags) > 4:
        issues.append("invalid_hashtag_count")

    if len(post.title.strip()) < 12:
        issues.append("title_too_short")

    if len(post.subtitle.strip()) < 20:
        issues.append("subtitle_too_short")

    body_len = len(post.body.strip())
    if body_len < 120:
        issues.append("body_too_short")
    # 580 vem do orçamento de 1024 chars do sendPhoto.caption descontando
    # title (120) + subtitle (180) + hashtags (~80) + tags HTML (~58) + \n\n (6).
    if body_len > 580:
        issues.append("body_too_long")

    if _too_similar_to_extraction(post.body, article.clean_text):
        issues.append("body_too_similar_to_extraction")

    if not post.source_url.strip():
        issues.append("missing_source_url")

    return len(issues) == 0, issues


def force_review(post: PublicPost, issues: list[str]) -> PublicPost:
    """Sinaliza problemas de validação local como notas — não bloqueia publicação.
    A decisão final é sempre do curador humano."""
    post.needs_review = True
    post.quality_notes.extend(issues)
    return post
