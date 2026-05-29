import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from app.services.auto_draft import create_auto_draft
from app.services.news_discovery import TOPIC_LABELS, search_gnews_topic, topics_for_hour
from app.services.preview import send_post_preview
from app.services.regenerator import UNIFIED_TONE
from app.settings import Settings
from app.storage.discovery_stats import get_today_count, increment_today_count
from app.storage.posts import get_post
from app.storage.session import (
    set_active_post,
    set_last_preview_message_ids,
    try_claim_idle_session,
)
from app.ui import review_keyboard

logger = logging.getLogger(__name__)

CYCLE_SECONDS = 3600  # 1h

# Plano free do GNews. Hard-coded porque é externo (não vem do .env).
GNEWS_DAILY_BUDGET = 100

# Por trilha buscamos 2 endpoints (top-headlines + search) = 2 calls. Por ciclo
# rodamos 2 trilhas = 4 calls. Trilhas sem categoria editorial (ex.: geek)
# economizam 1 call — a estimativa abaixo é conservadora (assume sempre 2).
AUTO_CALLS_PER_CYCLE = 4
MANUAL_CALLS_PER_SEARCH = 2  # mesmo raciocínio: 1 trilha × 2 endpoints


def auto_cycles_remaining_today(
    now_hour: int,
    rotation_hours: set[int],
    quiet_start: int,
    quiet_end: int,
) -> int:
    """Quantos ciclos do auto-loop ainda vão rodar no MESMO dia calendário
    (alinhado com a chave gnews_calls:YYYY-MM-DD). Considera só horas futuras
    do dia atual, em rotation_hours e fora do quiet window.

    Edge cases (com quiet=1-5, rotation=6..23+0):
      - now=23 → 0 (próximo ciclo às 00h já é amanhã)
      - now=0  → 18 (6..23 ainda neste dia)
      - now=1 (quiet) → 18
      - now=5 (quiet) → 18
      - now=10 → 13 (11..23)
      - now=22 → 1 (só 23)
    """
    return sum(
        1
        for h in range(now_hour + 1, 24)
        if h in rotation_hours and not (quiet_start <= h <= quiet_end)
    )


def safe_manual_searches(
    calls_used_today: int,
    cycles_remaining: int,
) -> int:
    """Quantas buscas manuais ainda cabem hoje sem furar o orçamento GNews,
    reservando o que o auto-loop precisa até o fim do dia."""
    reserved_for_auto = cycles_remaining * AUTO_CALLS_PER_CYCLE
    spare = GNEWS_DAILY_BUDGET - calls_used_today - reserved_for_auto
    return max(0, spare // MANUAL_CALLS_PER_SEARCH)


def _is_quiet_hour(hour: int, quiet_start: int, quiet_end: int) -> bool:
    return quiet_start <= hour <= quiet_end


async def _notify_owner(
    bot: Bot,
    database_path: str,
    owner_id: int,
    post_id: int,
    topic_label: str,
) -> bool:
    """Entrega prévia + review_keyboard pro OWNER. Reserva a sessão de forma
    atômica ANTES de enviar mensagens — se houver rascunho manual em curso
    (ou outro auto-draft já reservado), aborta sem clobberar. Devolve True
    se entregou."""
    claimed = await try_claim_idle_session(
        database_path,
        user_id=owner_id,
        post_id=post_id,
        mode="review",
        channel_slug=UNIFIED_TONE,
    )
    if not claimed:
        logger.info("auto_draft_deferred_owner_busy post=%s", post_id)
        return False

    try:
        post = await get_post(database_path, post_id)
        if not post:
            raise RuntimeError(f"post {post_id} disappeared after claim")

        header = await bot.send_message(
            chat_id=owner_id,
            text=f"🤖 Descoberta automática — {topic_label}\nRascunho #{post_id}",
        )
        tracked: list[int] = [header.message_id]
        tracked.extend(await send_post_preview(bot, owner_id, post))
        instr = await bot.send_message(
            chat_id=owner_id,
            text=(
                "Acima a prévia.\n"
                "Você pode publicar, editar, trocar a imagem ou ignorar."
            ),
            reply_markup=review_keyboard(),
        )
        tracked.append(instr.message_id)
        await set_last_preview_message_ids(database_path, owner_id, tracked)
        return True
    except Exception as exc:
        # Libera a sessão pra não deixar o owner travado num rascunho que
        # ele nunca viu. Próximo ciclo (ou flow manual) pode reivindicar.
        logger.exception(
            "auto_draft_notify_failed post=%s rolling back claim: %s",
            post_id, type(exc).__name__,
        )
        try:
            await set_active_post(
                database_path, user_id=owner_id, post_id=None,
                mode=None, clear_channel=True,
            )
        except Exception:
            logger.exception("auto_draft_session_rollback_failed post=%s", post_id)
        return False


async def _run_cycle(bot: Bot, settings: Settings) -> None:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)

    if _is_quiet_hour(now.hour, settings.discovery_quiet_start, settings.discovery_quiet_end):
        logger.debug("discovery_cycle_skipped_quiet_hour hour=%d", now.hour)
        return

    count = await get_today_count(settings.database_path, settings.timezone)
    if count >= settings.discovery_daily_cap:
        logger.info(
            "discovery_daily_cap_reached count=%d cap=%d",
            count, settings.discovery_daily_cap,
        )
        return

    enabled = settings.discovery_topics_list()
    topics = topics_for_hour(now.hour, enabled)
    if not topics:
        logger.debug("discovery_no_topics_for_hour hour=%d", now.hour)
        return

    logger.info(
        "discovery_cycle_start hour=%d topics=%s count=%d cap=%d",
        now.hour, topics, count, settings.discovery_daily_cap,
    )

    for topic in topics:
        if count >= settings.discovery_daily_cap:
            break
        if not settings.gnews_key:
            return
        articles = await search_gnews_topic(
            topic,
            settings.gnews_key,
            database_path=settings.database_path,
            timezone=settings.timezone,
        )
        for art in articles:
            if count >= settings.discovery_daily_cap:
                break
            url = art.get("url")
            if not url:
                continue
            result = await create_auto_draft(
                bot,
                database_path=settings.database_path,
                raw_url=url,
                linkpreview_key=settings.linkpreview_key,
                default_channel=UNIFIED_TONE,
                discovered_topic=topic,
            )
            if not result:
                continue
            post_id, _intake = result
            count = await increment_today_count(
                settings.database_path, settings.timezone
            )
            await _notify_owner(
                bot,
                settings.database_path,
                settings.owner_id,
                post_id,
                TOPIC_LABELS.get(topic, topic),
            )

    logger.info("discovery_cycle_done count=%d", count)


async def discovery_loop(bot: Bot, settings: Settings) -> None:
    if not settings.discovery_enabled:
        logger.info("discovery_disabled — loop not started")
        return
    if not settings.gnews_key:
        logger.warning("discovery_enabled_but_no_gnews_key — loop not started")
        return

    logger.info(
        "discovery_loop_started cap=%d quiet=%d-%d topics=%s cycle_seconds=%d budget=%d",
        settings.discovery_daily_cap,
        settings.discovery_quiet_start,
        settings.discovery_quiet_end,
        settings.discovery_topics or "all",
        CYCLE_SECONDS,
        GNEWS_DAILY_BUDGET,
    )

    while True:
        try:
            await _run_cycle(bot, settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("discovery_cycle_failed: %s", type(exc).__name__)
        await asyncio.sleep(CYCLE_SECONDS)
