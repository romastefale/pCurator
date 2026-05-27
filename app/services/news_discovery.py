import logging
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

TOPIC_QUERIES = {
    "tech": 'tecnologia OR "inteligência artificial" OR gadget',
    "cinema": "filme OR cinema OR estreia OR trailer",
    "series": "série OR streaming OR Netflix OR HBO",
    "pop": '"cultura pop" OR viral OR celebridade',
    "atualidades": 'Brasil OR trending OR "em alta"',
    "ciencia": "ciência OR descoberta OR estudo",
    "geek": "anime OR quadrinhos OR games OR Marvel OR DC",
}

TOPIC_LABELS = {
    "tech": "💻 Tecnologia",
    "cinema": "🎬 Cinema",
    "series": "📺 Séries",
    "pop": "🌟 Pop",
    "atualidades": "📰 Atualidades",
    "ciencia": "🔬 Ciência",
    "geek": "🎮 Geek",
}

# Hora local BR → trilhas a buscar nesse ciclo (12 ciclos cobrem 06h–00h).
ROTATION_BY_HOUR = {
    6: ["tech", "cinema"],
    8: ["series", "geek"],
    10: ["pop", "atualidades"],
    12: ["ciencia", "tech"],
    14: ["atualidades", "pop"],
    16: ["cinema", "series"],
    18: ["geek", "pop"],
    20: ["atualidades", "ciencia"],
    22: ["tech", "cinema"],
    0: ["ciencia", "geek"],
}

# Palavras gráficas/violentas no título → descarta antes de virar rascunho.
TITLE_BLACKLIST = (
    "assassinato",
    "estupro",
    "suicídio",
    "tortura",
    "decapita",
    "esquartej",
    "necrop",
    "homicídio",
    "feminicídio",
    "gore",
    "morre criança",
    "cadáver",
    "linchamento",
    "queimado vivo",
)

# Domínios bloqueados (preencher conforme aparecer ruído).
DOMAIN_BLACKLIST: set[str] = set()


def _passes_filters(article: dict) -> bool:
    title = (article.get("title") or "").lower()
    if any(bad in title for bad in TITLE_BLACKLIST):
        return False
    url = article.get("url") or ""
    if not url:
        return False
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return False
    if domain.startswith("www."):
        domain = domain[4:]
    if domain in DOMAIN_BLACKLIST:
        return False
    return True


async def search_gnews_topic(
    topic_key: str,
    gnews_key: str,
    *,
    lang: str = "pt",
    country: str = "br",
    max_results: int = 5,
    timeout_seconds: int = 10,
) -> list[dict]:
    """Busca uma trilha no GNews e devolve até max_results artigos filtrados."""
    query = TOPIC_QUERIES.get(topic_key)
    if not query:
        return []

    params = {
        "q": query,
        "lang": lang,
        "country": country,
        "max": max_results,
        "in": "title,description",
        "apikey": gnews_key,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://gnews.io/api/v4/search", params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "gnews_http_error topic=%s status=%s body=%s",
                        topic_key, resp.status, body[:200],
                    )
                    return []
                data = await resp.json()
    except Exception as exc:
        logger.warning(
            "gnews_request_failed topic=%s error=%s", topic_key, type(exc).__name__
        )
        return []

    articles = data.get("articles", []) or []
    return [a for a in articles if _passes_filters(a)]


def topics_for_hour(hour: int, enabled_topics: list[str] | None = None) -> list[str]:
    """Devolve as trilhas a buscar neste ciclo, filtrando pelo whitelist do .env."""
    slot = ROTATION_BY_HOUR.get(hour, [])
    if enabled_topics is None:
        return slot
    return [t for t in slot if t in enabled_topics]
