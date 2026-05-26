import html
import re

from app.types import PublicPost


def _clean_hashtag(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch == "_")
    return cleaned.strip("#")


def _compact_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_post_spacing(value: str) -> str:
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def render_public_post_html(post: PublicPost) -> str:
    hashtags = [_clean_hashtag(tag) for tag in post.hashtags]
    hashtags = [tag for tag in hashtags if tag]
    hashtags_line = " ".join(f"#{tag}" for tag in hashtags[:4])

    title = html.escape(_compact_inline(post.title))
    subtitle = html.escape(_compact_inline(post.subtitle))
    body = html.escape(_compact_inline(post.body))

    sections = [
        hashtags_line,
        f"<b>{title}</b>",
        f"<i>{subtitle}</i>",
        f"<blockquote><i>{body}</i></blockquote>",
    ]

    text = "\n\n".join(section for section in sections if section.strip())

    return _normalize_post_spacing(text)
