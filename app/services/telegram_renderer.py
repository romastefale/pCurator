import html
import re
import unicodedata

from app.types import PublicPost


def _strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _clean_hashtag(value: str) -> str:
    ascii_value = _strip_accents(value)
    cleaned = "".join(
        ch for ch in ascii_value if ch.isascii() and (ch.isalnum() or ch == "_")
    )
    return cleaned.strip("#")


def _compact_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _format_body_lines(body: str) -> str:
    text = _compact_inline(body)
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return html.escape(text)
    return "\n\n".join(html.escape(s) for s in sentences)


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
    body_lines = _format_body_lines(post.body)

    sections: list[str] = []
    if hashtags_line:
        sections.append(hashtags_line)
    if title:
        sections.append(f"<b>{title}</b>")
    if subtitle:
        sections.append(f"<i>{subtitle}</i>")
    if body_lines:
        sections.append(f"<blockquote expandable><i>{body_lines}</i></blockquote>")

    text = "\n\n".join(sections)
    return _normalize_post_spacing(text)
