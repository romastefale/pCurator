import asyncio
import logging
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

# Queries enriquecidas com entidades/marcas pra ampliar o leque de resultados.
# Cuidado: GNews aceita ~250 chars na query — manter abaixo disso.
TOPIC_QUERIES = {
    "tech": (
        'IA OR "inteligência artificial" OR ChatGPT OR OpenAI OR Gemini OR '
        'Apple OR iPhone OR Google OR Microsoft OR Android OR gadget OR '
        'startup OR fintech OR criptomoeda OR Tesla OR robô OR chip'
    ),
    "cinema": (
        "filme OR cinema OR estreia OR trailer OR bilheteria OR Hollywood OR "
        "Oscar OR Marvel OR DC OR Disney OR Pixar OR A24 OR diretor OR sequência"
    ),
    "series": (
        "série OR temporada OR Netflix OR HBO OR Max OR Disney+ OR Prime OR "
        '"Apple TV" OR finale OR renovada OR cancelada OR spin-off OR "novo episódio"'
    ),
    "pop": (
        'Taylor Swift OR Beyoncé OR BTS OR K-pop OR Anitta OR viral OR TikTok OR '
        'celebridade OR "cultura pop" OR meme OR polêmica OR festival OR Grammy OR show'
    ),
    "atualidades": (
        'Brasil OR Lula OR Congresso OR STF OR economia OR Selic OR inflação OR '
        'Petrobras OR "em alta" OR trending OR governo OR aprovou'
    ),
    "ciencia": (
        'NASA OR SpaceX OR Marte OR exoplaneta OR fóssil OR vacina OR '
        '"descoberta científica" OR "novo estudo" OR pesquisa OR genética OR '
        'clima OR oceano OR dinossauro OR "buraco negro"'
    ),
    "geek": (
        'anime OR mangá OR Naruto OR "One Piece" OR Pokémon OR Nintendo OR '
        'Switch OR PlayStation OR Xbox OR Steam OR RPG OR "novo jogo" OR '
        'Marvel OR DC OR "Star Wars" OR "Harry Potter"'
    ),
}

# Mapeia trilha → categoria do endpoint top-headlines do GNews.
# Categorias válidas: general, world, nation, business, technology,
# entertainment, sports, science, health. None = sem categoria editorial.
TOPIC_TO_CATEGORY = {
    "tech": "technology",
    "cinema": "entertainment",
    "series": "entertainment",
    "pop": "entertainment",
    "atualidades": "world",
    "ciencia": "science",
    "geek": None,  # sem categoria editorial relevante; só keyword search
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


async def _gnews_get(
    session: aiohttp.ClientSession,
    endpoint: str,
    params: dict,
    *,
    topic_key: str,
    source_label: str,
) -> list[dict]:
    """Faz uma chamada GET ao GNews e devolve a lista de articles (ou [])."""
    url = f"https://gnews.io/api/v4/{endpoint}"
    try:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.warning(
                    "gnews_http_error topic=%s endpoint=%s status=%s body=%s",
                    topic_key, source_label, resp.status, body[:200],
                )
                return []
            data = await resp.json()
    except Exception as exc:
        logger.warning(
            "gnews_request_failed topic=%s endpoint=%s error=%s",
            topic_key, source_label, type(exc).__name__,
        )
        return []
    return data.get("articles", []) or []


async def search_gnews_topic(
    topic_key: str,
    gnews_key: str,
    *,
    lang: str = "pt",
    country: str = "br",
    max_results: int = 5,
    timeout_seconds: int = 10,
) -> list[dict]:
    """Busca uma trilha combinando 2 fontes do GNews:
      - top-headlines?category=... → manchetes editoriais da categoria (se houver)
      - search?q=... → busca por keywords ricas da trilha

    Devolve até ~max_results*2 artigos únicos por URL, intercalados pra dar
    variedade (1 editorial, 1 keyword, 1 editorial, 1 keyword...). Articles
    duplicados em ambas as fontes aparecem uma vez só."""
    query = TOPIC_QUERIES.get(topic_key)
    if not query:
        return []

    category = TOPIC_TO_CATEGORY.get(topic_key)

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    search_params = {
        "q": query, "lang": lang, "country": country,
        "max": max_results, "in": "title,description", "apikey": gnews_key,
    }

    # GNews free tier limita a ~1 req/seg — chamadas SERIAIS com pausa curta
    # entre elas. Em paralelo (asyncio.gather) o GNews devolve 429 na segunda.
    async with aiohttp.ClientSession(timeout=timeout) as session:
        headline_articles: list[dict] = []
        if category:
            headline_params = {
                "category": category, "lang": lang, "country": country,
                "max": max_results, "apikey": gnews_key,
            }
            headline_articles = await _gnews_get(
                session, "top-headlines", headline_params,
                topic_key=topic_key, source_label="top-headlines",
            )
            await asyncio.sleep(1.2)  # respeita rate limit antes da próxima call

        search_articles = await _gnews_get(
            session, "search", search_params,
            topic_key=topic_key, source_label="search",
        )

    # Intercala (editorial primeiro pra dar prioridade ao que está bombando),
    # depois dedupa por URL preservando ordem.
    interleaved: list[dict] = []
    for pair in zip(headline_articles, search_articles):
        interleaved.extend(pair)
    longer = headline_articles if len(headline_articles) > len(search_articles) else search_articles
    interleaved.extend(longer[min(len(headline_articles), len(search_articles)):])

    seen_urls: set[str] = set()
    unique: list[dict] = []
    for art in interleaved:
        url = art.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(art)

    filtered = [a for a in unique if _passes_filters(a)]
    logger.info(
        "gnews_search topic=%s headlines=%d search=%d unique=%d kept=%d",
        topic_key, len(headline_articles), len(search_articles),
        len(unique), len(filtered),
    )
    return filtered


def topics_for_hour(hour: int, enabled_topics: list[str] | None = None) -> list[str]:
    """Devolve as trilhas a buscar neste ciclo, filtrando pelo whitelist do .env."""
    slot = ROTATION_BY_HOUR.get(hour, [])
    if enabled_topics is None:
        return slot
    return [t for t in slot if t in enabled_topics]
