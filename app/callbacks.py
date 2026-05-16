from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.settings import get_settings
from app.storage.events import log_event
from app.storage.session import get_active_post, set_active_post
from app.ui import review_keyboard

router = Router()


async def _log_choice(callback: CallbackQuery, channel_slug: str | None, event_type: str) -> None:
    settings = get_settings()
    post_id, mode = await get_active_post(settings.database_path, callback.from_user.id)
    await log_event(
        settings.database_path,
        channel_slug=channel_slug,
        event_type=event_type,
        payload={
            "user_id": callback.from_user.id,
            "data": callback.data,
            "post_id": post_id,
            "mode": mode,
        },
    )


async def _active_post_id(callback: CallbackQuery) -> int | None:
    settings = get_settings()
    post_id, _ = await get_active_post(settings.database_path, callback.from_user.id)
    return post_id


@router.callback_query(F.data == "channel:c1")
async def choose_c1(callback: CallbackQuery) -> None:
    await _log_choice(callback, "c1", "channel_selected")
    await callback.answer("Canal 1 selecionado")
    if callback.message:
        await callback.message.answer(
            "📘 Canal 1 selecionado. Revise o rascunho antes de publicar.",
            reply_markup=review_keyboard(),
        )


@router.callback_query(F.data == "channel:c2")
async def choose_c2(callback: CallbackQuery) -> None:
    await _log_choice(callback, "c2", "channel_selected")
    await callback.answer("Canal 2 selecionado")
    if callback.message:
        await callback.message.answer(
            "📰 Canal 2 selecionado. Revise o rascunho antes de publicar.",
            reply_markup=review_keyboard(),
        )


@router.callback_query(F.data == "channel:ignore")
async def ignore_channel(callback: CallbackQuery) -> None:
    await _log_choice(callback, None, "channel_ignored")
    settings = get_settings()
    await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=None, mode=None)
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")


@router.callback_query(F.data == "post:publish")
async def review_publish(callback: CallbackQuery) -> None:
    post_id = await _active_post_id(callback)
    await _log_choice(callback, None, "publish_requested")
    await callback.answer("Publicação solicitada")
    if callback.message:
        if post_id is None:
            await callback.message.answer("Nenhum rascunho ativo encontrado.")
            return
        await callback.message.answer(f"✅ Pedido de publicação registrado para o post #{post_id}.")


@router.callback_query(F.data == "post:edit")
async def review_edit(callback: CallbackQuery) -> None:
    post_id = await _active_post_id(callback)
    await _log_choice(callback, None, "edit_requested")
    await callback.answer("Edição solicitada")
    if callback.message:
        if post_id is None:
            await callback.message.answer("Nenhum rascunho ativo encontrado.")
            return
        settings = get_settings()
        await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=post_id, mode="edit_text")
        await callback.message.answer(f"✏️ Envie o novo texto da legenda para substituir o post #{post_id}.")


@router.callback_query(F.data == "post:image")
async def review_image(callback: CallbackQuery) -> None:
    post_id = await _active_post_id(callback)
    await _log_choice(callback, None, "image_requested")
    await callback.answer("Imagem solicitada")
    if callback.message:
        if post_id is None:
            await callback.message.answer("Nenhum rascunho ativo encontrado.")
            return
        settings = get_settings()
        await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=post_id, mode="edit_image")
        await callback.message.answer(f"🖼 Envie a nova imagem para o post #{post_id}.")


@router.callback_query(F.data == "post:ignore")
async def review_ignore(callback: CallbackQuery) -> None:
    await _log_choice(callback, None, "post_ignored")
    settings = get_settings()
    await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=None, mode=None)
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")
