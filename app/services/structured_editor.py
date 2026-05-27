import json
import logging
import re

from openai import AsyncOpenAI

from app.services.editorial_schema import PUBLIC_POST_JSON_SCHEMA
from app.settings import get_settings
from app.types import ArticleIntake, PublicPost

logger = logging.getLogger(__name__)


def _split_sentences(text: str) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip()]


def _complete_summary(text: str, max_chars: int = 580) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return "O conteúdo extraído precisa de revisão manual antes de publicação."

    selected: list[str] = []
    total = 0
    for sentence in sentences:
        next_total = total + len(sentence) + (1 if selected else 0)
        if selected and next_total > max_chars:
            break
        selected.append(sentence)
        total = next_total
        if len(selected) >= 4:
            break

    if not selected[-1].endswith((".", "!", "?")):
        selected[-1] = selected[-1] + "."

    # Agrupa de 2 em 2 frases por parágrafo — fallback também respeita o estilo
    # de "uma ideia por parágrafo" para o renderer não emendar tudo numa linha só.
    paragraphs: list[str] = []
    for i in range(0, len(selected), 2):
        paragraphs.append(" ".join(selected[i : i + 2]))
    return "\n\n".join(paragraphs)


def _fallback_subtitle(article: ArticleIntake) -> str:
    sentences = _split_sentences(article.clean_text)
    for sentence in sentences:
        if 40 <= len(sentence) <= 180:
            return sentence
    return "A informação principal foi extraída da matéria e deve ser revisada antes da publicação."


def _fallback_public_post(article: ArticleIntake, channel_slug: str, reason: str = "fallback_local_sem_ia") -> PublicPost:
    base_hashtags = ["Notícia", "Atualidade", "Curadoria"]
    if "copa" in f"{article.clean_title} {article.clean_text}".lower():
        base_hashtags = ["Notícia", "Copa2026", "SeleçãoBrasileira"]

    body = _complete_summary(article.clean_text)

    return PublicPost(
        hashtags=base_hashtags,
        title=article.clean_title[:110].strip() or "Notícia em revisão",
        subtitle=_fallback_subtitle(article),
        body=body,
        source_url=article.url,
        needs_review=True,
        quality_notes=[reason],
    )


def _post_from_dict(data: dict, article: ArticleIntake) -> PublicPost:
    return PublicPost(
        hashtags=list(data.get("hashtags") or []),
        title=str(data.get("title") or article.clean_title),
        subtitle=str(data.get("subtitle") or ""),
        body=str(data.get("body") or ""),
        source_url=str(data.get("source_url") or article.url),
        needs_review=bool(data.get("needs_review", False)),
        quality_notes=list(data.get("quality_notes") or []),
    )


async def generate_structured_public_post(article: ArticleIntake, channel_slug: str, risk_score: int = 100) -> PublicPost:
    settings = get_settings()
    if not settings.openai_key:
        logger.warning("OpenAI key missing; using local editorial fallback")
        return _fallback_public_post(article, channel_slug, "openai_key_missing")

    channel_hint = (
        "Canal 1: leve, pop, cultura digital, celebridades, comportamento e entretenimento. Evite política, religião, crime pesado, tragédia e tema excessivamente sensível."
        if channel_slug == "c1"
        else "Canal 2: jornalístico, sério, público adulto, com linguagem direta, cautelosa e imparcial."
    )

    prompt = f"""
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
- Estruture o body em 1 a 3 parágrafos curtos separados por duas quebras de linha (\\n\\n). Cada parágrafo agrupa frases que pertencem à mesma ideia; não isole cada frase em parágrafo próprio.
- O body deve ter no MÁXIMO 580 caracteres (limite rígido) — caso contrário a foto perde a legenda no Telegram. Prefira ~400 caracteres para folga.
- Se a confiança for baixa, use linguagem cautelosa.
- Se o assunto exigir cautela editorial, marque needs_review=true (a decisão de publicar é sempre humana).

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

    try:
        client = AsyncOpenAI(api_key=settings.openai_key)
        response = await client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": "Você é um editor jornalístico para Telegram. Responda apenas no schema solicitado."},
                {"role": "user", "content": prompt},
            ],
            text={"format": {"type": "json_schema", **PUBLIC_POST_JSON_SCHEMA}},
            temperature=0.35,
        )
        content = response.output_text
        data = json.loads(content)
        return _post_from_dict(data, article)
    except Exception as exc:
        logger.exception("OpenAI structured editorial generation failed: %s", type(exc).__name__)
        return _fallback_public_post(article, channel_slug, f"openai_error:{type(exc).__name__}")
