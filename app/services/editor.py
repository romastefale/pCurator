from openai import AsyncOpenAI

from app.settings import get_settings
from app.types import ItemData, RenderedPost

SYSTEM_PROMPT = """
Você é o editor do pCurator, uma redação privada para Telegram.
Gere uma publicação curta, fiel ao fato e pronta para legenda HTML.
Não invente dados. Não use tom sensacionalista.
Respeite o formato: 3 hashtags, título em negrito, subtítulo em itálico, corpo em blockquote itálico, via no rodapé.
""".strip()


def _fallback_post(item: ItemData) -> RenderedPost:
    text = (
        "#Notícia #Atualidade #Curadoria\n\n"
        f"<b>{item.title}</b>\n\n"
        "<i>Resumo editorial pendente de revisão final.</i>\n\n"
        f"<blockquote><i>{item.text[:420].strip()}</i></blockquote>\n\n"
        f"<i>Via: {item.source}.</i>"
        f"<a href=\"{item.url}\">&#8203;</a>"
    )
    return RenderedPost(text=text, image_url=item.image_url)


async def generate_editorial_post(item: ItemData, channel_slug: str) -> RenderedPost:
    settings = get_settings()
    if not settings.openai_key:
        return _fallback_post(item)

    client = AsyncOpenAI(api_key=settings.openai_key)
    channel_hint = (
        "Canal 1: leve, pop, cultura digital, sem política/religião/temas pesados."
        if channel_slug == "c1"
        else "Canal 2: sério, jornalístico, maduro, imparcial, aceita política com cautela."
    )

    user_prompt = f"""
Canal: {channel_slug}
Regra do canal: {channel_hint}
Fonte: {item.source}
URL: {item.url}
Título original: {item.title}
Texto extraído:
{item.text[:4000]}

Gere apenas o post final em HTML, sem explicações.
""".strip()

    response = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        return _fallback_post(item)

    return RenderedPost(text=content.strip(), image_url=item.image_url)
