import html
import json
import logging
import re
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
    get_reaction_watch,
    latest_reaction_snapshots,
    list_recent_reaction_snapshots,
    list_reaction_events,
    list_reaction_watches,
    reaction_event_count,
    record_reaction_event,
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
