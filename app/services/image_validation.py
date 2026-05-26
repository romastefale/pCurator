import asyncio
import logging
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

BAD_IMAGE_TERMS = (
    "logo",
    "icon",
    "favicon",
    "sprite",
    "avatar",
    "placeholder",
    "default",
    "blank",
    "transparent",
)

GOOD_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
)


def is_probably_valid_image_url(image_url: str | None) -> bool:
    if not image_url:
        return False

    parsed = urlparse(image_url.strip())
    if parsed.scheme not in {"http", "https"}:
        return False

    lowered = image_url.lower()
    if any(term in lowered for term in BAD_IMAGE_TERMS):
        return False

    path = parsed.path.lower()
    if path.endswith(GOOD_EXTENSIONS):
        return True

    return any(ext in lowered for ext in GOOD_EXTENSIONS)


_HEAD_REJECTED_STATUSES = {403, 405, 501}


async def head_confirms_image(image_url: str | None, *, timeout: float = 5.0) -> bool:
    """Confirma que a URL aponta pra bytes de imagem (Content-Type image/*).
    Tenta HEAD primeiro; se o servidor recusar HEAD (403/405/501) ou falhar,
    cai pra GET com Range: bytes=0-0 — assim respeitamos servidores que só
    aceitam GET sem baixar a imagem inteira. Retorna False em qualquer erro:
    falha explícita, sem fallback silencioso. Necessário porque sendPhoto e
    link_preview do Telegram silenciosamente não renderizam URLs quebradas
    (og:image inválido, paywall, redirect pra HTML, 404)."""
    if not image_url:
        return False
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            try:
                async with session.head(image_url, allow_redirects=True) as response:
                    if response.status < 400:
                        content_type = (response.headers.get("Content-Type") or "").lower()
                        return content_type.startswith("image/")
                    if response.status not in _HEAD_REJECTED_STATUSES:
                        return False
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.info("image_head_failed url=%s error=%s", image_url, type(exc).__name__)
            # Fallback: GET parcial — alguns CDNs/servidores não respondem HEAD.
            async with session.get(
                image_url,
                allow_redirects=True,
                headers={"Range": "bytes=0-0"},
            ) as response:
                if response.status >= 400 and response.status != 416:
                    return False
                content_type = (response.headers.get("Content-Type") or "").lower()
                return content_type.startswith("image/")
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.info("image_get_failed url=%s error=%s", image_url, type(exc).__name__)
        return False
