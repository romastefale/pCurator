from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.settings import get_settings
from app.storage.posts import list_recent_posts
from app.storage.sources import list_sources

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
