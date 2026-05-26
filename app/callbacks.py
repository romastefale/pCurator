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
from app.storage.posts import (
    get_post,
    save_post,
    try_lock_post_for_publish,
    update_post_channel_slug,
    update_post_status,
)
from app.storage.session import get_active_context, get_active_post, set_active_post
from app.ui import (
    channel_keyboard,
    channel_label,
    confirm_keyboard,
    destination_keyboard,
    review_keyboard,
)

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

    await callback.message.answer(
        f"🎨 Gerando prévia com o tom de {label} (a escolha do canal de destino vem depois)..."
    )
    # Persiste o tom no próprio post pra /pfr e auditoria reabrirem com o tom original.
    await update_post_channel_slug(settings.database_path, post_id, channel_slug)
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

    can_publish = bool(metadata.get("ok")) and bool(metadata.get("publishable", True))
    instruction = (
        f"Acima está a prévia exata (tom de {label}).\n"
        "Você pode editar o texto, trocar a imagem ou avançar para escolher o canal de publicação."
        if can_publish
        else f"⚠️ Rascunho marcado como não publicável automaticamente (tom de {label}).\n"
        "Edite o texto ou troque a imagem antes de avançar."
    )
    await callback.message.answer(instruction, reply_markup=review_keyboard(can_publish=can_publish))


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
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=None,
        mode=None,
        clear_channel=True,
    )
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")


@router.callback_query(F.data == "post:publish")
async def review_publish(callback: CallbackQuery) -> None:
    """Após revisão, pergunta o canal de DESTINO (pode ser diferente do tom)."""
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    settings = get_settings()
    post_id, channel_slug, _ = await get_active_context(settings.database_path, callback.from_user.id)
    await _log_choice(callback, channel_slug, "destination_requested")
    await callback.answer("Escolha o canal de destino")

    if not callback.message:
        return

    if post_id is None:
        await callback.message.answer("Nenhum rascunho ativo encontrado.")
        return

    post = await get_post(settings.database_path, post_id)
    if not post:
        await callback.message.answer("Post ativo não encontrado no banco.")
        return

    if post.get("status") in ("published", "publishing", "failed"):
        await callback.message.answer(
            f"⚠️ Post #{post_id} está com status '{post.get('status')}'. Envio bloqueado por segurança."
        )
        return

    tone_label = channel_label(channel_slug)
    await callback.message.answer(
        f"📤 Texto pronto (tom de {tone_label}).\n"
        "Para qual canal você quer publicar?",
        reply_markup=destination_keyboard(),
    )


async def _prepare_destination_confirm(callback: CallbackQuery, destination_slug: str) -> None:
    settings = get_settings()
    post_id, tone_slug, _ = await get_active_context(settings.database_path, callback.from_user.id)
    await _log_choice(callback, destination_slug, "destination_selected")
    await callback.answer(f"{channel_label(destination_slug)} selecionado")

    if not callback.message:
        return

    if post_id is None:
        await callback.message.answer("Nenhum rascunho ativo encontrado.")
        return

    destination_id = _resolve_channel_id(destination_slug)
    if destination_id is None:
        await callback.message.answer(
            f"⚠️ {channel_label(destination_slug)} não está configurado nas variáveis de ambiente."
        )
        return

    post = await get_post(settings.database_path, post_id)
    if not post:
        await callback.message.answer("Post ativo não encontrado no banco.")
        return

    if post.get("status") in ("published", "publishing", "failed"):
        await callback.message.answer(
            f"⚠️ Post #{post_id} está com status '{post.get('status')}'. Envio bloqueado por segurança."
        )
        return

    # Sessão passa a guardar o canal de DESTINO (sobrescreve o tom).
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=post_id,
        mode="confirm",
        channel_slug=destination_slug,
    )

    dest_label = channel_label(destination_slug)
    tone_note = ""
    if tone_slug and tone_slug != destination_slug:
        tone_note = f" (gerado com tom de {channel_label(tone_slug)})"

    await callback.message.answer(
        f"🔎 Pré-visualização final para {dest_label}{tone_note} — post #{post_id}.\n"
        "Esta é exatamente a forma como será enviada:"
    )
    await send_post_preview(callback.bot, callback.message.chat.id, post)
    await callback.message.answer(
        f"Confirma o envio para {dest_label}?",
        reply_markup=confirm_keyboard(post_id, destination_slug),
    )


