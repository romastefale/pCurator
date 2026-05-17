import json
import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.image_validation import is_probably_valid_image_url
from app.types import ItemData


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _meta_content(soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None) -> str | None:
    tag = None
    if property_name:
        tag = soup.find("meta", property=property_name)
    if tag is None and name:
        tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _image_from_jsonld(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            found = _image_from_jsonld(item)
            if found:
                return found
        return None

    if not isinstance(value, dict):
        return None

    image = value.get("image")
    if isinstance(image, str):
        return image.strip()
    if isinstance(image, list):
        for item in image:
            if isinstance(item, str):
                return item.strip()
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"]).strip()
    if isinstance(image, dict) and image.get("url"):
        return str(image["url"]).strip()

    graph = value.get("@graph")
    if graph:
        return _image_from_jsonld(graph)

    return None


def _extract_image_url(soup: BeautifulSoup) -> str | None:
    candidates: list[str] = []

    for property_name, name in (
        ("og:image", None),
        ("og:image:secure_url", None),
        (None, "twitter:image"),
        (None, "twitter:image:src"),
    ):
        found = _meta_content(soup, property_name=property_name, name=name)
        if found:
            candidates.append(found)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        found = _image_from_jsonld(payload)
        if found:
            candidates.append(found)

    article = soup.find("article")
    if article:
        for image in article.find_all("img"):
            if image.get("src"):
                candidates.append(image["src"].strip())

    for candidate in candidates:
        if is_probably_valid_image_url(candidate):
            return candidate

    return None


def extract_item(url: str, html: str) -> ItemData | None:
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "aside"]):
        tag.decompose()

    title = _meta_content(soup, property_name="og:title") or ""
    if not title and soup.title and soup.title.string:
        title = soup.title.string

    source = _meta_content(soup, property_name="og:site_name") or "Web"
    image_url = _extract_image_url(soup)

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
