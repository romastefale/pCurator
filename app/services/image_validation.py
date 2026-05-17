from urllib.parse import urlparse

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
