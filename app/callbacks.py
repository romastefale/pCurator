import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.access import reject_callback_if_not_owner
from app.services.preview import send_post_preview
from app.services.publisher import publish_post
from app.services.regenerator import regenerate_post_for_channel
from app.settings import get_settings
from app.storage.articles import get_article
from app.storage.events import log_event
from app.storage.posts import get_post, save_post, update_post_status
from app.storage.session import get_active_context, get_active_post, set_active_post
from app.ui import channel_keyboard, review_keyboard

logger = logging.getLogger(__name__)
router = Router()


def _log_callback_received(callback: CallbackQuery) -> None:
    logger.info(
        "callback_received data=%s user=%s",
        callback.data,
        callback.from_user.id if callback.from_user else None,
    )


def _generation_warning(metadata: dict) -> str | None:
    if not metadata.get("ok"):
        return "⚠️ Não consegui gerar a prévia editorial. Verifique os logs do Railway."

    engine = metadata.get("engine")
    if engine == "mira":
        return None

    notes = ", ".join(metadata.get("quality_notes") or []) or "sem detalhes"
    if engine == "openai":
        return f"⚠️ Mira não respondeu. Foi usado fallback OpenAI.\nMotivo: {notes}"

    return f"⚠️ Mira e OpenAI não foram usadas com sucesso. Foi usado fallback local.\nMotivo: {notes}"


async def _log_choice(callback: CallbackQuery, channel_slug: str | None, event_type: str) -> None:
    settings = get_settings()
    post_id, active_channel, mode = await get_active_context(settings.database_path, callback.from_user.id)
    await log_event(
        settings.database_path,
        channel_slug=channel_slug or active_channel,
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


def _resolve_channel_id(channel_slug: str | None) -> int | None:
    settings = get_settings()
    if channel_slug == "c1":
        return settings.channel_1_id
    if channel_slug == "c2":
        return settings.channel_2_id
    return None


async def _prepare_channel_review(callback: CallbackQuery, channel_slug: str, label: str) -> None:
    _log_callback_received(callback)
    settings = get_settings()
    post_id = await _active_post_id(callback)
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=post_id,
        mode="review",
        channel_slug=channel_slug,
    )
    await _log_choice(callback, channel_slug, "channel_selected")
    await callback.answer(f"{label} selecionado")

    if not callback.message:
        return

    if post_id is None:
        await callback.message.answer("Nenhum rascunho ativo encontrado.")
        return

    await callback.message.answer(f"{label} selecionado. Gerando prévia editorial...")
    metadata = await regenerate_post_for_channel(
        settings.database_path,
        post_id=post_id,
        channel_slug=channel_slug,
        bot=callback.bot,
    )
    post = await get_post(settings.database_path, post_id)

    if metadata.get("ok") and post:
        await send_post_preview(callback.bot, callback.message.chat.id, post)

    warning = _generation_warning(metadata)
    if warning:
        await callback.message.answer(warning)

    await callback.message.answer(
        "Revise o rascunho antes de publicar.",
        reply_markup=review_keyboard(),
    )


@router.callback_query(F.data.regexp(r"^duplicate:regenerate:\d+$"))
async def duplicate_regenerate(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    settings = get_settings()
    parts = (callback.data or "").split(":")

    try:
        article_id = int(parts[2])
        article = await get_article(article_id, settings.database_path)
        if not article:
            await callback.answer("Item não encontrado", show_alert=True)
            return

        post_id = await save_post(
            settings.database_path,
            article_id=article_id,
            channel_slug="manual",
            caption_html="Novo rascunho interno criado a partir de item duplicado. Escolha C1 ou C2 para gerar o post editorial final.",
            image_url=article.get("image_url"),
        )
        await set_active_post(
            settings.database_path,
            user_id=callback.from_user.id,
            post_id=post_id,
            mode="review",
        )
        await _log_choice(callback, None, "duplicate_regenerated")
        await callback.answer("Novo rascunho criado")

        if callback.message:
            await callback.message.answer(
                "🔁 Novo rascunho criado a partir da matéria duplicada.\n\n"
                f"Item #{article_id}\n"
                f"Post #{post_id}\n"
                f"Título: {article.get('title') or 'Sem título'}\n\n"
                "Escolha o canal para gerar a legenda editorial final.",
                reply_markup=channel_keyboard(),
            )
    except Exception as exc:
        logger.exception("Duplicate regenerate callback failed: %s", type(exc).__name__)
        await callback.answer("Erro ao gerar rascunho", show_alert=True)
        if callback.message:
            await callback.message.answer(
                "⚠️ Erro ao gerar novo rascunho duplicado. Verifique os logs do Railway."
            )


@router.callback_query(F.data == "duplicate:ignore")
async def duplicate_ignore(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    await _log_choice(callback, None, "duplicate_ignored")
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Matéria duplicada ignorada.")


@router.callback_query(F.data == "channel:c1")
async def choose_c1(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    await _prepare_channel_review(callback, "c1", "📘 Canal 1")


@router.callback_query(F.data == "channel:c2")
async def choose_c2(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    await _prepare_channel_review(callback, "c2", "📰 Canal 2")


@router.callback_query(F.data == "channel:ignore")
async def ignore_channel(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    await _log_choice(callback, None, "channel_ignored")
    settings = get_settings()
    await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=None, mode=None)
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")


@router.callback_query(F.data == "post:publish")
async def review_publish(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    settings = get_settings()
    post_id, channel_slug, _ = await get_active_context(settings.database_path, callback.from_user.id)
    await _log_choice(callback, channel_slug, "publish_requested")
    await callback.answer("Publicação solicitada")

    if not callback.message:
        return

    if post_id is None:
        await callback.message.answer("Nenhum rascunho ativo encontrado.")
        return

    channel_id = _resolve_channel_id(channel_slug)
    if channel_id is None:
        await callback.message.answer("Canal de destino não configurado para este rascunho.")
        return

    post = await get_post(settings.database_path, post_id)
    if not post:
        await callback.message.answer("Post ativo não encontrado no banco.")
        return

    await publish_post(callback.bot, channel_id, post)
    await update_post_status(settings.database_path, post_id, "published")
    await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=None, mode=None)
    await _log_choice(callback, channel_slug, "published")
    await callback.message.answer(f"✅ Post #{post_id} publicado.")


@router.callback_query(F.data == "post:edit")
async def review_edit(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

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
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

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
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    await _log_choice(callback, None, "post_ignored")
    settings = get_settings()
    await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=None, mode=None)
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")
