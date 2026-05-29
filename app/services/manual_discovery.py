import logging
from dataclasses import dataclass, field

from aiogram import Bot

from app.services.auto_draft import create_auto_draft
from app.services.news_discovery import search_gnews_topic
from app.services.regenerator import UNIFIED_TONE
from app.settings import Settings
from app.storage.discovery_stats import increment_today_count

logger = logging.getLogger(__name__)

MAX_REFILLS = 3


@dataclass
class SearchState:
    topic: str
    seen_urls: set[str] = field(default_factory=set)
    pending: list[dict] = field(default_factory=list)
    refills: int = 0


# Estado in-memory por usuário. Único usuário real é o OWNER; se o processo
# reiniciar, /buscar precisa ser chamado de novo.
_STATE: dict[int, SearchState] = {}


def reset_search(user_id: int, topic: str) -> SearchState:
    state = SearchState(topic=topic)
    _STATE[user_id] = state
    return state


def get_search(user_id: int) -> SearchState | None:
    return _STATE.get(user_id)


def clear_search(user_id: int) -> None:
    _STATE.pop(user_id, None)


async def _refill(state: SearchState, settings: Settings) -> None:
    if state.refills >= MAX_REFILLS:
        return
    state.refills += 1
    articles = await search_gnews_topic(
        state.topic,
        settings.gnews_key,
        max_results=10,
        database_path=settings.database_path,
        timezone=settings.timezone,
    )
    new = [a for a in articles if a.get("url") and a["url"] not in state.seen_urls]
    state.pending.extend(new)


async def fetch_next_for_search(
    bot: Bot, settings: Settings, user_id: int,
) -> tuple[int, str] | None:
    """Pega o próximo artigo da busca em andamento, cria auto-draft e devolve
    (post_id, source_name). Pula URLs já vistas e duplicatas do banco. Refila
    até MAX_REFILLS vezes via GNews antes de desistir. None = esgotou."""
    state = get_search(user_id)
    if not state or not settings.gnews_key:
        return None

    if not state.pending:
        await _refill(state, settings)

    while True:
        while state.pending:
            art = state.pending.pop(0)
            url = art.get("url")
            if not url or url in state.seen_urls:
                continue
            state.seen_urls.add(url)
            result = await create_auto_draft(
                bot,
                database_path=settings.database_path,
                raw_url=url,
                linkpreview_key=settings.linkpreview_key,
                default_channel=UNIFIED_TONE,
                discovered_topic=state.topic,
            )
            if not result:
                continue
            post_id, intake = result
            await increment_today_count(
                settings.database_path, settings.timezone
            )
            return post_id, intake.source

        # pending vazio — tenta refilar
        if state.refills >= MAX_REFILLS:
            return None
        await _refill(state, settings)
        if not state.pending:
            return None
