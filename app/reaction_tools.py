import html
import json
import logging
import re
from collections import deque
from datetime import datetime
from typing import Any

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message, MessageReactionCountUpdated, MessageReactionUpdated

from app.access import reject_message_if_not_allowed
from app.settings import get_settings
from app.storage.reactions import (
    deactivate_reaction_watch,
    get_reaction_watch,
    list_reaction_events,
    list_reaction_watches,
    record_reaction_event,
    upsert_reaction_watch,
)

logger = logging.getLogger(__name__)

router = Router()

_PUBLIC_POST_RE = re.compile(
    r"^(?:https?://)?t\.me/(?:s/)?(?P<channel>[A-Za-z0-9_]{5,})/(?P<message_id>\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

_PRIVATE_POST_RE = re.compile(
    r"^(?:https?://)?t\.me/c/(?P<internal_id>\d+)/(?P<message_id>\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)

# Cache curto para diagnóstico imediato. A versão persistente grava somente posts em watchlist.
_REACTION_EVENTS: dict[tuple[int, int], deque[str]] = {}
_REACTION_COUNTS: dict[tuple[int, int], str] = {}
_MAX_EVENTS_PER_POST = 12


def _command_payload(text: str) -> str:
    parts = (text or "").split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _parse_public_post_link(link: str) -> tuple[str, int] | None:
    match = _PUBLIC_POST_RE.match(link.strip())
    if not match:
        return None
    return match.group("channel"), int(match.group("message_id"))


def _parse_private_post_link(link: str) -> tuple[str, int] | None:
    match = _PRIVATE_POST_RE.match(link.strip())
    if not match:
        return None
    return match.group("internal_id"), int(match.group("message_id"))


def _json_value(raw: str | None, fallback: str = "—") -> str:
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if value is None:
        return fallback
    return str(value)


def _reaction_type_label(value: Any) -> str:
    if value is None:
        return "—"

    emoji = getattr(value, "emoji", None)
    if emoji:
        return str(emoji)

    custom_emoji_id = getattr(value, "custom_emoji_id", None)
    if custom_emoji_id:
        return f"custom:{custom_emoji_id}"

    reaction_type = getattr(value, "type", None)
    if reaction_type:
        return str(reaction_type)

    return html.escape(str(value))


def _reaction_list_label(values: Any) -> str:
    if not values:
        return "—"
    return ", ".join(_reaction_type_label(item) for item in values)


def _reaction_count_label(values: Any) -> str:
    if not values:
        return "sem contagem recebida"

    lines = []
    for item in values:
        reaction = _reaction_type_label(getattr(item, "type", None))
        total = getattr(item, "total_count", None)
        if total is None:
            lines.append(html.escape(str(item)))
        else:
            lines.append(f"{reaction}: {total}")
    return " · ".join(lines)


def _actor_data(update: MessageReactionUpdated) -> dict[str, Any]:
    user = getattr(update, "user", None)
    if user:
        return {
            "actor_user_id": user.id,
            "actor_username": user.username,
            "actor_name": user.full_name or str(user.id),
            "actor_chat_id": None,
            "actor_chat_title": None,
        }

    actor_chat = getattr(update, "actor_chat", None)
    if actor_chat:
        return {
            "actor_user_id": None,
            "actor_username": None,
            "actor_name": None,
            "actor_chat_id": actor_chat.id,
            "actor_chat_title": actor_chat.title or str(actor_chat.id),
        }

    return {
        "actor_user_id": None,
        "actor_username": None,
        "actor_name": None,
        "actor_chat_id": None,
        "actor_chat_title": None,
    }


def _actor_label_from_data(data: dict[str, Any]) -> str:
    if data.get("actor_user_id"):
        name = html.escape(str(data.get("actor_name") or data["actor_user_id"]))
        username = data.get("actor_username")
        username_line = f" @{html.escape(str(username))}" if username else ""
        return f"{name}{username_line} · <code>{data['actor_user_id']}</code>"

    if data.get("actor_chat_id"):
        title = html.escape(str(data.get("actor_chat_title") or data["actor_chat_id"]))
        return f"{title} · <code>{data['actor_chat_id']}</code>"

    return "ator não identificado"


def _store_event(chat_id: int, message_id: int, line: str) -> None:
    key = (chat_id, message_id)
    events = _REACTION_EVENTS.setdefault(key, deque(maxlen=_MAX_EVENTS_PER_POST))
    events.append(line)


def _format_cached_probe(chat_id: int, message_id: int) -> str:
    key = (chat_id, message_id)
    counts = _REACTION_COUNTS.get(key)
    events = list(_REACTION_EVENTS.get(key, ()))

    parts = []
    if counts:
        parts.append("<b>Cache de contagem desde que o bot iniciou</b>\n" + html.escape(counts))
    else:
        parts.append("<b>Cache de contagem desde que o bot iniciou</b>\n—")

    if events:
        parts.append("<b>Cache de eventos identificados desde que o bot iniciou</b>\n" + "\n".join(events[-_MAX_EVENTS_PER_POST:]))
    else:
        parts.append(
            "<b>Cache de eventos identificados desde que o bot iniciou</b>\n"
            "— nenhum evento individual recebido ainda"
        )

    return "\n\n".join(parts)


async def _format_persisted_probe(database_path: str, chat_id: int, message_id: int) -> str:
    watch = await get_reaction_watch(database_path, chat_id, message_id)
    events = await list_reaction_events(database_path, chat_id, message_id, limit=_MAX_EVENTS_PER_POST)

    if not watch:
        watched_line = "<b>Watchlist persistente</b>\n— este post ainda não está em observação. Use <code>/preactwatch LINK</code>."
    else:
        state = "ativa" if watch.get("is_active") else "inativa"
        last_event = watch.get("last_event_at") or "—"
        watched_line = (
            "<b>Watchlist persistente</b>\n"
            f"estado: <code>{state}</code> · último update: <code>{html.escape(str(last_event))}</code>"
        )

    if not events:
        events_line = "<b>Eventos persistidos</b>\n— nenhum update salvo para este post ainda"
    else:
        lines = []
        for event in events:
            created_at = html.escape(str(event.get("created_at") or "—"))
            event_type = event.get("event_type")
            if event_type == "reaction_count":
                counts = html.escape(_json_value(event.get("reactions_json"), "sem contagem"))
                lines.append(f"• <code>{created_at}</code> — contagem: {counts}")
            else:
                actor = _actor_label_from_data(event)
                old_reaction = html.escape(_json_value(event.get("old_reaction_json")))
                new_reaction = html.escape(_json_value(event.get("new_reaction_json")))
                lines.append(
                    f"• <code>{created_at}</code> — {actor}: "
                    f"<code>{old_reaction}</code> → <code>{new_reaction}</code>"
                )
        events_line = "<b>Eventos persistidos</b>\n" + "\n".join(lines)

    return watched_line + "\n\n" + events_line


async def _resolve_public_post(message: Message, raw_link: str) -> tuple[int | None, int | None, str | None, str | None, list[str]]:
    parsed = _parse_public_post_link(raw_link)
    if not parsed:
        return None, None, None, None, ["link público inválido"]

    channel, message_id = parsed
    attempt_lines = [
        f"Canal informado: <code>@{html.escape(channel)}</code>",
        f"Post: <code>{message_id}</code>",
    ]

    try:
        chat = await message.bot.get_chat(f"@{channel}")
    except TelegramAPIError as exc:
        attempt_lines.append(
            "getChat: falhou — "
            f"<code>{html.escape(type(exc).__name__)}</code>"
        )
        return None, message_id, channel, None, attempt_lines

    chat_id = chat.id
    title = chat.title or getattr(chat, "full_name", None) or f"@{channel}"
    attempt_lines.append(f"getChat: ok — {html.escape(title)} · <code>{chat.id}</code>")

    bot_user = await message.bot.get_me()
    try:
        member = await message.bot.get_chat_member(chat.id, bot_user.id)
        attempt_lines.append(f"bot no canal: <code>{html.escape(str(member.status))}</code>")
    except TelegramAPIError as exc:
        attempt_lines.append(
            "bot no canal: não confirmado — "
            f"<code>{html.escape(type(exc).__name__)}</code>"
        )

    return chat_id, message_id, channel, title, attempt_lines


@router.message_reaction()
async def reaction_update_handler(update: MessageReactionUpdated) -> None:
    """Registra reações futuras quando o Telegram entrega update identificado."""
    chat_id = update.chat.id
    message_id = update.message_id
    actor_data = _actor_data(update)
    actor = _actor_label_from_data(actor_data)
    old_reaction = _reaction_list_label(update.old_reaction)
    new_reaction = _reaction_list_label(update.new_reaction)
    moment = datetime.now().strftime("%H:%M:%S")

    line = (
        f"• <code>{moment}</code> — {actor}: "
        f"<code>{html.escape(old_reaction)}</code> → <code>{html.escape(new_reaction)}</code>"
    )
    _store_event(chat_id, message_id, line)

    settings = get_settings()
    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    if watch and watch.get("is_active"):
        await record_reaction_event(
            settings.database_path,
            chat_id=chat_id,
            message_id=message_id,
            event_type="reaction",
            old_reaction=old_reaction,
            new_reaction=new_reaction,
            **actor_data,
        )

    logger.info("reaction_update chat_id=%s message_id=%s", chat_id, message_id)


@router.message_reaction_count()
async def reaction_count_handler(update: MessageReactionCountUpdated) -> None:
    """Registra contagem futura quando o Telegram só entrega agregado/anônimo."""
    chat_id = update.chat.id
    message_id = update.message_id
    count_label = _reaction_count_label(update.reactions)
    _REACTION_COUNTS[(chat_id, message_id)] = count_label

    settings = get_settings()
    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    if watch and watch.get("is_active"):
        await record_reaction_event(
            settings.database_path,
            chat_id=chat_id,
            message_id=message_id,
            event_type="reaction_count",
            reactions=count_label,
        )

    logger.info("reaction_count_update chat_id=%s message_id=%s", chat_id, message_id)


@router.message(Command("preactwatch"))
async def reaction_watch_command(message: Message) -> None:
    """Ativa persistência para updates futuros de um post."""
    if await reject_message_if_not_allowed(message):
        return

    raw_link = _command_payload(message.text or "")
    if not raw_link:
        await message.answer(
            "<b>Observar reações futuras</b>\n\n"
            "Uso: <code>/preactwatch https://t.me/nomedocanal/123</code>"
        )
        return

    if _parse_private_post_link(raw_link):
        await message.answer(
            "<b>Observar reações futuras</b>\n\n"
            "Link <code>t.me/c/...</code> ainda não é aceito neste incremento. "
            "Use link público com username: <code>https://t.me/nomedocanal/123</code>."
        )
        return

    chat_id, message_id, channel, title, attempt_lines = await _resolve_public_post(message, raw_link)
    if chat_id is None or message_id is None:
        await message.answer(
            "<b>Observar reações futuras</b>\n\n"
            + "\n".join(f"• {line}" for line in attempt_lines)
            + "\n\nNão consegui ativar a observação sem resolver o canal."
        )
        return

    settings = get_settings()
    await upsert_reaction_watch(
        settings.database_path,
        chat_id=chat_id,
        message_id=message_id,
        channel_username=channel,
        channel_title=title,
        post_link=raw_link,
        created_by=message.from_user.id if message.from_user else None,
    )

    await message.answer(
        "<b>Observação ativada</b>\n\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        "A partir de agora, se o Telegram entregar <code>message_reaction</code> ou "
        "<code>message_reaction_count</code> para esse post, o pCurator salva em SQLite.\n"
        "Consulte depois com o mesmo link em <code>/preact LINK</code>."
    )


@router.message(Command("preactoff"))
async def reaction_watch_off_command(message: Message) -> None:
    """Desativa a watchlist persistente de um post."""
    if await reject_message_if_not_allowed(message):
        return

    raw_link = _command_payload(message.text or "")
    if not raw_link:
        await message.answer(
            "<b>Parar observação</b>\n\n"
            "Uso: <code>/preactoff https://t.me/nomedocanal/123</code>"
        )
        return

    chat_id, message_id, _, _, attempt_lines = await _resolve_public_post(message, raw_link)
    if chat_id is None or message_id is None:
        await message.answer(
            "<b>Parar observação</b>\n\n"
            + "\n".join(f"• {line}" for line in attempt_lines)
            + "\n\nNão consegui resolver o post."
        )
        return

    settings = get_settings()
    ok = await deactivate_reaction_watch(settings.database_path, chat_id, message_id)
    await message.answer(
        "<b>Parar observação</b>\n\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        + ("Observação desativada." if ok else "Esse post não estava em observação ativa.")
    )


@router.message(Command("preactlist"))
async def reaction_watch_list_command(message: Message) -> None:
    """Lista posts em observação persistente."""
    if await reject_message_if_not_allowed(message):
        return

    settings = get_settings()
    watches = await list_reaction_watches(settings.database_path, limit=20)
    if not watches:
        await message.answer("<b>Posts observados</b>\n\nNenhum post em observação.")
        return

    lines = []
    for watch in watches:
        title = html.escape(watch.get("channel_title") or watch.get("channel_username") or str(watch["chat_id"]))
        last_event = html.escape(str(watch.get("last_event_at") or "—"))
        post_link = html.escape(watch.get("post_link") or "")
        lines.append(
            f"• {title} · post <code>{watch['message_id']}</code> · último update: <code>{last_event}</code>\n"
            f"  <code>/preact {post_link}</code>"
        )

    await message.answer("<b>Posts observados</b>\n\n" + "\n".join(lines))


@router.message(Command("preact"))
async def reaction_probe_command(message: Message) -> None:
    """Diagnostica e tenta o máximo permitido pelo Bot API para um link de post."""
    if await reject_message_if_not_allowed(message):
        return

    raw_link = _command_payload(message.text or "")
    if not raw_link:
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            "Uso: <code>/preact https://t.me/nomedocanal/123</code>\n\n"
            "Para posts novos, primeiro use <code>/preactwatch LINK</code>. "
            "Depois consulte com <code>/preact LINK</code>."
        )
        return

    if _parse_private_post_link(raw_link):
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            f"Link recebido: <code>{html.escape(raw_link)}</code>\n"
            "Tipo: link interno <code>t.me/c/...</code>\n\n"
            "Este incremento ainda precisa de link público com username, no formato:\n"
            "<code>https://t.me/nomedocanal/123</code>"
        )
        return

    chat_id, message_id, _, _, attempt_lines = await _resolve_public_post(message, raw_link)
    if message_id is None:
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            "Link inválido para este comando.\n"
            "Use: <code>/preact https://t.me/nomedocanal/123</code>"
        )
        return

    settings = get_settings()
    if chat_id is not None:
        persisted = await _format_persisted_probe(settings.database_path, chat_id, message_id)
        cached = _format_cached_probe(chat_id, message_id)
    else:
        persisted = (
            "<b>Watchlist persistente</b>\n"
            "— não consegui resolver o canal, então não deu para consultar por chat_id"
        )
        cached = (
            "<b>Cache em memória</b>\n"
            "— não consegui resolver o canal, então não deu para cruzar cache por chat_id"
        )

    await message.answer(
        "<b>Diagnóstico de reações</b>\n\n"
        "<b>Tentativas feitas agora</b>\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        + persisted
        + "\n\n"
        + cached
        + "\n\n"
        "<b>Limite real</b>\n"
        "O Bot API não tem método para buscar o histórico de quem reagiu em post antigo. "
        "Para os próximos posts, use <code>/preactwatch LINK</code>; se o Telegram entregar "
        "updates de reação ou contagem, o pCurator salva e mostra aqui."
    )
