import json

from openai import AsyncOpenAI

from app.services.editorial_schema import PUBLIC_POST_JSON_SCHEMA
from app.settings import get_settings
from app.types import ArticleIntake, PublicPost


def _fallback_public_post(article: ArticleIntake, channel_slug: str) -> PublicPost:
    base_hashtags = ["Notícia", "Atualidade", "Curadoria"]
    if "copa" in f"{article.clean_title} {article.clean_text}".lower():
        base_hashtags = ["Notícia", "Copa2026", "SeleçãoBrasileira"]

    body = article.clean_text[:520].strip()
    if not body:
        body = "O conteúdo extraído precisa de revisão manual antes de publicação."

    return PublicPost(
        hashtags=base_hashtags,
        title=article.clean_title[:110].strip() or "Notícia em revisão",
        subtitle="Resumo editorial gerado a partir das informações principais da matéria.",
        body=body,
        source_url=article.url,
        publishable=bool(article.clean_text),
        needs_review=True,
        quality_notes=["fallback_local_sem_ia"],
    )


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


async def generate_structured_public_post(article: ArticleIntake, channel_slug: str, risk_score: int = 100) -> PublicPost:
    settings = get_settings()
    if not settings.openai_key:
        return _fallback_public_post(article, channel_slug)

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
- Se a confiança for baixa, use linguagem cautelosa.
- Se o assunto não for adequado ao canal, marque publishable=false e needs_review=true.

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
            text={"format": {"type": "json_schema", "json_schema": PUBLIC_POST_JSON_SCHEMA}},
            temperature=0.35,
        )
        content = response.output_text
        data = json.loads(content)
        return _post_from_dict(data, article)
    except Exception:
        return _fallback_public_post(article, channel_slug)
