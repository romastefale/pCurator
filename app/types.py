from dataclasses import dataclass


@dataclass(slots=True)
class ItemData:
    url: str
    title: str
    text: str
    source: str
    image_url: str | None = None


@dataclass(slots=True)
class RenderedPost:
    text: str
    image_url: str | None = None
