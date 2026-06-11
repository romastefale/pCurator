import html
import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

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


@router.message(Command("preact"))
async def reaction_probe_command(message: Message) -> None:
    """Diagnostica o que o Bot API consegue fazer com um link de post."""
    if await reject_message_if_not_allowed(message):
        return

    raw_link = _command_payload(message.text or "")
    if not raw_link:
        await message.answer(
            "<b>Diagnóstico de reações</b>\n\n"
            "Uso: <code>/preact https://t.me/nomedocanal/123</code>\n\n"
            "Este comando não promete listar quem reagiu. Ele valida o link e mostra "
            "o limite real do Telegram para post de canal."
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
            "Este incremento inicial aceita link público com username, no formato:\n"
            "<code>https://t.me/nomedocanal/123</code>\n\n"
            "Para canal broadcast, mesmo sendo seu canal, o Bot API normalmente só "
            "entrega contagem agregada/anônima de reações futuras, não a lista de usuários."
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

    await message.answer(
        "<b>Diagnóstico de reações</b>\n\n"
        f"Canal: <code>@{html.escape(channel)}</code>\n"
        f"Post: <code>{message_id}</code>\n\n"
        "<b>Resultado seguro</b>\n"
        "• O Bot API não permite buscar o histórico de quem reagiu em um post antigo.\n"
        "• Em canal broadcast, o Telegram tende a entregar apenas contagem agregada/anônima.\n"
        "• Se alguém prometer revelar todos os usuários de um post de canal já publicado, "
        "trate como suspeito, principalmente se pedir sessão, QR code ou pasta <code>tdata</code>.\n\n"
        "<b>Próximo incremento possível</b>\n"
        "Adicionar monitoramento de reações futuras com <code>message_reaction</code> e "
        "<code>message_reaction_count</code>. Em canal, o esperado ainda é contagem; "
        "em grupo/supergrupo pode aparecer usuário quando o Telegram entregar reação identificada."
    )
