from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.settings import get_settings
from app.storage.posts import list_recent_posts
from app.storage.sources import list_sources, upsert_source

router = Router()


@router.message(Command("start"))
async def start_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    await message.answer(
        "<b>pCurator ativo.</b>\n\n"
        "Envie um link de notícia para iniciar uma curadoria manual.\n"
        "Use /ph para ver os comandos disponíveis.",
        parse_mode="HTML",
    )


@router.message(Command("ph"))
async def help_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    await message.answer(
        "<b>Comandos pCurator</b>\n\n"
        "/start — estado inicial\n"
        "/ph — ajuda rápida\n"
        "/ps — status técnico\n"
        "/pq — fila editorial\n"
        "/pf — fontes\n"
        "/pfa Nome | url | escopo | nota — cadastrar fonte\n"
        "/pr — regras aprendidas\n",
        parse_mode="HTML",
    )


@router.message(Command("ps"))
async def status_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    c1 = "configurado" if settings.channel_1_id else "pendente"
    c2 = "configurado" if settings.channel_2_id else "pendente"

    await message.answer(
        "<b>Status pCurator</b>\n\n"
        "Base: carregada\n"
        f"Banco: <code>{settings.database_path}</code>\n"
        f"Canal 1: {c1}\n"
        f"Canal 2: {c2}\n"
        "Modo atual: manual assistido\n",
        parse_mode="HTML",
    )


@router.message(Command("pq"))
async def queue_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    posts = await list_recent_posts(settings.database_path, limit=5)

    if not posts:
        await message.answer("Fila editorial vazia.")
        return

    lines = ["<b>Últimos rascunhos</b>", ""]
    for post in posts:
        image_status = "com imagem" if post.get("image_url") else "sem imagem"
        lines.append(
            f"#{post['id']} · {post['status']} · {post['channel_slug']} · {image_status}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("pf"))
async def sources_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    sources = await list_sources(settings.database_path, limit=10)

    if not sources:
        await message.answer("Nenhuma fonte cadastrada ainda.")
        return

    lines = ["<b>Fontes cadastradas</b>", ""]
    for source in sources:
        state = "bloqueada" if source["is_blocked"] else "ativa"
        lines.append(
            f"#{source['id']} · {source['name']} · {source['scope']} · {source['quality_score']} · {state}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("pfa"))
async def add_source_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    text = message.text or ""
    raw = text.replace("/pfa", "", 1).strip()
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) < 1 or not parts[0]:
        await message.answer(
            "Formato: <code>/pfa Nome | url | escopo | nota</code>\n"
            "Exemplo: <code>/pfa G1 | https://g1.globo.com | global | 80</code>",
            parse_mode="HTML",
        )
        return

    name = parts[0]
    url = parts[1] if len(parts) > 1 and parts[1] else None
    scope = parts[2] if len(parts) > 2 and parts[2] else "global"

    try:
        quality_score = int(parts[3]) if len(parts) > 3 and parts[3] else 70
    except ValueError:
        quality_score = 70

    quality_score = max(0, min(100, quality_score))
    settings = get_settings()
    source_id = await upsert_source(
        settings.database_path,
        name=name,
        url=url,
        scope=scope,
        quality_score=quality_score,
    )

    await message.answer(
        f"Fonte cadastrada: #{source_id} · {name} · {scope} · {quality_score}"
    )
