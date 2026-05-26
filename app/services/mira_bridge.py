import asyncio
import json
import logging
import re
import uuid

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from app.settings import get_settings
from app.types import ArticleIntake, PublicPost

logger = logging.getLogger(__name__)
_PENDING: dict[str, asyncio.Future[str]] = {}


def build_mira_prompt(article: ArticleIntake, channel_slug: str, risk_score: int) -> tuple[str, str]:
    request_id = uuid.uuid4().hex[:12]
    prefix = "Mi" + "ra, "
    prompt = (
        prefix
        + "responda em JSON puro, sem markdown e sem explicações.\n\n"
        + f"ID do pedido: {request_id}\n\n"
        + "Campos obrigatórios: hashtags, title, subtitle, body, source_url, publishable, needs_review, quality_notes.\n\n"
        + "Regras: reescreva como resumo editorial para Telegram; não copie a raspagem; não use Via, Prévia editorial, Oferecido por, Por Redação ou Atualizado; não coloque fonte no título; termine em frase completa; use 3 ou 4 hashtags.\n\n"
        + f"Canal: {channel_slug}\nRisco: {risk_score}\nFonte: {article.source}\nURL: {article.url}\nTítulo: {article.clean_title}\nTexto:\n{article.clean_text[:2600]}"
    )
    return request_id, prompt[:3900]


def _extract_json(text: str) -> dict | None:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = re.split(r"[,#;\n]+", value)
        return [part.strip().lstrip("#") for part in parts if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _post_from_dict(data: dict, article: ArticleIntake) -> PublicPost:
    return PublicPost(
        hashtags=_as_list(data.get("hashtags")),
        title=str(data.get("title") or article.clean_title),
        subtitle=str(data.get("subtitle") or ""),
        body=str(data.get("body") or ""),
        source_url=str(data.get("source_url") or article.url),
        publishable=bool(data.get("publishable", True)),
        needs_review=bool(data.get("needs_review", False)),
        quality_notes=_as_list(data.get("quality_notes")),
    )


async def request_mira_public_post(bot: Bot, article: ArticleIntake, channel_slug: str, risk_score: int = 100) -> PublicPost:
    settings = get_settings()
    if settings.mira_group_id is None:
        raise RuntimeError("mira_group_id_not_configured")
    request_id, prompt = build_mira_prompt(article, channel_slug, risk_score)
    future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    _PENDING[request_id] = future
    try:
        sent = await bot.send_message(
            settings.mira_group_id,
            prompt,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        logger.info("mira_request_sent request_id=%s message_id=%s", request_id, sent.message_id)
        response_text = await asyncio.wait_for(future, timeout=settings.mira_timeout_seconds)
        data = _extract_json(response_text)
        if not data:
            raise ValueError("mira_invalid_json")
        post = _post_from_dict(data, article)
        post.quality_notes.append("mira_used")
        return post
    finally:
        _PENDING.pop(request_id, None)


async def resolve_mira_response(reply_to_text: str | None, response_text: str | None) -> bool:
    if not reply_to_text or not response_text:
        return False
    match = re.search(r"ID do pedido:\s*([a-f0-9]{12})", reply_to_text, flags=re.IGNORECASE)
    if not match:
        logger.info("mira_response_ignored reason=request_id_not_found")
        return False
    request_id = match.group(1)
    future = _PENDING.get(request_id)
    if not future or future.done():
        logger.info("mira_response_ignored reason=no_pending_request request_id=%s", request_id)
        return False
    future.set_result(response_text)
    logger.info("mira_response_resolved request_id=%s", request_id)
    return True
