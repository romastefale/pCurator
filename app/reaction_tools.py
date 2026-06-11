import html
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

# Memória curta, propositalmente volátil: não altera banco nem fluxo editorial.
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
            lines.append(f"{reaction}: <code>{total}</code>")
    return "\n".join(lines)


def _actor_label(update: MessageReactionUpdated) -> str:
    user = getattr(update, "user", None)
    if user:
        name = html.escape(user.full_name or str(user.id))
        username = f" @{html.escape(user.username)}" if user.username else ""
        return f"{name}{username} · <code>{user.id}</code>"

    actor_chat = getattr(update, "actor_chat", None)
    if actor_chat:
        title = html.escape(actor_chat.title or str(actor_chat.id))
        return f"{title} · <code>{actor_chat.id}</code>"

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
        parts.append("<b>Contagem recebida desde que o bot iniciou</b>\n" + counts)
    else:
        parts.append("<b>Contagem recebida desde que o bot iniciou</b>\n—")

    if events:
        parts.append("<b>Eventos identificados recebidos desde que o bot iniciou</b>\n" + "\n".join(events[-_MAX_EVENTS_PER_POST:]))
    else:
        parts.append(
            "<b>Eventos identificados recebidos desde que o bot iniciou</b>\n"
            "— nenhum evento individual recebido ainda"
        )

    return "\n\n".join(parts)


@router.message_reaction()
async def reaction_update_handler(update: MessageReactionUpdated) -> None:
    """Registra reações futuras quando o Telegram entrega update identificado."""
    chat_id = update.chat.id
    message_id = update.message_id
    actor = _actor_label(update)
    old_reaction = _reaction_list_label(update.old_reaction)
    new_reaction = _reaction_list_label(update.new_reaction)
    moment = datetime.now().strftime("%H:%M:%S")

    line = (
        f"• <code>{moment}</code> — {actor}: "
        f"<code>{html.escape(old_reaction)}</code> → <code>{html.escape(new_reaction)}</code>"
    )
    _store_event(chat_id, message_id, line)
    logger.info("reaction_update chat_id=%s message_id=%s", chat_id, message_id)


@router.message_reaction_count()
async def reaction_count_handler(update: MessageReactionCountUpdated) -> None:
    """Registra contagem futura quando o Telegram só entrega agregado/anônimo."""
    chat_id = update.chat.id
    message_id = update.message_id
    _REACTION_COUNTS[(chat_id, message_id)] = _reaction_count_label(update.reactions)
    logger.info("reaction_count_update chat_id=%s message_id=%s", chat_id, message_id)


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
            "O comando tenta resolver o canal, checar o acesso do bot e mostrar "
            "eventos de reação futura que o Telegram já tenha entregue."
        )
        return

    private_link = _parse_private_post_link(raw_link)
    if private_link:
        internal_id, message_id = private_link
        logger.info("preact_private_link internal_id=%s message_id=%s", internal_id, message_id)
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            f"Link recebido: <code>{html.escape(raw_link)}</code>\n"
            "Tipo: link interno <code>t.me/c/...</code>\n"
            f"Post: <code>{message_id}</code>\n\n"
            "Tentativa possível neste incremento: não consigo resolver <code>t.me/c/...</code> "
            "sem o ID real do chat. Use link público com username, no formato:\n"
            "<code>https://t.me/nomedocanal/123</code>\n\n"
            "Limite do Telegram: para canal broadcast, o Bot API normalmente só "
            "entrega contagem agregada/anônima de reações futuras, não a lista histórica de usuários."
        )
        return

    parsed = _parse_public_post_link(raw_link)
    if not parsed:
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            "Link inválido para este comando.\n"
            "Use: <code>/preact https://t.me/nomedocanal/123</code>"
        )
        return

    channel, message_id = parsed
    logger.info("preact_public_link channel=%s message_id=%s", channel, message_id)

    attempt_lines = [
        f"Canal informado: <code>@{html.escape(channel)}</code>",
        f"Post: <code>{message_id}</code>",
    ]

    chat_id: int | None = None
    try:
        chat = await message.bot.get_chat(f"@{channel}")
        chat_id = chat.id
        title = html.escape(chat.title or chat.full_name or f"@{channel}")
        attempt_lines.append(f"getChat: ok — {title} · <code>{chat.id}</code>")

        bot_user = await message.bot.get_me()
        try:
            member = await message.bot.get_chat_member(chat.id, bot_user.id)
            attempt_lines.append(f"bot no canal: <code>{html.escape(member.status)}</code>")
        except TelegramAPIError as exc:
            attempt_lines.append(
                "bot no canal: não confirmado — "
                f"<code>{html.escape(type(exc).__name__)}</code>"
            )

    except TelegramAPIError as exc:
        attempt_lines.append(
            "getChat: falhou — "
            f"<code>{html.escape(type(exc).__name__)}</code>"
        )

    if chat_id is not None:
        cached = _format_cached_probe(chat_id, message_id)
    else:
        cached = (
            "<b>Eventos recebidos</b>\n"
            "— não consegui resolver o canal, então não deu para cruzar cache por chat_id"
        )

    await message.answer(
        "<b>Diagnóstico de reações</b>\n\n"
        "<b>Tentativas feitas agora</b>\n"
        + "\n".join(f"• {line}" for line in attempt_lines)
        + "\n\n"
        + cached
        + "\n\n"
        "<b>Limite real</b>\n"
        "O Bot API não tem método para buscar o histórico de quem reagiu em post antigo. "
        "Este comando tenta o que é possível: acesso do bot + reações futuras recebidas "
        "por <code>message_reaction</code> e <code>message_reaction_count</code>."
    )
