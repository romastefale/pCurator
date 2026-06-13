import hashlib
import html
import json
import logging
import re
from io import BytesIO
from collections import deque
from datetime import datetime, timezone
from typing import Any

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message, MessageReactionCountUpdated, MessageReactionUpdated

from app.access import is_owner_id
from app.settings import get_settings
from app.storage.reactions import (
    deactivate_reaction_watch,
    find_reaction_posts_by_message_id,
    get_latest_reaction_post_metadata,
    get_reaction_watch,
    latest_reaction_snapshots,
    list_recent_reaction_snapshots,
    list_reaction_events,
    list_reaction_watches,
    reaction_event_count,
    record_reaction_event,
    record_reaction_post_metadata,
    record_reaction_snapshot,
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
_INTERNAL_POST_RE = re.compile(
    r"^channel:(?P<chat_id>-?\d+)/(?P<message_id>\d+)$",
    re.IGNORECASE,
)

# Cache curto para diagnóstico imediato. A versão persistente grava posts vistos/watchlist.
_REACTION_EVENTS: dict[tuple[int, int], deque[str]] = {}
_REACTION_COUNTS: dict[tuple[int, int], str] = {}
_MAX_EVENTS_PER_POST = 12


def _safe_log_value(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text[:240] if len(text) > 240 else text


def _audit_info(event: str, **fields: Any) -> None:
    payload = " ".join(f"{key}={_safe_log_value(value)}" for key, value in fields.items())
    if payload:
        logger.info("[pCurator reactions] %s %s", event, payload)
    else:
        logger.info("[pCurator reactions] %s", event)


def _audit_warning(event: str, **fields: Any) -> None:
    payload = " ".join(f"{key}={_safe_log_value(value)}" for key, value in fields.items())
    if payload:
        logger.warning("[pCurator reactions] %s %s", event, payload)
    else:
        logger.warning("[pCurator reactions] %s", event)


def _now_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def _parse_private_post_link(link: str) -> tuple[int, int] | None:
    match = _PRIVATE_POST_RE.match(link.strip())
    if not match:
        return None
    # Links t.me/c/<internal_id>/<msg> mapeiam, para bots, para chat_id -100<internal_id>.
    return int(f"-100{match.group('internal_id')}"), int(match.group("message_id"))


def _parse_internal_post_ref(link: str) -> tuple[int, int] | None:
    match = _INTERNAL_POST_RE.match(link.strip())
    if not match:
        return None
    return int(match.group("chat_id")), int(match.group("message_id"))


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


def _json_load_or_none(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


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

    return str(value)


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
            lines.append(str(item))
        else:
            lines.append(f"{reaction}: {total}")
    return " · ".join(lines)


def _telegram_date_iso(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _reaction_type_parts(value: Any) -> tuple[str, str, str]:
    """Retorna (key, label, kind) de forma estável para emoji/custom/paid."""
    if value is None:
        return "unknown", "—", "unknown"

    kind = str(getattr(value, "type", None) or "unknown")
    emoji = getattr(value, "emoji", None)
    if emoji:
        return f"emoji:{emoji}", str(emoji), "emoji"

    custom_emoji_id = getattr(value, "custom_emoji_id", None)
    if custom_emoji_id:
        return f"custom_emoji:{custom_emoji_id}", f"custom:{custom_emoji_id}", "custom_emoji"

    if kind and kind != "unknown":
        return kind, kind, kind

    return str(value), str(value), "unknown"


def _reaction_count_items(values: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not values:
        return items
    for item in values:
        key, label, kind = _reaction_type_parts(getattr(item, "type", None))
        total = getattr(item, "total_count", 0) or 0
        try:
            total_int = int(total)
        except (TypeError, ValueError):
            total_int = 0
        items.append({"key": key, "label": label, "kind": kind, "total": total_int})
    return items


def _reaction_stats_from_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int(item.get("total") or 0) for item in items)
    kinds = len(items)
    dominant = "—"
    if items:
        dominant = max(items, key=lambda item: int(item.get("total") or 0)).get("label") or "—"
    return {"total_reactions": total, "reaction_kinds": kinds, "dominant_reaction": dominant}


def _delta_label(snapshot: dict[str, Any]) -> str:
    previous = snapshot.get("previous_count")
    delta = snapshot.get("delta_count")
    current = snapshot.get("total_count")
    if previous is None or delta is None:
        return f"{current} · primeiro snapshot"
    sign = "+" if int(delta) > 0 else ""
    return f"{previous} → {current} ({sign}{delta})"


def _snapshot_summary_line(snapshot: dict[str, Any]) -> str:
    label = str(snapshot.get("dominant_reaction") or snapshot.get("reaction_key") or "—")
    reaction_key = str(snapshot.get("reaction_key") or "")
    if reaction_key.startswith("emoji:"):
        label = reaction_key.split(":", 1)[1]
    elif reaction_key == "aggregate:unknown":
        label = "agregado sem emoji"
    return f"{html.escape(label)}: <code>{html.escape(_delta_label(snapshot))}</code>"


def _snapshot_csv_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace('"', '""')
    if any(ch in text for ch in [",", "\n", '"']):
        return f'"{text}"'
    return text


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


def _chat_title(chat: Any) -> str:
    return str(getattr(chat, "title", None) or getattr(chat, "full_name", None) or getattr(chat, "id", "canal"))


def _chat_username(chat: Any) -> str | None:
    username = getattr(chat, "username", None)
    return str(username) if username else None


def _post_ref(chat: Any, message_id: int) -> str:
    username = _chat_username(chat)
    if username:
        return f"https://t.me/{username}/{message_id}"
    return f"channel:{chat.id}/{message_id}"


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


async def _notify_owner(
    bot: Any,
    text: str,
    *,
    event_type: str,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> None:
    settings = get_settings()
    if not settings.owner_id:
        _audit_warning(
            "owner_notify_skipped",
            reason="owner_id_missing",
            event_type=event_type,
            chat_id=chat_id,
            message_id=message_id,
        )
        return
    try:
        await bot.send_message(settings.owner_id, text)
        _audit_info(
            "owner_notify_sent",
            owner_id=settings.owner_id,
            event_type=event_type,
            chat_id=chat_id,
            message_id=message_id,
        )
    except Exception as exc:
        _audit_warning(
            "owner_notify_failed",
            owner_id=settings.owner_id,
            event_type=event_type,
            chat_id=chat_id,
            message_id=message_id,
            error=type(exc).__name__,
        )


async def _ignore_if_not_owner_dm(message: Message) -> bool:
    """Garante que os comandos novos de reação não respondam fora da DM do dono.

    A regra é silenciosa de propósito: se alguém chamar /preact* em grupo/canal
    ou se outro usuário chamar no privado, o bot não responde nada. Isso preserva
    o requisito de nenhuma interação pública/externa para esta implementação.
    """
    if str(message.chat.type) != "private":
        _audit_info(
            "owner_only_command_ignored",
            reason="not_private_chat",
            chat_id=getattr(message.chat, "id", None),
            chat_type=getattr(message.chat, "type", None),
            from_user_id=getattr(message.from_user, "id", None),
        )
        return True
    user_id = message.from_user.id if message.from_user else None
    if not is_owner_id(user_id):
        _audit_info(
            "owner_only_command_ignored",
            reason="not_owner",
            chat_id=getattr(message.chat, "id", None),
            from_user_id=user_id,
        )
        return True
    return False


async def _ensure_watch_for_seen_post(
    *,
    bot: Any,
    database_path: str,
    chat: Any,
    message_id: int,
    source: str,
    notify_owner: bool,
) -> dict | None:
    """Garante watchlist para qualquer post de canal visto pelo bot/admin.

    A operação é idempotente. Não depende do post ter sido publicado pelo pCurator.
    """
    chat_id = int(chat.id)
    watch = await get_reaction_watch(database_path, chat_id, message_id)
    title = _chat_title(chat)
    username = _chat_username(chat)
    post_link = _post_ref(chat, message_id)

    await upsert_reaction_watch(
        database_path,
        chat_id=chat_id,
        message_id=message_id,
        channel_username=username,
        channel_title=title,
        post_link=post_link,
        created_by=None,
        source=source if not watch else str(watch.get("source") or source),
    )

    if not watch:
        _audit_info(
            "watch_created",
            source=source,
            chat_id=chat_id,
            message_id=message_id,
            title=title,
            username=username,
            ref=post_link,
        )
    else:
        _audit_info(
            "watch_confirmed",
            source=source,
            chat_id=chat_id,
            message_id=message_id,
            title=title,
            username=username,
            ref=post_link,
        )

    if notify_owner and not watch:
        await _notify_owner(
            bot,
            "<b>Post de canal monitorado</b>\n\n"
            f"Canal: <b>{html.escape(title)}</b>\n"
            f"Chat ID: <code>{chat_id}</code>\n"
            f"Post: <code>{message_id}</code>\n"
            f"Origem: <code>{html.escape(source)}</code>\n"
            f"Ref: <code>{html.escape(post_link)}</code>\n"
            f"Horário: <code>{html.escape(_now_label())}</code>\n\n"
            "Status: monitoramento ativado. Vou avisar aqui na DM quando o Telegram entregar atualização de reação desse post.",
            event_type="channel_post_watch",
            chat_id=chat_id,
            message_id=message_id,
        )

    return await get_reaction_watch(database_path, chat_id, message_id)


async def _format_persisted_probe(database_path: str, chat_id: int, message_id: int) -> str:
    watch = await get_reaction_watch(database_path, chat_id, message_id)
    events = await list_reaction_events(database_path, chat_id, message_id, limit=_MAX_EVENTS_PER_POST)

    if not watch:
        watched_line = (
            "<b>Watchlist persistente</b>\n"
            "— este post ainda não está em observação. Use <code>/preactwatch LINK</code>."
        )
    else:
        state = "ativa" if watch.get("is_active") else "inativa"
        last_event = html.escape(str(watch.get("last_event_at") or "—"))
        source = html.escape(str(watch.get("source") or "manual"))
        watched_line = (
            "<b>Watchlist persistente</b>\n"
            f"estado: <code>{state}</code> · origem: <code>{source}</code> · último update: <code>{last_event}</code>"
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


async def _resolve_post_ref(message: Message, raw_ref: str) -> tuple[int | None, int | None, str | None, str | None, str, list[str]]:
    """Resolve link/ref para (chat_id, message_id, username, title, normalized_ref, log)."""
    raw_ref = raw_ref.strip()

    internal = _parse_internal_post_ref(raw_ref)
    if internal:
        chat_id, message_id = internal
        attempt_lines = [f"Canal informado: <code>{chat_id}</code>", f"Post: <code>{message_id}</code>"]
        try:
            chat = await message.bot.get_chat(chat_id)
            title = _chat_title(chat)
            attempt_lines.append(f"getChat: ok — {html.escape(title)} · <code>{chat.id}</code>")
            return chat.id, message_id, _chat_username(chat), title, raw_ref, attempt_lines
        except TelegramAPIError as exc:
            attempt_lines.append(f"getChat: falhou — <code>{html.escape(type(exc).__name__)}</code>")
            return chat_id, message_id, None, None, raw_ref, attempt_lines

    private = _parse_private_post_link(raw_ref)
    if private:
        chat_id, message_id = private
        attempt_lines = [
            f"Link interno: <code>{html.escape(raw_ref)}</code>",
            f"Canal inferido: <code>{chat_id}</code>",
            f"Post: <code>{message_id}</code>",
        ]
        try:
            chat = await message.bot.get_chat(chat_id)
            title = _chat_title(chat)
            attempt_lines.append(f"getChat: ok — {html.escape(title)} · <code>{chat.id}</code>")
            return chat.id, message_id, _chat_username(chat), title, f"channel:{chat.id}/{message_id}", attempt_lines
        except TelegramAPIError as exc:
            attempt_lines.append(f"getChat: falhou — <code>{html.escape(type(exc).__name__)}</code>")
            return None, message_id, None, None, raw_ref, attempt_lines

    public = _parse_public_post_link(raw_ref)
    if not public:
        return None, None, None, None, raw_ref, ["link inválido"]

    channel, message_id = public
    attempt_lines = [
        f"Canal informado: <code>@{html.escape(channel)}</code>",
        f"Post: <code>{message_id}</code>",
    ]
    try:
        chat = await message.bot.get_chat(f"@{channel}")
    except TelegramAPIError as exc:
        attempt_lines.append(f"getChat: falhou — <code>{html.escape(type(exc).__name__)}</code>")
        return None, message_id, channel, None, raw_ref, attempt_lines

    title = _chat_title(chat)
    username = _chat_username(chat) or channel
    attempt_lines.append(f"getChat: ok — {html.escape(title)} · <code>{chat.id}</code>")

    bot_user = await message.bot.get_me()
    try:
        member = await message.bot.get_chat_member(chat.id, bot_user.id)
        attempt_lines.append(f"bot no canal: <code>{html.escape(str(member.status))}</code>")
    except TelegramAPIError as exc:
        attempt_lines.append(f"bot no canal: não confirmado — <code>{html.escape(type(exc).__name__)}</code>")

    return chat.id, message_id, username, title, f"https://t.me/{username}/{message_id}", attempt_lines


@router.channel_post()
async def channel_post_seen_handler(message: Message) -> None:
    """Auto-watch global: todo post de canal visto pelo bot vira monitorado."""
    settings = get_settings()
    await _ensure_watch_for_seen_post(
        bot=message.bot,
        database_path=settings.database_path,
        chat=message.chat,
        message_id=message.message_id,
        source="channel_post_seen",
        notify_owner=True,
    )
    _audit_info(
        "channel_post_received",
        chat_id=message.chat.id,
        message_id=message.message_id,
        title=_chat_title(message.chat),
    )


@router.edited_channel_post()
async def edited_channel_post_seen_handler(message: Message) -> None:
    """Mantém watchlist para posts editados que o bot vê no canal."""
    settings = get_settings()
    await _ensure_watch_for_seen_post(
        bot=message.bot,
        database_path=settings.database_path,
        chat=message.chat,
        message_id=message.message_id,
        source="edited_channel_post_seen",
        notify_owner=False,
    )
    _audit_info(
        "edited_channel_post_received",
        chat_id=message.chat.id,
        message_id=message.message_id,
        title=_chat_title(message.chat),
    )


@router.message_reaction()
async def reaction_update_handler(update: MessageReactionUpdated) -> None:
    """Registra e notifica reações futuras quando o Telegram entrega update identificado."""
    chat_id = update.chat.id
    message_id = update.message_id
    actor_data = _actor_data(update)
    actor = _actor_label_from_data(actor_data)
    old_reaction = _reaction_list_label(update.old_reaction)
    new_reaction = _reaction_list_label(update.new_reaction)
    moment = datetime.now().strftime("%H:%M:%S")

    _audit_info(
        "message_reaction_received",
        chat_id=chat_id,
        message_id=message_id,
        actor_user_id=actor_data.get("actor_user_id"),
        actor_username=actor_data.get("actor_username"),
        actor_chat_id=actor_data.get("actor_chat_id"),
        old_reaction=old_reaction,
        new_reaction=new_reaction,
    )

    line = (
        f"• <code>{moment}</code> — {actor}: "
        f"<code>{html.escape(old_reaction)}</code> → <code>{html.escape(new_reaction)}</code>"
    )
    _store_event(chat_id, message_id, line)

    settings = get_settings()
    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    if not watch or not watch.get("is_active"):
        watch = await _ensure_watch_for_seen_post(
            bot=update.bot,
            database_path=settings.database_path,
            chat=update.chat,
            message_id=message_id,
            source="reaction_auto_seen",
            notify_owner=False,
        )

    await record_reaction_event(
        settings.database_path,
        chat_id=chat_id,
        message_id=message_id,
        event_type="reaction",
        old_reaction=old_reaction,
        new_reaction=new_reaction,
        **actor_data,
    )
    _audit_info(
        "reaction_event_saved",
        event_type="message_reaction",
        chat_id=chat_id,
        message_id=message_id,
        old_reaction=old_reaction,
        new_reaction=new_reaction,
    )

    title = _chat_title(update.chat)
    ref = (watch or {}).get("post_link") or _post_ref(update.chat, message_id)
    await _notify_owner(
        update.bot,
        "<b>Nova reação detectada</b>\n\n"
        f"Canal: <b>{html.escape(title)}</b>\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Post: <code>{message_id}</code>\n"
        f"Ator: {actor}\n"
        f"Antes: <code>{html.escape(old_reaction)}</code>\n"
        f"Agora: <code>{html.escape(new_reaction)}</code>\n"
        f"Evento: <code>message_reaction</code>\n"
        f"Ref: <code>{html.escape(str(ref))}</code>\n"
        f"Horário: <code>{html.escape(_now_label())}</code>",
        event_type="message_reaction",
        chat_id=chat_id,
        message_id=message_id,
    )

    _audit_info(
        "message_reaction_handled",
        chat_id=chat_id,
        message_id=message_id,
        old_reaction=old_reaction,
        new_reaction=new_reaction,
    )


@router.message_reaction_count()
async def reaction_count_handler(update: MessageReactionCountUpdated) -> None:
    """Registra e notifica contagem futura quando o Telegram entrega agregado/anônimo."""
    chat_id = update.chat.id
    message_id = update.message_id
    count_label = _reaction_count_label(update.reactions)
    _REACTION_COUNTS[(chat_id, message_id)] = count_label

    _audit_info(
        "message_reaction_count_received",
        chat_id=chat_id,
        message_id=message_id,
        reactions=count_label,
    )

    settings = get_settings()
    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    if not watch or not watch.get("is_active"):
        watch = await _ensure_watch_for_seen_post(
            bot=update.bot,
            database_path=settings.database_path,
            chat=update.chat,
            message_id=message_id,
            source="reaction_count_auto_seen",
            notify_owner=False,
        )

    await record_reaction_event(
        settings.database_path,
        chat_id=chat_id,
        message_id=message_id,
        event_type="reaction_count",
        reactions=count_label,
    )
    _audit_info(
        "reaction_event_saved",
        event_type="message_reaction_count",
        chat_id=chat_id,
        message_id=message_id,
        reactions=count_label,
    )

    items = _reaction_count_items(update.reactions)
    stats = _reaction_stats_from_items(items)
    telegram_date = _telegram_date_iso(getattr(update, "date", None))
    snapshots: list[dict[str, Any]] = []

    # message_reaction_count representa o conjunto agregado atual. Se uma reação
    # desapareceu do update atual, gravamos snapshot zero para impedir que
    # consultas futuras mantenham uma reação antiga como se ainda estivesse ativa.
    current_keys = {str(item["key"]) for item in items}
    previous_snapshots = await latest_reaction_snapshots(settings.database_path, chat_id, message_id)
    for previous in previous_snapshots:
        previous_key = str(previous.get("reaction_key") or "")
        if not previous_key or previous_key in current_keys:
            continue
        if int(previous.get("total_count") or 0) <= 0:
            continue
        snapshot = await record_reaction_snapshot(
            settings.database_path,
            chat_id=chat_id,
            message_id=message_id,
            reaction_key=previous_key,
            reaction_type=str(previous.get("reaction_type") or "unknown"),
            total_count=0,
            data_mode="aggregate_anonymous",
            telegram_date=telegram_date,
            total_reactions=int(stats["total_reactions"]),
            reaction_kinds=int(stats["reaction_kinds"]),
            dominant_reaction=str(stats["dominant_reaction"]),
        )
        snapshots.append(snapshot)

    for item in items:
        snapshot = await record_reaction_snapshot(
            settings.database_path,
            chat_id=chat_id,
            message_id=message_id,
            reaction_key=str(item["key"]),
            reaction_type=str(item["kind"]),
            total_count=int(item["total"]),
            data_mode="aggregate_anonymous",
            telegram_date=telegram_date,
            total_reactions=int(stats["total_reactions"]),
            reaction_kinds=int(stats["reaction_kinds"]),
            dominant_reaction=str(stats["dominant_reaction"]),
        )
        snapshots.append(snapshot)
    snapshot_lines = [_snapshot_summary_line(snapshot) for snapshot in snapshots]
    snapshot_text = "\n".join(snapshot_lines) if snapshot_lines else "—"
    _audit_info(
        "reaction_snapshot_saved",
        event_type="message_reaction_count",
        chat_id=chat_id,
        message_id=message_id,
        total_reactions=stats["total_reactions"],
        reaction_kinds=stats["reaction_kinds"],
        dominant_reaction=stats["dominant_reaction"],
        data_mode="aggregate_anonymous",
    )

    title = _chat_title(update.chat)
    ref = (watch or {}).get("post_link") or _post_ref(update.chat, message_id)
    await _notify_owner(
        update.bot,
        "<b>Contagem de reações atualizada</b>\n\n"
        f"Canal: <b>{html.escape(title)}</b>\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Post: <code>{message_id}</code>\n"
        f"Reações: <code>{html.escape(count_label)}</code>\n"
        f"Total geral: <code>{stats['total_reactions']}</code>\n"
        f"Tipos de reação: <code>{stats['reaction_kinds']}</code>\n"
        f"Dominante: <code>{html.escape(str(stats['dominant_reaction']))}</code>\n"
        f"Variação desde o snapshot anterior:\n{snapshot_text}\n"
        f"Modo do dado: <code>aggregate_anonymous</code>\n"
        f"Evento: <code>message_reaction_count</code>\n"
        f"Ref: <code>{html.escape(str(ref))}</code>\n"
        f"Horário Telegram: <code>{html.escape(str(telegram_date or '—'))}</code>\n"
        f"Horário local: <code>{html.escape(_now_label())}</code>\n\n"
        "Observação: em canal broadcast isso pode vir agregado/anônimo e com atraso do Telegram.",
        event_type="message_reaction_count",
        chat_id=chat_id,
        message_id=message_id,
    )



    _audit_info(
        "message_reaction_count_handled",
        chat_id=chat_id,
        message_id=message_id,
        reactions=count_label,
        total_reactions=stats["total_reactions"],
        reaction_kinds=stats["reaction_kinds"],
        dominant_reaction=stats["dominant_reaction"],
        data_mode="aggregate_anonymous",
    )


@router.message(Command("preactwatch"))
async def reaction_watch_command(message: Message) -> None:
    """Ativa persistência para updates futuros de um post."""
    if await _ignore_if_not_owner_dm(message):
        return

    raw_ref = _command_payload(message.text or "")
    if not raw_ref:
        await message.answer(
            "<b>Observar reações futuras</b>\n\n"
            "Uso: <code>/preactwatch https://t.me/nomedocanal/123</code>"
        )
        return

    chat_id, message_id, username, title, normalized_ref, attempt_lines = await _resolve_post_ref(message, raw_ref)
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
        channel_username=username,
        channel_title=title,
        post_link=normalized_ref,
        created_by=message.from_user.id if message.from_user else None,
        source="manual",
    )

    await message.answer(
        "<b>Observação ativada</b>\n\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        "A partir de agora, se o Telegram entregar <code>message_reaction</code> ou "
        "<code>message_reaction_count</code> para esse post, o pCurator salva em SQLite "
        "e avisa o dono na DM.\n"
        "Consulte depois com <code>/preact LINK</code>."
    )


@router.message(Command("preactoff"))
async def reaction_watch_off_command(message: Message) -> None:
    """Desativa a watchlist persistente de um post."""
    if await _ignore_if_not_owner_dm(message):
        return

    raw_ref = _command_payload(message.text or "")
    if not raw_ref:
        await message.answer(
            "<b>Parar observação</b>\n\n"
            "Uso: <code>/preactoff https://t.me/nomedocanal/123</code>"
        )
        return

    chat_id, message_id, _, _, _, attempt_lines = await _resolve_post_ref(message, raw_ref)
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
    if await _ignore_if_not_owner_dm(message):
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
        source = html.escape(str(watch.get("source") or "manual"))
        lines.append(
            f"• {title} · post <code>{watch['message_id']}</code> · origem: <code>{source}</code> · último update: <code>{last_event}</code>\n"
            f"  <code>/preact {post_link}</code>"
        )

    await message.answer("<b>Posts observados</b>\n\n" + "\n".join(lines))




async def _format_snapshot_probe(database_path: str, chat_id: int, message_id: int) -> str:
    snapshots = await latest_reaction_snapshots(database_path, chat_id, message_id)
    event_count = await reaction_event_count(database_path, chat_id, message_id)
    if not snapshots:
        return (
            "<b>Estatística por snapshot</b>\n"
            "— ainda não há snapshot de contagem para este post. "
            "Ele será criado quando o Telegram entregar <code>message_reaction_count</code>."
        )

    total = max(int(s.get("total_reactions") or 0) for s in snapshots)
    kinds = max(int(s.get("reaction_kinds") or 0) for s in snapshots)
    dominant = next((str(s.get("dominant_reaction")) for s in snapshots if s.get("dominant_reaction")), "—")
    last_at = max(str(s.get("captured_at") or "") for s in snapshots)
    mode = snapshots[0].get("data_mode") or "aggregate_anonymous"
    lines = [_snapshot_summary_line(snapshot) for snapshot in snapshots]
    return (
        "<b>Estatística por snapshot</b>\n"
        f"modo do dado: <code>{html.escape(str(mode))}</code>\n"
        f"total geral: <code>{total}</code> · tipos: <code>{kinds}</code> · dominante: <code>{html.escape(dominant)}</code>\n"
        f"eventos salvos: <code>{event_count}</code> · último snapshot: <code>{html.escape(last_at or '—')}</code>\n"
        + "\n".join(f"• {line}" for line in lines)
    )


def _latest_post_totals(rows: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    latest_by_key: dict[tuple[int, int, str], dict[str, Any]] = {}
    for row in rows:
        key = (int(row["chat_id"]), int(row["message_id"]), str(row["reaction_key"]))
        if key not in latest_by_key or int(row["id"]) > int(latest_by_key[key]["id"]):
            latest_by_key[key] = row

    posts: dict[tuple[int, int], dict[str, Any]] = {}
    for row in latest_by_key.values():
        post_key = (int(row["chat_id"]), int(row["message_id"]))
        item = posts.setdefault(
            post_key,
            {
                "chat_id": int(row["chat_id"]),
                "message_id": int(row["message_id"]),
                "channel_title": row.get("channel_title") or str(row["chat_id"]),
                "post_link": row.get("post_link") or f"channel:{row['chat_id']}/{row['message_id']}",
                "total": 0,
                "positive_delta": 0,
                "last_at": row.get("captured_at") or "",
                "dominant": row.get("dominant_reaction") or "—",
            },
        )
        item["total"] += int(row.get("total_count") or 0)
        delta = row.get("delta_count")
        if delta is not None and int(delta) > 0:
            item["positive_delta"] += int(delta)
        if str(row.get("captured_at") or "") > str(item.get("last_at") or ""):
            item["last_at"] = row.get("captured_at") or ""
            item["dominant"] = row.get("dominant_reaction") or item.get("dominant") or "—"
    return posts




def _extract_json_candidate(text: str) -> str:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(r"\s*```$", "", candidate).strip()
    first_brace = min([idx for idx in [candidate.find("{"), candidate.find("[")] if idx >= 0] or [-1])
    if first_brace > 0:
        candidate = candidate[first_brace:]
    return candidate


def _nested_get(data: Any, path: list[Any], default: Any = None) -> Any:
    current = data
    for key in path:
        try:
            if isinstance(current, dict):
                current = current[key]
            elif isinstance(current, list) and isinstance(key, int):
                current = current[key]
            else:
                return default
        except (KeyError, IndexError, TypeError):
            return default
    return current


def _short_text(value: Any, limit: int = 180) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return None
    return text[:limit] + ("…" if len(text) > limit else "")


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chat_id_from_dump_peer(raw_id: Any) -> int | None:
    peer_id = _safe_int(raw_id)
    if peer_id is None:
        return None
    if peer_id < 0:
        return peer_id
    return int(f"-100{peer_id}")


def _dump_attributes(data: dict[str, Any]) -> list[dict[str, Any]]:
    attrs = data.get("attributes")
    return attrs if isinstance(attrs, list) else []


def _dump_reaction_attribute(data: dict[str, Any]) -> dict[str, Any] | None:
    for attr in _dump_attributes(data):
        if isinstance(attr, dict) and isinstance(attr.get("reactions"), list):
            return attr
    return None


def _dump_signature(data: dict[str, Any]) -> str | None:
    for attr in _dump_attributes(data):
        if isinstance(attr, dict) and attr.get("signature"):
            return _short_text(attr.get("signature"), 80)
    return None


def _dump_count_values(data: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for attr in _dump_attributes(data):
        if isinstance(attr, dict) and "count" in attr:
            number = _safe_int(attr.get("count"))
            if number is not None:
                values.append(number)
    return values


def _dump_content_type(data: dict[str, Any]) -> str:
    media = data.get("media")
    if isinstance(media, list) and media:
        for item in media:
            if isinstance(item, dict) and ("imageId" in item or "representations" in item):
                return "photo"
        return "media"
    if data.get("text"):
        return "text"
    return "unknown"


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dump_reaction_value(value: Any) -> tuple[str, str, str]:
    """Normaliza tipos de reação em formatos Telegram app, Bot API, TDLib e MTProto/Pyrogram."""
    if isinstance(value, dict):
        # Telegram app dump: {"builtin": "❤"}
        if value.get("builtin"):
            label = str(value["builtin"])
            return f"emoji:{label}", label, "emoji"

        # TDLib/Bot API: {"@type": "reactionTypeEmoji", "emoji": "❤"} ou {"type": "emoji", "emoji": "❤"}
        emoji = _first_present(value, "emoji", "emoticon", "reaction")
        if isinstance(emoji, str) and emoji:
            return f"emoji:{emoji}", emoji, "emoji"

        # Alguns dumps aninham a reação dentro de type/value/reaction.
        for nested_key in ("type", "value", "reaction"):
            nested = value.get(nested_key)
            if isinstance(nested, dict):
                key, label, kind = _dump_reaction_value(nested)
                if label != "unknown":
                    return key, label, kind

        custom_id = _first_present(value, "customEmojiId", "custom_emoji_id", "customEmoji", "document_id", "documentId")
        if custom_id:
            custom = str(custom_id)
            return f"custom_emoji:{custom}", f"custom:{custom}", "custom_emoji"

        raw_type = str(_first_present(value, "@type", "_", "type") or "")
        if "paid" in raw_type.lower() or value.get("paid") or value.get("stars"):
            return "paid", "paid", "paid"
        if raw_type and raw_type not in {"emoji", "custom_emoji", "reactionTypeEmoji"}:
            return raw_type, raw_type, raw_type

    label = str(value or "unknown")
    return label, label, "unknown"


def _reaction_total_from_raw(raw: dict[str, Any]) -> int:
    total = _first_present(raw, "count", "total_count", "totalCount", "total")
    return _safe_int(total) or 0


def _chosen_order_from_raw(raw: dict[str, Any]) -> int | None:
    return _safe_int(_first_present(raw, "chosenOrder", "chosen_order", "order"))


def _dump_reaction_container_candidates(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Encontra blocos de reações em dumps Telegram app, TDLib, MTProto/Pyrogram e Bot API."""
    candidates: list[tuple[str, dict[str, Any]]] = []

    attr = _dump_reaction_attribute(data)
    if attr:
        candidates.append(("telegram_app_attribute", attr))

    direct_reactions = data.get("reactions")
    if isinstance(direct_reactions, dict):
        candidates.append(("root_reactions", direct_reactions))
    elif isinstance(direct_reactions, list):
        candidates.append(("root_reactions_list", {"reactions": direct_reactions}))

    for path, source in [
        (["interaction_info", "reactions"], "tdlib_interaction_info"),
        (["interactionInfo", "reactions"], "tdlib_interactionInfo"),
        (["interaction_info", "message_reactions"], "tdlib_message_reactions"),
        (["interactionInfo", "messageReactions"], "tdlib_messageReactions"),
        (["message", "reactions"], "wrapped_message_reactions"),
        (["message", "interaction_info", "reactions"], "wrapped_tdlib_interaction_info"),
        (["message", "interactionInfo", "reactions"], "wrapped_tdlib_interactionInfo"),
        (["content", "reactions"], "content_reactions"),
    ]:
        value = _nested_get(data, path)
        if isinstance(value, dict):
            candidates.append((source, value))
        elif isinstance(value, list):
            candidates.append((source, {"reactions": value}))

    # Remove duplicados por identidade do objeto para não processar o mesmo bloco duas vezes.
    seen: set[int] = set()
    unique: list[tuple[str, dict[str, Any]]] = []
    for source, container in candidates:
        ident = id(container)
        if ident in seen:
            continue
        seen.add(ident)
        unique.append((source, container))
    return unique



_REACTION_PROBE_KEYS = {
    "reaction",
    "reactions",
    "messageReactions",
    "message_reactions",
    "reactionCounts",
    "reaction_counts",
    "results",
    "canViewList",
    "canGetAddedReactions",
    "can_get_added_reactions",
    "can_see_list",
    "canSeeList",
    "recentPeers",
    "recent_peers",
    "recentReactions",
    "recent_reactions",
    "recentSenderIds",
    "recent_sender_ids",
    "topPeers",
    "top_peers",
    "topReactors",
    "top_reactors",
    "paidReactors",
    "paid_reactors",
    "areTags",
    "are_tags",
    "isTags",
}

_REACTION_CONTAINER_KEYS = {
    "reactions",
    "messageReactions",
    "message_reactions",
    "reactionCounts",
    "reaction_counts",
    "results",
}


def _dump_path_join(base: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{base}[{key}]" if base else f"[{key}]"
    if not base:
        return str(key)
    safe = str(key)
    if safe.isidentifier():
        return f"{base}.{safe}"
    return f"{base}[{safe!r}]"


def _dump_probe_value_summary(value: Any) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        keys = list(value.keys())[:6]
        return "dict{" + ",".join(str(k) for k in keys) + ("…" if len(value) > 6 else "") + "}"
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text[:60] + ("…" if len(text) > 60 else "")


def _dump_probe_reaction_paths(data: Any, *, limit: int = 40) -> list[dict[str, str]]:
    """Varre o JSON inteiro em busca de chaves de reação/TDLib/MTProto para diagnóstico."""
    matches: list[dict[str, str]] = []
    seen: set[int] = set()

    def walk(value: Any, path: str, depth: int) -> None:
        if len(matches) >= limit or depth > 18:
            return
        if isinstance(value, (dict, list)):
            ident = id(value)
            if ident in seen:
                return
            seen.add(ident)
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = _dump_path_join(path, key)
                key_text = str(key)
                if key_text in _REACTION_PROBE_KEYS or "reaction" in key_text.lower():
                    matches.append({
                        "path": child_path,
                        "key": key_text,
                        "summary": _dump_probe_value_summary(child),
                    })
                    if len(matches) >= limit:
                        return
                walk(child, child_path, depth + 1)
                if len(matches) >= limit:
                    return
        elif isinstance(value, list):
            for index, child in enumerate(value[:120]):
                walk(child, _dump_path_join(path, index), depth + 1)
                if len(matches) >= limit:
                    return

    walk(data, "", 0)
    return matches


def _dump_recursive_reaction_container_candidates(data: Any, *, limit: int = 80) -> list[tuple[str, dict[str, Any]]]:
    """Fallback: encontra containers de reação em qualquer nível do dump."""
    candidates: list[tuple[str, dict[str, Any]]] = []
    seen: set[int] = set()

    def add_candidate(source: str, container: dict[str, Any]) -> None:
        if len(candidates) >= limit:
            return
        ident = id(container)
        if ident in seen:
            return
        seen.add(ident)
        candidates.append((source, container))

    def walk(value: Any, path: str, depth: int) -> None:
        if len(candidates) >= limit or depth > 18:
            return
        if isinstance(value, dict):
            # Container direto: possui array conhecido ou flags/listas de reação.
            if any(isinstance(value.get(key), list) for key in _REACTION_CONTAINER_KEYS):
                add_candidate(f"recursive:{path or 'root'}", value)
            elif any(key in value for key in ("canViewList", "canGetAddedReactions", "can_get_added_reactions", "can_see_list")):
                add_candidate(f"recursive:{path or 'root'}", value)

            for key, child in value.items():
                child_path = _dump_path_join(path, key)
                if str(key) in _REACTION_CONTAINER_KEYS:
                    if isinstance(child, dict):
                        add_candidate(f"recursive:{child_path}", child)
                    elif isinstance(child, list):
                        # MTProto/Pyrogram podem ter reactions.results/reaction_counts; Telegram app pode ter attr.reactions.
                        wrapper_key = "results" if str(key) == "results" else "reactions"
                        add_candidate(f"recursive:{child_path}", {wrapper_key: child})
                walk(child, child_path, depth + 1)
                if len(candidates) >= limit:
                    return
        elif isinstance(value, list):
            for index, child in enumerate(value[:120]):
                walk(child, _dump_path_join(path, index), depth + 1)
                if len(candidates) >= limit:
                    return

    walk(data, "", 0)
    return candidates

def _dump_reaction_items_from_container(container: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items: list[Any] = []
    source_key = ""
    if isinstance(container.get("reactions"), list):
        raw_items = container.get("reactions") or []
        source_key = "reactions"
    elif isinstance(container.get("results"), list):
        raw_items = container.get("results") or []
        source_key = "results"
    elif isinstance(container.get("reaction_counts"), list):
        raw_items = container.get("reaction_counts") or []
        source_key = "reaction_counts"
    elif isinstance(container.get("reactionCounts"), list):
        raw_items = container.get("reactionCounts") or []
        source_key = "reactionCounts"

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        # Telegram app: value/count. TDLib/Bot API: type/total_count. MTProto/Pyrogram: reaction/count.
        reaction_value = None
        for key in ("value", "type", "reaction"):
            if key in raw:
                reaction_value = raw.get(key)
                break
        if reaction_value is None and (raw.get("emoji") or raw.get("emoticon") or raw.get("builtin")):
            reaction_value = raw

        key, label, kind = _dump_reaction_value(reaction_value)
        total = _reaction_total_from_raw(raw)
        chosen_order = _chosen_order_from_raw(raw)
        items.append({
            "key": key,
            "label": label,
            "kind": kind,
            "total": total,
            "chosen_order": chosen_order,
            "source_key": source_key,
        })
    return items


def _dump_reaction_items(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """Retorna itens + formato detectado + container usado.

    Primeiro tenta caminhos conhecidos; se não encontrar itens, faz varredura
    recursiva em todo o dump para cobrir exports/clients com embrulhos novos.
    """
    best_items: list[dict[str, Any]] = []
    best_source: str | None = None
    best_container: dict[str, Any] | None = None

    for source, container in _dump_reaction_container_candidates(data):
        items = _dump_reaction_items_from_container(container)
        if items:
            return items, source, container
        if best_container is None:
            best_source = source
            best_container = container

    for source, container in _dump_recursive_reaction_container_candidates(data):
        items = _dump_reaction_items_from_container(container)
        if items:
            return items, source, container
        if best_container is None:
            best_source = source
            best_container = container

    return best_items, best_source, best_container


def _dump_bool_from_container(container: dict[str, Any] | None, data: dict[str, Any], *names: str) -> bool | None:
    for source in [container, data]:
        if not isinstance(source, dict):
            continue
        value = _first_present(source, *names)
        if value is None:
            continue
        return bool(value)
    return None


def _dump_list_count(container: dict[str, Any] | None, data: dict[str, Any], *names: str) -> int:
    for source in [container, data]:
        if not isinstance(source, dict):
            continue
        value = _first_present(source, *names)
        if isinstance(value, list):
            return len(value)
    return 0


def _dump_extra_metrics(data: dict[str, Any]) -> dict[str, Any]:
    interaction = data.get("interaction_info") if isinstance(data.get("interaction_info"), dict) else None
    if interaction is None and isinstance(data.get("interactionInfo"), dict):
        interaction = data.get("interactionInfo")
    if interaction is None and isinstance(_nested_get(data, ["message", "interaction_info"]), dict):
        interaction = _nested_get(data, ["message", "interaction_info"])
    if interaction is None and isinstance(_nested_get(data, ["message", "interactionInfo"]), dict):
        interaction = _nested_get(data, ["message", "interactionInfo"])
    interaction = interaction or {}

    reply_info = interaction.get("reply_info") or interaction.get("replyInfo") or {}
    reply_count = None
    if isinstance(reply_info, dict):
        reply_count = _safe_int(_first_present(reply_info, "reply_count", "replyCount", "count"))

    return {
        "view_count": _safe_int(_first_present(interaction, "view_count", "viewCount", "views")),
        "forward_count": _safe_int(_first_present(interaction, "forward_count", "forwardCount", "forwards")),
        "reply_count": reply_count,
    }


def _dump_message_id(data: dict[str, Any]) -> int | None:
    for value in [
        data.get("message_id"),
        data.get("messageId"),
        _nested_get(data, ["message", "message_id"]),
        _nested_get(data, ["message", "messageId"]),
    ]:
        number = _safe_int(value)
        if number is not None:
            return number

    # TDLib usa id numérico simples como ID da mensagem quando chat_id está no objeto.
    if data.get("chat_id") is not None or data.get("chatId") is not None:
        number = _safe_int(data.get("id"))
        if number is not None:
            return number

    for path in [["id", "id"], ["id", "rawValue"], ["message", "id"]]:
        number = _safe_int(_nested_get(data, path))
        if number is not None:
            return number

    return _safe_int(data.get("stableId"))


def _dump_chat_id(data: dict[str, Any]) -> int | None:
    for value in [
        data.get("chat_id"),
        data.get("chatId"),
        _nested_get(data, ["chat", "id"]),
        _nested_get(data, ["message", "chat_id"]),
        _nested_get(data, ["message", "chatId"]),
        _nested_get(data, ["message", "chat", "id"]),
    ]:
        number = _safe_int(value)
        if number is not None:
            return _chat_id_from_dump_peer(number)

    peer_raw = _nested_get(data, ["id", "peerId", "id", "rawValue"])
    if peer_raw is None:
        peer_raw = _nested_get(data, ["author", "id", "id", "rawValue"])
    if peer_raw is None:
        peer_raw = _nested_get(data, ["peer_id", "channel_id"])
    if peer_raw is None:
        peer_raw = _nested_get(data, ["peerId", "channelId"])
    if peer_raw is None:
        peer_raw = _nested_get(data, ["peerId", "id"])
    return _chat_id_from_dump_peer(peer_raw)


def _dump_text_preview(data: dict[str, Any]) -> str | None:
    candidates = [
        data.get("text"),
        data.get("caption"),
        _nested_get(data, ["content", "text", "text"]),
        _nested_get(data, ["content", "caption", "text"]),
        _nested_get(data, ["message", "text"]),
        _nested_get(data, ["message", "content", "text", "text"]),
        _nested_get(data, ["message", "content", "caption", "text"]),
    ]
    for value in candidates:
        if isinstance(value, dict):
            value = value.get("text")
        text = _short_text(value, 180)
        if text:
            return text
    return None


def _dump_signature(data: dict[str, Any]) -> str | None:
    for key in ("signature", "post_author", "postAuthor", "author_signature", "authorSignature"):
        text = _short_text(data.get(key), 80)
        if text:
            return text
    for attr in _dump_attributes(data):
        if isinstance(attr, dict) and attr.get("signature"):
            return _short_text(attr.get("signature"), 80)
    return None


def _dump_content_type(data: dict[str, Any]) -> str:
    content = data.get("content") if isinstance(data.get("content"), dict) else None
    if content is None and isinstance(_nested_get(data, ["message", "content"]), dict):
        content = _nested_get(data, ["message", "content"])
    if isinstance(content, dict):
        raw_type = str(_first_present(content, "@type", "_", "type") or "")
        if raw_type:
            cleaned = raw_type.replace("message", "", 1) if raw_type.startswith("message") else raw_type
            return cleaned[:80] or raw_type[:80]

    media = data.get("media")
    if isinstance(media, list) and media:
        for item in media:
            if isinstance(item, dict) and ("imageId" in item or "representations" in item):
                return "photo"
        return "media"
    if data.get("photo") or _nested_get(data, ["content", "photo"]):
        return "photo"
    if _dump_text_preview(data):
        return "text"
    return "unknown"


def _dump_count_values(data: dict[str, Any]) -> dict[str, Any]:
    attribute_counts: list[int] = []
    for attr in _dump_attributes(data):
        if isinstance(attr, dict) and "count" in attr and "reactions" not in attr:
            number = _safe_int(attr.get("count"))
            if number is not None:
                attribute_counts.append(number)

    metrics = _dump_extra_metrics(data)
    # Dumps do cliente Telegram/iOS podem serializar os campos MTProto views/forwards
    # como atributos genéricos {count: N}. Quando houver bloco `reactions`, ele é a
    # fonte principal de reactions; os counts soltos ficam como candidatos de interação.
    if metrics.get("view_count") is None and attribute_counts:
        metrics["possible_view_count"] = attribute_counts[0]
        metrics["possible_view_source"] = "root_attribute_count_candidate"
    else:
        metrics["possible_view_count"] = metrics.get("view_count")
        metrics["possible_view_source"] = "explicit_interaction_info" if metrics.get("view_count") is not None else None

    if metrics.get("forward_count") is None and len(attribute_counts) > 1:
        metrics["possible_forward_count"] = attribute_counts[1]
        metrics["possible_forward_source"] = "root_attribute_count_candidate"
    else:
        metrics["possible_forward_count"] = metrics.get("forward_count")
        metrics["possible_forward_source"] = "explicit_interaction_info" if metrics.get("forward_count") is not None else None

    metrics["root_count_confidence"] = (
        "candidate_pending_mtproto_confirmation" if attribute_counts else "not_available"
    )
    return {"attribute_counts": attribute_counts, **metrics}


def _dump_untyped_root_counts(data: dict[str, Any]) -> list[int]:
    """Counts soltos da raiz do dump, sem tratá-los como reactions confirmadas.

    No Telegram/MTProto views, forwards e reactions são campos separados. Em dumps
    do cliente iOS alguns campos podem aparecer como atributos genéricos
    `{count: N}`. Eles devem ser preservados como candidatos de views/forwards,
    mas não devem inflar `total_reactions` quando não há bloco explícito
    `reactions` ou evento `message_reaction_count`.
    """
    counts = _dump_count_values(data).get("attribute_counts") or []
    return [int(c) for c in counts if _safe_int(c) is not None]


_MAX_DUMP_FILE_BYTES = 5 * 1024 * 1024
_ALLOWED_DUMP_EXTENSIONS = {".json", ".txt"}
_ALLOWED_DUMP_MIME_TYPES = {"application/json", "text/plain", "text/json"}


def _document_extension(filename: str | None) -> str:
    if not filename:
        return ""
    lowered = filename.lower().strip()
    dot = lowered.rfind(".")
    return lowered[dot:] if dot >= 0 else ""


async def _read_dump_document_text(source_message: Message, *, bot: Any) -> str | None:
    """Lê dump anexado como .json/.txt sem aceitar binários grandes.

    O comando permanece owner-only no handler; este helper só evita que dumps longos
    precisem caber em uma mensagem de texto.
    """
    document = getattr(source_message, "document", None)
    if not document:
        return None

    filename = getattr(document, "file_name", None)
    extension = _document_extension(filename)
    mime_type = str(getattr(document, "mime_type", None) or "")
    if extension not in _ALLOWED_DUMP_EXTENSIONS and mime_type not in _ALLOWED_DUMP_MIME_TYPES:
        raise ValueError("arquivo de dump precisa ser .json ou .txt")

    file_size = getattr(document, "file_size", None)
    if file_size is not None and int(file_size) > _MAX_DUMP_FILE_BYTES:
        raise ValueError("arquivo de dump muito grande; limite atual é 5 MB")

    telegram_file = await bot.get_file(document.file_id)
    buffer = BytesIO()
    await bot.download_file(telegram_file.file_path, destination=buffer)
    raw = buffer.getvalue()
    if len(raw) > _MAX_DUMP_FILE_BYTES:
        raise ValueError("arquivo de dump muito grande; limite atual é 5 MB")

    for encoding in ("utf-8-sig", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            text = ""
    if not text:
        text = raw.decode("utf-8", errors="replace")

    text = text.strip()
    if not text:
        raise ValueError("arquivo de dump está vazio")

    _audit_info(
        "preactdeep_dump_file_loaded",
        filename=filename or "-",
        mime_type=mime_type or "-",
        size=len(raw),
    )
    return text


def _parse_dump_payload(text: str) -> dict[str, Any]:
    candidate = _extract_json_candidate(text)
    data = json.loads(candidate)
    if isinstance(data, list):
        if len(data) != 1 or not isinstance(data[0], dict):
            raise ValueError("dump precisa ser um objeto JSON de mensagem ou lista com um objeto")
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("dump precisa ser um objeto JSON")

    normalized_dump = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    dump_hash = hashlib.sha256(normalized_dump.encode("utf-8")).hexdigest()

    chat_id = _dump_chat_id(data)
    message_id = _dump_message_id(data)
    username = _nested_get(data, ["author", "username"]) or _nested_get(data, ["chat", "username"]) or _nested_get(data, ["sender_chat", "username"])
    title = _nested_get(data, ["author", "title"]) or _nested_get(data, ["chat", "title"]) or _nested_get(data, ["sender_chat", "title"])

    if not username or not title:
        for peer in _nested_get(data, ["peers", "items"], []) or []:
            if not isinstance(peer, dict):
                continue
            candidate = peer.get(".1")
            if isinstance(candidate, dict):
                username = username or candidate.get("username")
                title = title or candidate.get("title")
                break

    items, source_format, reaction_container = _dump_reaction_items(data)
    stats = _reaction_stats_from_items(items)
    root_counts = _dump_untyped_root_counts(data)
    if not items and root_counts:
        source_format = source_format or "telegram_client_root_counts_untyped"
    if items:
        reaction_label = " · ".join(f"{item['label']}: {item['total']}" for item in items)
    else:
        reaction_label = "—"

    can_view_list = _dump_bool_from_container(
        reaction_container,
        data,
        "canViewList",
        "canGetAddedReactions",
        "can_get_added_reactions",
        "can_see_list",
        "canSeeList",
    )
    recent_peers_count = _dump_list_count(
        reaction_container,
        data,
        "recentPeers",
        "recent_peers",
        "recentReactions",
        "recent_reactions",
        "recentSenderIds",
        "recent_sender_ids",
        "recent_chooser_dialog_ids",
    )
    top_peers_count = _dump_list_count(
        reaction_container,
        data,
        "topPeers",
        "top_peers",
        "topReactors",
        "top_reactors",
    )
    paid_reactors_count = _dump_list_count(
        reaction_container,
        data,
        "paidReactors",
        "paid_reactors",
        "paid_reactor_ids",
    )
    are_tags = _dump_bool_from_container(
        reaction_container,
        data,
        "isTags",
        "areTags",
        "are_tags",
    )

    if can_view_list is True:
        data_mode = "list_available"
    elif items and can_view_list is False:
        data_mode = "aggregate_anonymous"
    elif items:
        data_mode = "aggregate_or_unknown"
    elif root_counts:
        data_mode = "root_counts_untyped"
    else:
        data_mode = "unknown_no_list_flag"

    post_link = f"https://t.me/{username}/{message_id}" if username and message_id else None

    if chat_id is None or message_id is None:
        raise ValueError("não consegui extrair chat_id/message_id do dump")

    reaction_probe_paths = _dump_probe_reaction_paths(data)
    reaction_probe_summary = [
        f"{match['path']}={match['summary']}" for match in reaction_probe_paths[:12]
    ]

    count_values = _dump_count_values(data)
    if not items and not root_counts:
        _audit_warning(
            "preactdeep_dump_no_reactions_found",
            chat_id=chat_id,
            message_id=message_id,
            source_format=source_format or "-",
            probe_matches=len(reaction_probe_paths),
            probe_preview=" | ".join(reaction_probe_summary[:6]) or "-",
        )
    elif not items and root_counts:
        _audit_info(
            "preactdeep_dump_root_counts_found",
            chat_id=chat_id,
            message_id=message_id,
            possible_views=count_values.get("possible_view_count"),
            possible_forwards=count_values.get("possible_forward_count"),
            source_format=source_format or "telegram_client_root_counts_untyped",
            raw_counts=count_values.get("attribute_counts"),
        )
    elif items and root_counts:
        _audit_info(
            "preactdeep_dump_reactions_and_counts_found",
            chat_id=chat_id,
            message_id=message_id,
            total_reactions=stats["total_reactions"],
            possible_views=count_values.get("possible_view_count"),
            possible_forwards=count_values.get("possible_forward_count"),
            source_format=source_format or "telegram_client_attribute_reactions",
            raw_counts=count_values.get("attribute_counts"),
        )

    return {
        "chat_id": chat_id,
        "message_id": message_id,
        "chat_username": str(username) if username else None,
        "chat_title": str(title) if title else None,
        "post_link": post_link or f"channel:{chat_id}/{message_id}",
        "text_preview": _dump_text_preview(data),
        "signature": _dump_signature(data),
        "content_type": _dump_content_type(data),
        "can_view_list": can_view_list,
        "recent_peers_count": recent_peers_count,
        "top_peers_count": top_peers_count,
        "paid_reactors_count": paid_reactors_count,
        "are_tags": are_tags,
        "reaction_items": items,
        "root_counts": root_counts,
        "reaction_label": reaction_label,
        "total_reactions": int(stats["total_reactions"]),
        "reaction_kinds": int(stats["reaction_kinds"]),
        "dominant_reaction": str(stats["dominant_reaction"]),
        "data_mode": data_mode,
        "raw_count_values": count_values,
        "possible_view_count": count_values.get("possible_view_count"),
        "possible_forward_count": count_values.get("possible_forward_count"),
        "raw_attribute_counts": count_values.get("attribute_counts") or [],
        "view_confidence": count_values.get("root_count_confidence") if count_values.get("possible_view_count") is not None else "not_available",
        "forward_confidence": count_values.get("root_count_confidence") if count_values.get("possible_forward_count") is not None else "not_available",
        "stable_id": data.get("stableId"),
        "stable_version": data.get("stableVersion"),
        "source_format": source_format or "unknown",
        "dump_hash": dump_hash,
        "extra_metrics": count_values,
        "probe_matches": len(reaction_probe_paths),
        "probe_paths": reaction_probe_paths[:12],
        "probe_summary": reaction_probe_summary[:12],
    }

def _metadata_bool_label(value: Any) -> str:
    if value is None:
        return "—"
    return "sim" if bool(value) else "não"


def _format_metadata_block(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return "<b>Metadados deep salvos</b>\n— nenhum dump salvo para este post ainda"
    raw_counts = _json_load_or_none(metadata.get("raw_attribute_counts_json"))
    if raw_counts is None:
        raw_values = _json_load_or_none(metadata.get("raw_count_values_json"))
        raw_counts = raw_values.get("attribute_counts") if isinstance(raw_values, dict) else []
    possible_views = metadata.get("possible_view_count")
    possible_forwards = metadata.get("possible_forward_count")
    view_confidence = metadata.get("view_confidence") or "—"
    forward_confidence = metadata.get("forward_confidence") or "—"
    stable_label = "—"
    if metadata.get("stable_id") is not None or metadata.get("stable_version") is not None:
        stable_label = f"{metadata.get('stable_id') or '—'} / v{metadata.get('stable_version') or '—'}"
    dump_hash = str(metadata.get("dump_hash") or "—")
    if len(dump_hash) > 16:
        dump_hash = dump_hash[:16]
    return (
        "<b>Metadados deep salvos</b>\n"
        f"texto: <code>{html.escape(str(metadata.get('text_preview') or '—'))}</code>\n"
        f"assinatura: <code>{html.escape(str(metadata.get('signature') or '—'))}</code>\n"
        f"tipo: <code>{html.escape(str(metadata.get('content_type') or '—'))}</code>\n"
        f"canViewList: <code>{_metadata_bool_label(metadata.get('dump_can_view_list'))}</code> · "
        f"recentPeers: <code>{metadata.get('dump_recent_peers_count') or 0}</code> · "
        f"topPeers: <code>{metadata.get('dump_top_peers_count') or 0}</code>\n"
        f"modo dump: <code>{html.escape(str(metadata.get('dump_data_mode') or '—'))}</code> · "
        f"formato: <code>{html.escape(str(metadata.get('source_format') or '—'))}</code>\n"
        f"views/candidato: <code>{possible_views if possible_views is not None else '—'}</code> "
        f"(<code>{html.escape(str(view_confidence))}</code>) · "
        f"forwards/candidato: <code>{possible_forwards if possible_forwards is not None else '—'}</code> "
        f"(<code>{html.escape(str(forward_confidence))}</code>)\n"
        f"counts raiz: <code>{html.escape(str(raw_counts or []))}</code>\n"
        f"stable: <code>{html.escape(stable_label)}</code> · dump hash: <code>{html.escape(dump_hash)}</code>\n"
        f"último deep: <code>{html.escape(str(metadata.get('created_at') or '—'))}</code>"
    )


def _format_deep_result(analysis: dict[str, Any], *, saved_snapshot_lines: list[str] | None = None, db_block: str | None = None) -> str:
    saved_snapshot_lines = saved_snapshot_lines or []
    title = html.escape(str(analysis.get("chat_title") or analysis["chat_id"]))
    username = analysis.get("chat_username")
    username_line = f"@{html.escape(str(username))}" if username else "—"
    text_preview = html.escape(str(analysis.get("text_preview") or "—"))
    signature = html.escape(str(analysis.get("signature") or "—"))
    content_type = html.escape(str(analysis.get("content_type") or "—"))
    post_link = html.escape(str(analysis.get("post_link") or "—"))
    reactions = html.escape(str(analysis.get("reaction_label") or "—"))
    can_view = _metadata_bool_label(analysis.get("can_view_list"))
    are_tags = _metadata_bool_label(analysis.get("are_tags"))
    snapshot_text = "\n".join(saved_snapshot_lines) if saved_snapshot_lines else "—"
    db_text = ("\n\n" + db_block) if db_block else ""
    extra = analysis.get("extra_metrics") or {}
    source_format = html.escape(str(analysis.get("source_format") or "unknown"))
    views_display = extra.get("view_count") if extra.get("view_count") is not None else extra.get("possible_view_count")
    forwards_display = extra.get("forward_count") if extra.get("forward_count") is not None else extra.get("possible_forward_count")
    views_source = extra.get("possible_view_source") or "—"
    forwards_source = extra.get("possible_forward_source") or "—"
    root_counts_display = analysis.get("raw_count_values", {}).get("attribute_counts") if isinstance(analysis.get("raw_count_values"), dict) else None
    extra_metrics_line = (
        f"formato detectado: <code>{source_format}</code>\n"
        f"views/candidato: <code>{views_display if views_display is not None else '—'}</code> "
        f"(<code>{html.escape(str(views_source))}</code>) · "
        f"forwards/candidato: <code>{forwards_display if forwards_display is not None else '—'}</code> "
        f"(<code>{html.escape(str(forwards_source))}</code>) · "
        f"replies: <code>{extra.get('reply_count') if extra.get('reply_count') is not None else '—'}</code>\n"
        f"counts raiz: <code>{html.escape(str(root_counts_display or []))}</code>\n"
    )
    probe_summary = analysis.get("probe_summary") or []
    probe_text = ""
    if probe_summary:
        probe_lines = "\n".join(
            "• " + html.escape(str(line)) for line in probe_summary[:8]
        )
        probe_text = (
            "\n<b>Varredura recursiva</b>\n"
            f"chaves candidatas encontradas: <code>{int(analysis.get('probe_matches') or 0)}</code>\n"
            f"{probe_lines}\n"
        )
    else:
        probe_text = (
            "\n<b>Varredura recursiva</b>\n"
            "chaves candidatas encontradas: <code>0</code>\n"
        )

    no_reactions_note = ""
    if int(analysis.get("reaction_kinds") or 0) == 0:
        if analysis.get("data_mode") == "root_counts_untyped":
            no_reactions_note = (
                "\n<b>Aviso</b>\n"
                "não encontrei emoji/lista de reactions neste dump. Os <code>attributes[].count</code> foram salvos como "
                "candidatos de views/forwards, pendentes de confirmação por MTProto; não foram somados como reactions.\n"
            )
        else:
            no_reactions_note = (
                "\n<b>Aviso</b>\n"
                "não encontrei bloco de reações compatível neste dump; salvei os metadados disponíveis e mantive o diagnóstico local.\n"
                "Se a varredura recursiva abaixo vier zerada, o arquivo provavelmente não contém bloco de reações. "
                "Se vier com caminhos candidatos, o dump usa um formato novo para mapear.\n"
            )
    return (
        "<b>Diagnóstico deep de reações</b>\n\n"
        f"Canal: <b>{title}</b> · <code>{username_line}</code>\n"
        f"Chat ID: <code>{analysis['chat_id']}</code>\n"
        f"Post: <code>{analysis['message_id']}</code>\n"
        f"Link: <code>{post_link}</code>\n\n"
        f"Texto: <code>{text_preview}</code>\n"
        f"Assinatura: <code>{signature}</code>\n"
        f"Tipo: <code>{content_type}</code>\n\n"
        f"Reações dump/API: <code>{reactions}</code>\n"
        f"Total: <code>{analysis.get('total_reactions', 0)}</code> · "
        f"tipos: <code>{analysis.get('reaction_kinds', 0)}</code> · "
        f"dominante: <code>{html.escape(str(analysis.get('dominant_reaction') or '—'))}</code>\n\n"
        "<b>Camada dump/API</b>\n"
        f"canViewList: <code>{can_view}</code>\n"
        f"recentPeers: <code>{analysis.get('recent_peers_count', 0)}</code> · "
        f"topPeers: <code>{analysis.get('top_peers_count', 0)}</code> · "
        f"paidReactors: <code>{analysis.get('paid_reactors_count', 0)}</code>\n"
        f"isTags: <code>{are_tags}</code>\n"
        f"modo: <code>{html.escape(str(analysis.get('data_mode') or '—'))}</code>\n"
        f"{extra_metrics_line}"
        f"{probe_text}\n"
        "<b>Snapshots gravados a partir do dump</b>\n"
        f"{snapshot_text}"
        f"{db_text}"
        f"{no_reactions_note}\n\n"
        "<b>Campos ignorados por segurança</b>\n"
        "<code>accessHash</code>, <code>fileReference</code>, <code>pointerValue</code>, bytes de thumbnail e IDs internos de mídia."
    )

@router.message(Command("preactpost"))
async def reaction_post_stats_command(message: Message) -> None:
    """Mostra diagnóstico estatístico de um post observado."""
    if await _ignore_if_not_owner_dm(message):
        return

    raw_ref = _command_payload(message.text or "")
    if not raw_ref:
        await message.answer(
            "<b>Estatística de post</b>\n\n"
            "Uso: <code>/preactpost https://t.me/nomedocanal/123</code>"
        )
        return

    chat_id, message_id, _, _, _, attempt_lines = await _resolve_post_ref(message, raw_ref)
    if chat_id is None or message_id is None:
        await message.answer(
            "<b>Estatística de post</b>\n\n"
            + "\n".join(f"• {line}" for line in attempt_lines)
            + "\n\nNão consegui resolver o post."
        )
        return

    settings = get_settings()
    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    stats = await _format_snapshot_probe(settings.database_path, chat_id, message_id)
    title = html.escape((watch or {}).get("channel_title") or str(chat_id))
    ref = html.escape((watch or {}).get("post_link") or raw_ref)
    source = html.escape(str((watch or {}).get("source") or "—"))
    await message.answer(
        "<b>Estatística de reação do post</b>\n\n"
        f"Canal: <b>{title}</b>\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Post: <code>{message_id}</code>\n"
        f"Origem: <code>{source}</code>\n"
        f"Ref: <code>{ref}</code>\n\n"
        + stats
    )


@router.message(Command("preacttop"))
async def reaction_top_command(message: Message) -> None:
    """Lista posts com mais reações, com base no último snapshot de cada reação."""
    if await _ignore_if_not_owner_dm(message):
        return

    settings = get_settings()
    rows = await list_recent_reaction_snapshots(settings.database_path, limit=800)
    posts = sorted(_latest_post_totals(rows).values(), key=lambda row: int(row["total"]), reverse=True)[:10]
    if not posts:
        await message.answer("<b>Top reações</b>\n\nNenhum snapshot salvo ainda.")
        return

    lines = []
    for idx, item in enumerate(posts, start=1):
        title = html.escape(str(item.get("channel_title") or item["chat_id"]))
        ref = html.escape(str(item.get("post_link") or ""))
        lines.append(
            f"{idx}. {title} · post <code>{item['message_id']}</code> · "
            f"total: <code>{item['total']}</code> · dominante: <code>{html.escape(str(item.get('dominant') or '—'))}</code>\n"
            f"   <code>{ref}</code>"
        )
    await message.answer("<b>Top reações por post</b>\n\n" + "\n".join(lines))


@router.message(Command("preactfast"))
async def reaction_fast_command(message: Message) -> None:
    """Lista posts com maior delta positivo recente registrado nos snapshots."""
    if await _ignore_if_not_owner_dm(message):
        return

    settings = get_settings()
    rows = await list_recent_reaction_snapshots(settings.database_path, limit=800)
    posts = sorted(
        (item for item in _latest_post_totals(rows).values() if int(item.get("positive_delta") or 0) > 0),
        key=lambda row: int(row["positive_delta"]),
        reverse=True,
    )[:10]
    if not posts:
        await message.answer("<b>Posts em aceleração</b>\n\nAinda não há delta positivo calculado. Ele aparece a partir do segundo snapshot de um post.")
        return

    lines = []
    for idx, item in enumerate(posts, start=1):
        title = html.escape(str(item.get("channel_title") or item["chat_id"]))
        ref = html.escape(str(item.get("post_link") or ""))
        lines.append(
            f"{idx}. {title} · post <code>{item['message_id']}</code> · "
            f"delta recente: <code>+{item['positive_delta']}</code> · total: <code>{item['total']}</code>\n"
            f"   <code>{ref}</code>"
        )
    await message.answer("<b>Posts em aceleração</b>\n\n" + "\n".join(lines))


@router.message(Command("preactresumo"))
async def reaction_summary_command(message: Message) -> None:
    """Resumo compacto de snapshots de reação para a DM do dono."""
    if await _ignore_if_not_owner_dm(message):
        return

    settings = get_settings()
    rows = await list_recent_reaction_snapshots(settings.database_path, limit=1000)
    posts = _latest_post_totals(rows)
    if not posts:
        await message.answer("<b>Resumo de reações</b>\n\nNenhum snapshot salvo ainda.")
        return

    total_posts = len(posts)
    total_reactions = sum(int(item.get("total") or 0) for item in posts.values())
    best = max(posts.values(), key=lambda item: int(item.get("total") or 0))
    fastest = max(posts.values(), key=lambda item: int(item.get("positive_delta") or 0))
    await message.answer(
        "<b>Resumo de reações</b>\n\n"
        f"Posts com snapshot: <code>{total_posts}</code>\n"
        f"Total atual somado: <code>{total_reactions}</code>\n"
        f"Melhor post: <code>{best['message_id']}</code> · total <code>{best['total']}</code>\n"
        f"Maior delta recente: post <code>{fastest['message_id']}</code> · "
        f"<code>+{fastest.get('positive_delta') or 0}</code>\n"
        "Modo predominante: <code>aggregate_anonymous</code> quando o Telegram entrega contagem de canal."
    )


@router.message(Command("preactcsv"))
async def reaction_csv_command(message: Message) -> None:
    """Exporta snapshots recentes em CSV textual na DM do dono."""
    if await _ignore_if_not_owner_dm(message):
        return

    settings = get_settings()
    rows = await list_recent_reaction_snapshots(settings.database_path, limit=200)
    if not rows:
        await message.answer("<b>CSV de reações</b>\n\nNenhum snapshot salvo ainda.")
        return

    header = [
        "chat_id", "message_id", "channel_title", "reaction_key", "reaction_type",
        "total_count", "previous_count", "delta_count", "total_reactions",
        "reaction_kinds", "dominant_reaction", "data_mode", "telegram_date", "captured_at", "post_link",
    ]
    lines = [",".join(header)]
    for row in rows[:120]:
        lines.append(",".join(_snapshot_csv_value(row.get(col)) for col in header))
    csv_text = "\n".join(lines)
    if len(csv_text) > 3500:
        csv_text = csv_text[:3500] + "\n...cortado para caber na mensagem"
    await message.answer("<b>CSV de snapshots recentes</b>\n\n<pre>" + html.escape(csv_text) + "</pre>")


@router.message(Command("preactget"))
async def reaction_get_command(message: Message) -> None:
    """Consulta consolidada de um post já visto/salvo, sem depender do Railway log."""
    if await _ignore_if_not_owner_dm(message):
        return

    raw_ref = _command_payload(message.text or "")
    if not raw_ref:
        await message.answer(
            "<b>Consulta consolidada de reações</b>\n\n"
            "Uso: <code>/preactget 125</code> ou <code>/preactget https://t.me/romastefale/125</code>"
        )
        return

    settings = get_settings()
    if raw_ref.isdigit():
        matches = await find_reaction_posts_by_message_id(settings.database_path, int(raw_ref), limit=8)
        if not matches:
            await message.answer(
                "<b>Consulta consolidada de reações</b>\n\n"
                f"Não encontrei post <code>{html.escape(raw_ref)}</code> nos dados locais."
            )
            return
        if len(matches) > 1:
            lines = []
            for item in matches:
                title = html.escape(str(item.get("channel_title") or item.get("channel_username") or item["chat_id"]))
                ref = html.escape(str(item.get("post_link") or f"channel:{item['chat_id']}/{item['message_id']}"))
                lines.append(f"• {title} · <code>{ref}</code>")
            await message.answer(
                "<b>Consulta consolidada de reações</b>\n\n"
                "Esse ID existe em mais de um contexto. Use uma destas refs:\n" + "\n".join(lines)
            )
            return
        chat_id = int(matches[0]["chat_id"])
        message_id = int(matches[0]["message_id"])
        attempt_lines = [f"Post local: <code>{message_id}</code>", f"Chat ID: <code>{chat_id}</code>"]
        raw_ref = str(matches[0].get("post_link") or f"channel:{chat_id}/{message_id}")
    else:
        chat_id, message_id, _, _, _, attempt_lines = await _resolve_post_ref(message, raw_ref)
        if chat_id is None or message_id is None:
            await message.answer(
                "<b>Consulta consolidada de reações</b>\n\n"
                + "\n".join(f"• {line}" for line in attempt_lines)
                + "\n\nNão consegui resolver o post."
            )
            return

    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    snapshots = await latest_reaction_snapshots(settings.database_path, chat_id, message_id)
    metadata = await get_latest_reaction_post_metadata(settings.database_path, chat_id, message_id)
    snapshot_block = await _format_snapshot_probe(settings.database_path, chat_id, message_id)
    metadata_block = _format_metadata_block(metadata)
    title = html.escape(str((watch or {}).get("channel_title") or (metadata or {}).get("channel_title") or chat_id))
    ref = html.escape(str((watch or {}).get("post_link") or (metadata or {}).get("post_link") or raw_ref))
    current_total = sum(int(row.get("total_count") or 0) for row in snapshots)
    current_reactions = " · ".join(
        _snapshot_summary_line(row) for row in snapshots if int(row.get("total_count") or 0) > 0
    ) or "—"
    await message.answer(
        "<b>Consulta consolidada de reações</b>\n\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        f"Canal: <b>{title}</b>\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Post: <code>{message_id}</code>\n"
        f"Ref: <code>{ref}</code>\n\n"
        "<b>Estado atual por snapshots</b>\n"
        f"reações ativas: {current_reactions}\n"
        f"total ativo: <code>{current_total}</code>\n\n"
        + snapshot_block
        + "\n\n"
        + metadata_block
        + "\n\n<b>Regra de confiança</b>\n"
        "<code>message_reaction_count</code> é a fonte mais forte para reação atual; "
        "dump é evidência complementar; <code>attributes[].count</code> solto permanece como candidato de views/forwards."
    )


@router.message(Command("preactdeep"))
async def reaction_deep_command(message: Message) -> None:
    """Diagnóstico profundo: link/id por banco ou dump JSON por reply/texto."""
    if await _ignore_if_not_owner_dm(message):
        return

    payload = _command_payload(message.text or message.caption or "")
    reply_text = None
    dump_file_text = None
    try:
        if message.reply_to_message:
            reply_text = message.reply_to_message.text or message.reply_to_message.caption
            dump_file_text = await _read_dump_document_text(message.reply_to_message, bot=message.bot)
        if dump_file_text is None:
            dump_file_text = await _read_dump_document_text(message, bot=message.bot)
    except Exception as exc:
        await message.answer(
            "<b>Diagnóstico deep</b>\n\n"
            f"Não consegui ler o arquivo de dump: <code>{html.escape(str(exc))}</code>\n\n"
            "Envie um arquivo <code>.json</code> ou <code>.txt</code> com até 5 MB e responda com <code>/preactdeep</code>."
        )
        return

    dump_text = None
    payload_mode = payload.lower().strip()
    if dump_file_text and (not payload or payload_mode in {"dump", "json", "txt", "file", "arquivo"}):
        dump_text = dump_file_text
    elif reply_text and (not payload or payload_mode in {"dump", "json", "txt", "file", "arquivo"}):
        dump_text = reply_text
    elif payload.strip().startswith(("{", "[", "```")):
        dump_text = payload

    settings = get_settings()
    if dump_text:
        try:
            analysis = _parse_dump_payload(dump_text)
        except Exception as exc:
            await message.answer(
                "<b>Diagnóstico deep</b>\n\n"
                f"Não consegui parametrizar o dump JSON: <code>{html.escape(str(exc))}</code>\n\n"
                "Use reply no dump completo ou em um arquivo .json/.txt e envie <code>/preactdeep</code>."
            )
            return

        await upsert_reaction_watch(
            settings.database_path,
            chat_id=int(analysis["chat_id"]),
            message_id=int(analysis["message_id"]),
            channel_username=analysis.get("chat_username"),
            channel_title=analysis.get("chat_title"),
            post_link=str(analysis.get("post_link") or f"channel:{analysis['chat_id']}/{analysis['message_id']}"),
            created_by=message.from_user.id if message.from_user else None,
            source="dump_deep",
        )
        metadata = await record_reaction_post_metadata(
            settings.database_path,
            chat_id=int(analysis["chat_id"]),
            message_id=int(analysis["message_id"]),
            channel_username=analysis.get("chat_username"),
            channel_title=analysis.get("chat_title"),
            post_link=analysis.get("post_link"),
            text_preview=analysis.get("text_preview"),
            signature=analysis.get("signature"),
            content_type=analysis.get("content_type"),
            dump_can_view_list=analysis.get("can_view_list"),
            dump_recent_peers_count=int(analysis.get("recent_peers_count") or 0),
            dump_top_peers_count=int(analysis.get("top_peers_count") or 0),
            dump_paid_reactors_count=int(analysis.get("paid_reactors_count") or 0),
            dump_are_tags=analysis.get("are_tags"),
            dump_reactions=analysis.get("reaction_items"),
            dump_total_reactions=int(analysis.get("total_reactions") or 0),
            dump_reaction_kinds=int(analysis.get("reaction_kinds") or 0),
            dump_dominant_reaction=str(analysis.get("dominant_reaction") or "—"),
            dump_data_mode=str(analysis.get("data_mode") or "aggregate_anonymous"),
            possible_view_count=analysis.get("possible_view_count"),
            possible_forward_count=analysis.get("possible_forward_count"),
            raw_attribute_counts=analysis.get("raw_attribute_counts"),
            view_confidence=analysis.get("view_confidence"),
            forward_confidence=analysis.get("forward_confidence"),
            stable_id=_safe_int(analysis.get("stable_id")),
            stable_version=_safe_int(analysis.get("stable_version")),
            source_format=str(analysis.get("source_format") or "unknown"),
            dump_hash=str(analysis.get("dump_hash") or ""),
            raw_count_values=analysis.get("raw_count_values"),
            source="preactdeep_dump",
        )

        snapshot_lines: list[str] = []
        duplicate_dump = metadata.get("_upsert_action") == "existing"
        if duplicate_dump:
            snapshot_lines.append("— dump idêntico já estava salvo; snapshots não foram duplicados")
        for item in ([] if duplicate_dump else (analysis.get("reaction_items") or [])):
            snapshot = await record_reaction_snapshot(
                settings.database_path,
                chat_id=int(analysis["chat_id"]),
                message_id=int(analysis["message_id"]),
                reaction_key=str(item["key"]),
                reaction_type=str(item["kind"]),
                total_count=int(item["total"]),
                data_mode=str(analysis.get("data_mode") or "aggregate_anonymous"),
                telegram_date=None,
                total_reactions=int(analysis.get("total_reactions") or 0),
                reaction_kinds=int(analysis.get("reaction_kinds") or 0),
                dominant_reaction=str(analysis.get("dominant_reaction") or "—"),
            )
            snapshot_lines.append("• " + _snapshot_summary_line(snapshot))

        # Counts soltos da raiz do dump são candidatos de views/forwards, não snapshots de reaction.

        _audit_info(
            "preactdeep_dump_saved",
            chat_id=analysis["chat_id"],
            message_id=analysis["message_id"],
            total_reactions=analysis.get("total_reactions"),
            reaction_kinds=analysis.get("reaction_kinds"),
            can_view_list=analysis.get("can_view_list"),
            source_format=analysis.get("source_format"),
            possible_views=analysis.get("possible_view_count"),
            possible_forwards=analysis.get("possible_forward_count"),
            raw_counts=analysis.get("raw_attribute_counts"),
            metadata_id=metadata.get("id"),
            metadata_action=metadata.get("_upsert_action"),
            dump_hash=str(analysis.get("dump_hash") or "")[:16],
        )
        await message.answer(_format_deep_result(analysis, saved_snapshot_lines=snapshot_lines))
        return

    raw_ref = payload.strip()
    if not raw_ref:
        await message.answer(
            "<b>Diagnóstico deep</b>\n\n"
            "Uso por link: <code>/preactdeep https://t.me/romastefale/118</code>\n"
            "Uso por ID já visto: <code>/preactdeep 118</code>\n"
            "Uso por dump: responda ao JSON colado ou a um arquivo .json/.txt com <code>/preactdeep</code>."
        )
        return

    if raw_ref.isdigit():
        matches = await find_reaction_posts_by_message_id(settings.database_path, int(raw_ref), limit=8)
        if not matches:
            await message.answer(
                "<b>Diagnóstico deep</b>\n\n"
                f"Não encontrei post <code>{html.escape(raw_ref)}</code> nos dados locais. Use link completo ou responda a um dump."
            )
            return
        if len(matches) > 1:
            lines = []
            for item in matches:
                title = html.escape(str(item.get("channel_title") or item.get("channel_username") or item["chat_id"]))
                ref = html.escape(str(item.get("post_link") or f"channel:{item['chat_id']}/{item['message_id']}"))
                lines.append(f"• {title} · <code>{ref}</code>")
            await message.answer(
                "<b>Diagnóstico deep</b>\n\n"
                "Esse ID existe em mais de um contexto. Use uma destas refs:\n" + "\n".join(lines)
            )
            return
        chat_id = int(matches[0]["chat_id"])
        message_id = int(matches[0]["message_id"])
        attempt_lines = [f"Post local: <code>{message_id}</code>", f"Chat ID: <code>{chat_id}</code>"]
    else:
        chat_id, message_id, _, _, _, attempt_lines = await _resolve_post_ref(message, raw_ref)
        if chat_id is None or message_id is None:
            await message.answer(
                "<b>Diagnóstico deep</b>\n\n"
                + "\n".join(f"• {line}" for line in attempt_lines)
                + "\n\nNão consegui resolver o post."
            )
            return

    watch = await get_reaction_watch(settings.database_path, chat_id, message_id)
    snapshots = await latest_reaction_snapshots(settings.database_path, chat_id, message_id)
    metadata = await get_latest_reaction_post_metadata(settings.database_path, chat_id, message_id)
    snapshot_block = await _format_snapshot_probe(settings.database_path, chat_id, message_id)
    metadata_block = _format_metadata_block(metadata)
    title = html.escape(str((watch or {}).get("channel_title") or (metadata or {}).get("channel_title") or chat_id))
    ref = html.escape(str((watch or {}).get("post_link") or (metadata or {}).get("post_link") or raw_ref))
    await message.answer(
        "<b>Diagnóstico deep de reações</b>\n\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        f"Canal: <b>{title}</b>\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Post: <code>{message_id}</code>\n"
        f"Ref: <code>{ref}</code>\n\n"
        + snapshot_block
        + "\n\n"
        + metadata_block
        + "\n\n"
        + ("<b>Conclusão</b>\nHá snapshots locais para este post." if snapshots else "<b>Conclusão</b>\nAinda não há snapshot local para este post.")
    )


@router.message(Command("preact"))
async def reaction_probe_command(message: Message) -> None:
    """Diagnostica e tenta o máximo permitido pelo Bot API para um link de post."""
    if await _ignore_if_not_owner_dm(message):
        return

    raw_ref = _command_payload(message.text or "")
    if not raw_ref:
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            "Uso: <code>/preact https://t.me/nomedocanal/123</code>\n\n"
            "Posts de canal vistos pelo bot admin entram automaticamente em monitoramento. "
            "Para um post específico, também pode usar <code>/preactwatch LINK</code>."
        )
        return

    chat_id, message_id, _, _, _, attempt_lines = await _resolve_post_ref(message, raw_ref)
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
        snapshots = await _format_snapshot_probe(settings.database_path, chat_id, message_id)
        cached = _format_cached_probe(chat_id, message_id)
    else:
        persisted = (
            "<b>Watchlist persistente</b>\n"
            "— não consegui resolver o canal, então não deu para consultar por chat_id"
        )
        snapshots = (
            "<b>Estatística por snapshot</b>\n"
            "— não consegui resolver o canal, então não deu para cruzar snapshots por chat_id"
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
        + snapshots
        + "\n\n"
        + cached
        + "\n\n"
        "<b>Limite real</b>\n"
        "O Bot API não tem método para buscar o histórico de quem reagiu em post antigo. "
        "Para os próximos posts, todo post de canal que o bot admin receber via <code>channel_post</code> "
        "entra em monitoramento automático; quando o Telegram entregar reação ou contagem, "
        "o pCurator salva e avisa na DM do dono."
    )
