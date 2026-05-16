import re

from bs4 import BeautifulSoup

from app.types import ItemData


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_item(url: str, html: str) -> ItemData | None:
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]
    elif soup.title and soup.title.string:
        title = soup.title.string

    source = "Web"
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content"):
        source = site_name["content"]

    image_url = None
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        image_url = og_image["content"].strip()

    paragraphs = soup.find_all("p")
    text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
    text = _clean_text(text)

    title = _clean_text(title)
    source = _clean_text(source)

    if not title and not text:
        return None

    return ItemData(
        url=url,
        title=title or "Sem título",
        text=text,
        source=source or "Web",
        image_url=image_url,
    )
