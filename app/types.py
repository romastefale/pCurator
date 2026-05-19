from dataclasses import dataclass, field


@dataclass(slots=True)
class ItemData:
    url: str
    title: str
    text: str
    source: str
    image_url: str | None = None


@dataclass(slots=True)
class ArticleIntake:
    url: str
    raw_title: str
    clean_title: str
    clean_text: str
    source: str
    image_url: str | None = None


@dataclass(slots=True)
class PublicPost:
    hashtags: list[str] = field(default_factory=list)
    title: str = ""
    subtitle: str = ""
    body: str = ""
    source_url: str = ""
    publishable: bool = True
    needs_review: bool = False
    quality_notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RenderedPost:
    text: str
    image_url: str | None = None
