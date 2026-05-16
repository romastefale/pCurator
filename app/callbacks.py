from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.settings import get_settings
from app.storage.events import log_event

router = Router()


async def _log_choice(callback: CallbackQuery, channel_slug: str, event_type: str) -> None:
    settings = get_settings()
    await log_event(
        settings.database_path,
        channel_slug=channel_slug,
        event_type=event_type,
        payload={"user_id": callback.from_user.id, "data": callback.data},
    )


@router.callback_query(F.data == "channel:c1")
async def choose_c1(callback: CallbackQuery) -> None:
    await _log_choice(callback, "c1", "channel_selected")
    await callback.answer("Canal 1 selecionado")
    if callback.message:
        await callback.message.answer("📘 Canal 1 selecionado. Próxima etapa: revisão editorial.")


@router.callback_query(F.data == "channel:c2")
async def choose_c2(callback: CallbackQuery) -> None:
    await _log_choice(callback, "c2", "channel_selected")
    await callback.answer("Canal 2 selecionado")
    if callback.message:
        await callback.message.answer("📰 Canal 2 selecionado. Próxima etapa: revisão editorial.")


@router.callback_query(F.data == "channel:ignore")
async def ignore_channel(callback: CallbackQuery) -> None:
    await _log_choice(callback, None, "channel_ignored")
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")
