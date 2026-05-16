from html import escape


def build_caption(
    hashtags: list[str],
    title: str,
    subtitle: str,
    body: str,
    source_name: str,
    url: str,
) -> str:
    clean_tags = [tag if tag.startswith("#") else f"#{tag}" for tag in hashtags[:3]]
    while len(clean_tags) < 3:
        clean_tags.append("#Notícia")

    return (
        f"{' '.join(clean_tags)}\n\n"
        f"<b>{escape(title)}</b>\n\n"
        f"<i>{escape(subtitle)}</i>\n\n"
        f"<blockquote><i>{escape(body)}</i></blockquote>\n\n"
        f"<i>Via: {escape(source_name)}.</i>"
        f"<a href=\"{escape(url, quote=True)}\">&#8203;</a>"
    )
