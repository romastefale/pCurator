import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.access import reject_callback_if_not_owner
from app.services.manual_discovery import (
    clear_search,
    fetch_next_for_search,
    get_search,
    reset_search,
)
from app.services.news_discovery import TOPIC_LABELS
from app.services.preview import send_post_preview
from app.services.publisher import publish_post
from app.services.regenerator import UNIFIED_TONE
from app.services.review_delivery import generate_and_deliver_review
from app.settings import Settings, get_settings
from app.storage.articles import get_article
from app.storage.discovery_stats import get_today_count
from app.storage.events import log_event
from app.storage.posts import (
    get_post,
    save_post,
    try_lock_post_for_publish,
    update_post_status,
)
from app.storage.session import (
    get_active_context,
    get_active_post,
    pop_last_preview_message_ids,
    set_active_post,
    set_last_preview_message_ids,
    try_claim_idle_session,
)
from app.ui import (
    channel_label,
    confirm_keyboard,
    destination_keyboard,
    review_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


async def _delete_tracked_previews(bot: Bot, chat_id: int, user_id: int) -> None:
    settings = get_settings()
    ids = await pop_last_preview_message_ids(settings.database_path, user_id)
    if not ids:
        return
    # Bot API 7.0+ permite deletar até 100 mensagens numa única chamada.
    try:
        await bot.delete_messages(chat_id=chat_id, message_ids=ids)
        return
    except TelegramBadRequest:
        # Fallback: alguma msg fora da janela de 48h ou já apagada — tenta uma a uma.
        for message_id in ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except TelegramBadRequest:
                pass


async def _delete_callback_message(callback: CallbackQuery) -> None:
    """Apaga a mensagem que continha o botão clicado (prompt agora obsoleto).

    Telegram só permite apagar mensagens enviadas pelo próprio bot e há
    janela de 48h; ignoramos falhas silenciosamente."""
    if not callback.message:
        return
    try:
        await callback.bot.delete_message(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
    except TelegramBadRequest:
        pass


def _log_callback_received(callback: CallbackQuery) -> None:
    logger.info(
        "callback_received data=%s user=%s",
        callback.data,
        callback.from_user.id if callback.from_user else None,
    )


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


@router.callback_query(F.data.regexp(r"^duplicate:regenerate:\d+$"))
async def duplicate_regenerate(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    await _delete_callback_message(callback)
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
            caption_html="Novo rascunho interno criado a partir de item duplicado — gerando legenda editorial...",
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
            status_msg = await callback.message.answer(
                "🔁 Novo rascunho criado a partir da matéria duplicada.\n\n"
                f"Item #{article_id}\n"
                f"Post #{post_id}\n"
                f"Título: {article.get('title') or 'Sem título'}\n\n"
                "🎨 Gerando a prévia editorial..."
            )
            await generate_and_deliver_review(
                callback.bot,
                settings.database_path,
                chat_id=callback.message.chat.id,
                user_id=callback.from_user.id,
                post_id=post_id,
                status_message_id=status_msg.message_id,
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

    await _delete_callback_message(callback)
    await _log_choice(callback, None, "duplicate_ignored")
    await callback.answer("Ignorado")
    if callback.message:
        await callback.message.answer("🚫 Matéria duplicada ignorada.")


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

    # Apaga toda a fase de revisão (prévia + warning + instrução c/ botão clicado).
    await _delete_tracked_previews(callback.bot, callback.message.chat.id, callback.from_user.id)

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

    await callback.message.answer(
        "📤 Texto pronto.\n"
        "Para qual canal você quer publicar?",
        reply_markup=destination_keyboard(),
    )


async def _prepare_destination_confirm(callback: CallbackQuery, destination_slug: str) -> None:
    settings = get_settings()
    post_id, _, _ = await get_active_context(settings.database_path, callback.from_user.id)
    await _log_choice(callback, destination_slug, "destination_selected")
    await callback.answer(f"{channel_label(destination_slug)} selecionado")

    if not callback.message:
        return

    # Apaga o prompt "Para qual canal você quer publicar?" agora obsoleto.
    await _delete_callback_message(callback)

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

    tracked: list[int] = []
    header = await callback.message.answer(
        f"🔎 Pré-visualização final para {dest_label} — post #{post_id}.\n"
        "Esta é exatamente a forma como será enviada:"
    )
    tracked.append(header.message_id)
    tracked.extend(await send_post_preview(callback.bot, callback.message.chat.id, post))
    confirm_msg = await callback.message.answer(
        f"Confirma o envio para {dest_label}?",
        reply_markup=confirm_keyboard(post_id, destination_slug),
    )
    tracked.append(confirm_msg.message_id)
    await set_last_preview_message_ids(settings.database_path, callback.from_user.id, tracked)


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

    await _delete_callback_message(callback)
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

    # Sempre apaga o prompt clicado (mesmo se obsoleto) — é o comportamento
    # esperado pelo usuário: clicou no botão, a mensagem some.
    await _delete_callback_message(callback)

    # Valida que o botão clicado bate com o estado atual da sessão. Isso impede
    # publicar no destino errado se o usuário clicou num botão obsoleto.
    if session_post_id != button_post_id or session_channel != button_destination or mode != "confirm":
        await callback.message.answer(
            "⚠️ Esta confirmação não bate com o rascunho ativo (botão obsoleto).\n"
            "Reabra o rascunho e escolha o destino de novo."
        )
        return

    # Limpa também a prévia final + header tracked (sessão válida, então tracked
    # corresponde de fato a este fluxo).
    await _delete_tracked_previews(callback.bot, callback.message.chat.id, callback.from_user.id)

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

    await _delete_callback_message(callback)

    settings = get_settings()
    post_id, channel_slug, mode = await get_active_context(settings.database_path, callback.from_user.id)
    # Só limpa tracked se a sessão ainda está na fase de confirmação que esse
    # botão representa — caso contrário pode estar apagando msgs de outro fluxo.
    if callback.message and mode == "confirm":
        await _delete_tracked_previews(
            callback.bot, callback.message.chat.id, callback.from_user.id
        )
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
        await _delete_tracked_previews(
            callback.bot, callback.message.chat.id, callback.from_user.id
        )
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
        await _delete_tracked_previews(
            callback.bot, callback.message.chat.id, callback.from_user.id
        )
        await set_active_post(settings.database_path, user_id=callback.from_user.id, post_id=post_id, mode="edit_image")
        await callback.message.answer(f"🖼 Envie a nova imagem para o post #{post_id}.")


async def _deliver_next_manual_draft(
    bot: Bot,
    settings: Settings,
    user_id: int,
    chat_id: int,
    topic: str,
) -> bool:
    """Busca próxima notícia da trilha, cria rascunho (tom único), reserva
    sessão e envia prévia com botão ⏭ Próxima. Devolve True se entregou."""
    result = await fetch_next_for_search(bot, settings, user_id)
    if not result:
        return False

    post_id, source_name = result

    claimed = await try_claim_idle_session(
        settings.database_path,
        user_id=user_id,
        post_id=post_id,
        mode="review",
        channel_slug=UNIFIED_TONE,
    )
    if not claimed:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ Rascunho criado mas você tem outro post ativo.\n"
                "Finalize o atual e use /buscar novamente."
            ),
        )
        return True

    try:
        post = await get_post(settings.database_path, post_id)
        if not post:
            raise RuntimeError(f"post {post_id} disappeared after claim")

        topic_label = TOPIC_LABELS.get(topic, topic)
        header = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🔍 Busca manual — {topic_label}\n"
                f"Rascunho #{post_id} · {source_name}"
            ),
        )
        tracked: list[int] = [header.message_id]
        tracked.extend(await send_post_preview(bot, chat_id, post))
        instr = await bot.send_message(
            chat_id=chat_id,
            text=(
                "Acima a prévia.\n"
                "Publique, edite, troque a imagem, ignore ou peça a próxima."
            ),
            reply_markup=review_keyboard(with_next=True),
        )
        tracked.append(instr.message_id)
        await set_last_preview_message_ids(settings.database_path, user_id, tracked)
        return True
    except Exception as exc:
        logger.exception(
            "manual_draft_notify_failed post=%s rolling back: %s",
            post_id, type(exc).__name__,
        )
        try:
            await set_active_post(
                settings.database_path, user_id=user_id, post_id=None,
                mode=None, clear_channel=True,
            )
        except Exception:
            logger.exception("manual_draft_session_rollback_failed post=%s", post_id)
        return False


