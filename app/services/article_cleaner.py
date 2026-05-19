import re

SOURCE_SUFFIX_RE = re.compile(r"\s+[|\-–—]\s+(G1|UOL|CNN|GE|Folha|Estadão|BBC|Reuters|AFP)\s*$", re.IGNORECASE)
BOILERPLATE_PATTERNS = (
    r"^Oferecido por\s+",
    r"^Por\s+Redação\s+[^\n]*",
    r"\bAtualizado\s+\d{1,2}/\d{1,2}/\d{4}[^.\n]*",
    r"\bPublicado\s+\d{1,2}/\d{1,2}/\d{4}[^.\n]*",
    r"\bcompartilhe\b",
    r"\bassine\b",
    r"\bcontinua após a publicidade\b",
)


def normalize_title(title: str | None) -> str:
    value = re.sub(r"\s+", " ", title or "").strip()
    value = SOURCE_SUFFIX_RE.sub("", value).strip()
    return value


def clean_extracted_text(text: str | None) -> str:
    value = text or ""
    value = re.sub(r"\s+", " ", value).strip()

    for pattern in BOILERPLATE_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()

    value = re.sub(r"\s+", " ", value).strip()
    return value


def compact_source_name(source: str | None) -> str:
    value = re.sub(r"\s+", " ", source or "Web").strip()
    return value or "Web"
