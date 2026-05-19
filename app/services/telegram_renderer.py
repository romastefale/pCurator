import html

from app.types import PublicPost


def _clean_hashtag(value: str) -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch == "_")
    return cleaned.strip("#")


def render_public_post_html(post: PublicPost) -> str:
    hashtags = [_clean_hashtag(tag) for tag in post.hashtags]
    hashtags = [tag for tag in hashtags if tag]
    hashtags_line = " ".join(f"#{tag}" for tag in hashtags[:4])

    title = html.escape(post.title.strip())
    subtitle = html.escape(post.subtitle.strip())
    body = html.escape(post.body.strip())
    source_url = html.escape(post.source_url.strip(), quote=True)

    parts = [
        hashtags_line,
        "",
        f"<b>{title}</b>",
        "",
        f"<i>{subtitle}</i>",
        "",
        f"<blockquote><i>{body}</i></blockquote>",
    ]

    if source_url:
        parts.extend(["", f"<a href=\"{source_url}\">&#8203;</a>"])

    return "\n".join(parts).strip()