@router.callback_query(F.data.startswith("discover:"))
async def discover_topic_picked(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    topic = callback.data.split(":", 1)[1]
    await _delete_callback_message(callback)

    if topic == "cancel":
        clear_search(callback.from_user.id)
        await callback.answer("Cancelado")
        if callback.message:
            await callback.message.answer("🚫 Busca cancelada.")
        return

    if topic not in TOPIC_LABELS:
        await callback.answer("Trilha inválida", show_alert=True)
        return

    settings = get_settings()
    if not settings.gnews_key:
        await callback.answer("GNEWS_KEY não configurada", show_alert=True)
        return

    count = await get_today_count(settings.database_path, settings.timezone)
    if count >= settings.discovery_daily_cap:
        await callback.answer("Limite diário atingido", show_alert=True)
        if callback.message:
            await callback.message.answer(
                f"⚠️ Limite diário atingido ({count}/{settings.discovery_daily_cap}). "
                "Reset à meia-noite local."
            )
        return

    await callback.answer("Buscando...")
    reset_search(callback.from_user.id, topic)
    if callback.message:
        ok = await _deliver_next_manual_draft(
            callback.bot, settings, callback.from_user.id,
            callback.message.chat.id, topic,
        )
        if not ok:
            await callback.message.answer(
                f"Nenhuma notícia nova em <b>{TOPIC_LABELS[topic]}</b> agora. "
                "Tente outra trilha com /buscar."
            )


@router.callback_query(F.data == "post:next")
async def review_next(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    settings = get_settings()
    user_id = callback.from_user.id

    # VALIDA pré-condições ANTES de mexer no rascunho atual — se o estado de
    # busca foi perdido (restart) ou o cap estourou, o rascunho fica intacto
    # e o owner pode tratá-lo via Publicar/Ignorar/Editar normalmente.
    state = get_search(user_id)
    if not state:
        await callback.answer("Contexto perdido", show_alert=True)
        if callback.message:
            await callback.message.answer(
                "⚠️ Contexto de busca perdido (bot reiniciou?). "
                "Use /buscar para começar de novo. "
                "O rascunho atual continua disponível pra publicar ou ignorar."
            )
        return

    count = await get_today_count(settings.database_path, settings.timezone)
    if count >= settings.discovery_daily_cap:
        await callback.answer("Limite diário atingido", show_alert=True)
        if callback.message:
            await callback.message.answer(
                f"⚠️ Limite diário atingido ({count}/{settings.discovery_daily_cap}). "
                "O rascunho atual continua disponível pra publicar ou ignorar."
            )
        return

    # Pré-condições OK — agora pode descartar o atual e liberar sessão
    active_id, _, _ = await get_active_context(settings.database_path, user_id)
    if active_id:
        post = await get_post(settings.database_path, active_id)
        if post and post.get("status") == "draft":
            await update_post_status(settings.database_path, active_id, "ignored")

    await _delete_callback_message(callback)
    if callback.message:
        await _delete_tracked_previews(
            callback.bot, callback.message.chat.id, user_id
        )
    await _log_choice(callback, None, "post_next_requested")

    await set_active_post(
        settings.database_path, user_id=user_id, post_id=None,
        mode=None, clear_channel=True,
    )

    await callback.answer("Buscando próxima...")
    if callback.message:
        ok = await _deliver_next_manual_draft(
            callback.bot, settings, user_id,
            callback.message.chat.id, state.topic,
        )
        if not ok:
            await callback.message.answer(
                f"Sem mais notícias novas em <b>{TOPIC_LABELS.get(state.topic, state.topic)}</b>. "
                "Tente outra trilha com /buscar."
            )


@router.callback_query(F.data == "post:ignore")
async def review_ignore(callback: CallbackQuery) -> None:
    _log_callback_received(callback)
    if await reject_callback_if_not_owner(callback):
        return

    await _delete_callback_message(callback)
    settings = get_settings()
    _, _, mode = await get_active_context(settings.database_path, callback.from_user.id)
    if callback.message and mode in ("review", "confirm"):
        await _delete_tracked_previews(
            callback.bot, callback.message.chat.id, callback.from_user.id
        )
    await _log_choice(callback, None, "post_ignored")
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
