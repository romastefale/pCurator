from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.access import reject_message_if_not_owner

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

    await message.answer("pCurator em preparação. Fundação carregada.")