@router.callback_query(F.data == "dest:c1")
async def destination_c1(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return
    await _prepare_destination_confirm(callback, "c1")


@router.callback_query(F.data == "dest:c2")
async def destination_c2(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return
    await _prepare_destination_confirm(callback, "c2")


@router.callback_query(F.data == "dest:back")
async def destination_back(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    settings = get_settings()
    post_id, channel_slug, _ = await get_active_context(settings.database_path, callback.from_user.id)
    await _log_choice(callback, channel_slug, "destination_back")
    await callback.answer("Voltando para revisão")

    if post_id is not None:
        # Restaura sessão para review (tom permanece em channel_slug).
        post = await get_post(settings.database_path, post_id)
        tone_slug = (post or {}).get("channel_slug") if post else channel_slug
        await set_active_post(
            settings.database_path,
            user_id=callback.from_user.id,
            post_id=post_id,
            mode="review",
            channel_slug=tone_slug,
        )

    if callback.message:
        await callback.message.answer(
            "↩️ Voltando para revisão. Use os botões abaixo para ajustar ou avançar de novo:",
            reply_markup=review_keyboard(),
        )


@router.callback_query(F.data.regexp(r"^post:confirm:\d+:(c1|c2)$"))
async def review_confirm(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    parts = (callback.data or "").split(":")
    try:
        button_post_id = int(parts[2])
        button_destination = parts[3]
    except (IndexError, ValueError):
        await callback.answer("Botão inválido", show_alert=True)
        return

    settings = get_settings()
    session_post_id, session_channel, mode = await get_active_context(
        settings.database_path, callback.from_user.id
    )
    await callback.answer("Enviando...")

    if not callback.message:
        return

    # Valida que o botão clicado bate com o estado atual da sessão. Isso impede
    # publicar no destino errado se o usuário clicou num botão obsoleto.
    if session_post_id != button_post_id or session_channel != button_destination or mode != "confirm":
        await callback.message.answer(
            "⚠️ Esta confirmação não bate com o rascunho ativo (botão obsoleto).\n"
            "Reabra o rascunho e escolha o destino de novo."
        )
        return

    channel_slug = button_destination
    post_id = button_post_id

    channel_id = _resolve_channel_id(channel_slug)
    if channel_id is None:
        await callback.message.answer("Canal de destino não configurado para este rascunho.")
        return

    post = await get_post(settings.database_path, post_id)
    if not post:
        await callback.message.answer("Post ativo não encontrado no banco.")
        return

    current_status = post.get("status")
    if current_status in ("published", "publishing", "failed"):
        await callback.message.answer(
            f"⚠️ Post #{post_id} está com status '{current_status}'. Envio bloqueado por segurança."
        )
        await set_active_post(
            settings.database_path,
            user_id=callback.from_user.id,
            post_id=None,
            mode=None,
            clear_channel=True,
        )
        return

    # Trava atômica draft -> publishing. Se já foi tomada, recusa.
    locked = await try_lock_post_for_publish(settings.database_path, post_id)
    if not locked:
        await callback.message.answer(
            f"⚠️ Post #{post_id} já está em envio ou foi publicado. Verifique o canal antes de tentar de novo."
        )
        await set_active_post(
            settings.database_path,
            user_id=callback.from_user.id,
            post_id=None,
            mode=None,
            clear_channel=True,
        )
        return

    try:
        await publish_post(callback.bot, channel_id, post)
    except Exception as exc:
        logger.exception("Publish failed for post %s: %s", post_id, type(exc).__name__)
        # Deixa como 'failed' (não volta pra draft) — o envio pode ter saído parcial
        # e marcar como draft permitiria re-publicação acidental.
        await update_post_status(settings.database_path, post_id, "failed")
        await set_active_post(
            settings.database_path,
            user_id=callback.from_user.id,
            post_id=None,
            mode=None,
            clear_channel=True,
        )
        await _log_choice(callback, channel_slug, "publish_failed")
        await callback.message.answer(
            f"❌ Falha ao publicar post #{post_id} em {channel_label(channel_slug)}: {type(exc).__name__}.\n"
            "⚠️ Verifique o canal antes de tentar de novo — parte do conteúdo pode ter sido enviada.\n"
            f"O post ficou marcado como 'failed'. Use <code>/pfr {post_id}</code> para reabrir após verificar."
        )
        return

    await update_post_status(settings.database_path, post_id, "published")
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=None,
        mode=None,
        clear_channel=True,
    )
    await _log_choice(callback, channel_slug, "published")
    await callback.message.answer(
        f"✅ Post #{post_id} publicado em {channel_label(channel_slug)}.\n"
        "Envie o próximo link quando quiser."
    )


@router.callback_query(F.data == "post:cancel_confirm")
async def review_cancel_confirm(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    settings = get_settings()
    post_id, channel_slug, _ = await get_active_context(settings.database_path, callback.from_user.id)
    await _log_choice(callback, channel_slug, "confirm_cancelled")
    await callback.answer("Confirmação cancelada")

    if post_id is not None:
        await set_active_post(
            settings.database_path,
            user_id=callback.from_user.id,
            post_id=post_id,
            mode="review",
            channel_slug=channel_slug,
        )

    if callback.message:
        await callback.message.answer(
            f"Envio para {channel_label(channel_slug)} cancelado. O rascunho continua disponível.",
            reply_markup=review_keyboard(),
        )


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
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=None,
        mode=None,
        clear_channel=True,
    )
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Rascunho ignorado.")
