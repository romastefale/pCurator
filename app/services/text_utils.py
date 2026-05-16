import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}


def normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_title(value: str | None) -> str:
    text = normalize_space(value).lower()
    text = re.sub(r"[^\w\sÀ-ÿ-]", "", text)
    return normalize_space(text)


def stable_hash(value: str | None) -> str:
    text = normalize_space(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in TRACKING_KEYS or key.startswith(TRACKING_PREFIXES):
            continue
        query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))
