from aiogram import F, Router
from aiogram.types import CallbackQuery

router = Router()


@router.callback_query(F.data == "channel:c1")
async def choose_c1(callback: CallbackQuery) -> None:
    await callback.answer("Canal 1 selecionado")
    if callback.message:
        await callback.message.answer("📘 Canal 1 selecionado. Próxima etapa: revisão editorial.")


@router.callback_query(F.data == "channel:c2")
async def choose_c2(callback: CallbackQuery) -> None:
    await callback.answer("Canal 2 selecionado")
    if callback.message:
        await callback.message.answer("📰 Canal 2 selecionado. Próxima etapa: revisão editorial.")


@router.callback_query(F.data == "channel:ignore")
async def ignore_channel(callback: CallbackQuery) -> None:
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")
