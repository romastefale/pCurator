import asyncio
import json
import logging
import re
import uuid

from aiogram import Bot

from app.services.editorial_schema import PUBLIC_POST_JSON_SCHEMA
from app.settings import get_settings
from app.types import ArticleIntake, PublicPost

logger = logging.getLogger(__name__)

_PENDING: dict[str, asyncio.Future[str]] = {}


def _schema_instruction() -> str:
    return json.dumps(PUBLIC_POST_JSON_SCHEMA["schema"], ensure_ascii=False)


def build_mira_prompt(article: ArticleIntake, channel_slug: str, risk_score: int) -> tuple[str, str]:
    channel_hint = (
        "Canal 1: leve, pop, cultura digital, celebridades, comportamento e entretenimento. Evite política, religião, crime pesado, tragédia e tema excessivamente sensível."
        if channel_slug == "c1"
        else "Canal 2: jornalístico, sério, público adulto, com linguagem direta, cautelosa e imparcial."
    )
    request_id = uuid.uuid4().hex[:12]
    prompt = f"""
Mira, responda este pedido em JSON puro, sem markdown, sem texto antes e sem texto depois.

ID do pedido: {request_id}

Você vai transformar uma matéria extraída de site em uma legenda curta para Telegram.

Regras obrigatórias:
- Não copie a raspagem literalmente.
- Não use 'Via:'.
- Não use 'Prévia editorial'.
- Não coloque o nome da fonte no título.
- Não use '| G1', '- G1', '| UOL', '| CNN' ou sufixos parecidos.
- Não inclua autoria, data de atualização ou 'Oferecido por'.
- Gere título reescrito, subtítulo contextual e corpo resumido.
- O corpo deve ser jornalístico, curto, claro e sem clickbait.
- O resumo deve terminar em frase completa, sem corte seco no meio da ideia.
- Se a confiança for baixa, use linguagem cautelosa.
- Se o assunto não for adequado ao canal, marque publishable=false e needs_review=true.

Responda obedecendo este JSON Schema:
{_schema_instruction()}

Canal: {channel_slug}
Critério do canal: {channel_hint}
Risco editorial calculado: {risk_score}
Fonte: {article.source}
URL: {article.url}
Título bruto: {article.raw_title}
Título limpo: {article.clean_title}
Texto limpo extraído:
{article.clean_text[:5000]}
""".strip()
    return request_id, prompt


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


def _post_from_dict(data: dict, article: ArticleIntake) -> PublicPost:
    return PublicPost(
        hashtags=list(data.get("hashtags") or []),
        title=str(data.get("title") or article.clean_title),
        subtitle=str(data.get("subtitle") or ""),
        body=str(data.get("body") or ""),
        source_url=str(data.get("source_url") or article.url),
        publishable=bool(data.get("publishable", True)),
        needs_review=bool(data.get("needs_review", False)),
        quality_notes=list(data.get("quality_notes") or []),
    )


async def request_mira_public_post(bot: Bot, article: ArticleIntake, channel_slug: str, risk_score: int = 100) -> PublicPost:
    settings = get_settings()
    request_id, prompt = build_mira_prompt(article, channel_slug, risk_score)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _PENDING[request_id] = future

    try:
        sent = await bot.send_message(
            chat_id=settings.mira_group_id,
            text=prompt,
            disable_web_page_preview=True,
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
        return False
    request_id = match.group(1)
    future = _PENDING.get(request_id)
    if not future or future.done():
        return False
    future.set_result(response_text)
    logger.info("mira_response_received request_id=%s", request_id)
    return True
