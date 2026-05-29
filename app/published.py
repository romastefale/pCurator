"""Publicações já no ar: notificação pro dono + editar/apagar (owner-only).

Fluxo:
  - Toda publicação bem-sucedida (callbacks.review_confirm) chama
    notify_owner_published(): manda pro dono uma cópia fiel da publicação +
    uma mensagem com metadados (quem/quando/onde) e botões Apagar/Editar.
  - Apagar: deleteMessages no canal (todos os message_ids gravados) + status
    'deleted'. Confirmação em 2 passos (destrutivo, irreversível).
  - Editar: submenu Texto/Imagem.
      Texto  -> seta sessão mode='edit_published_text'; o texto digitado é
                aplicado por edit_flow via apply_published_text_edit().
      Imagem -> seta sessão mode='edit_published_image'; a(s) foto(s) são
                aplicadas por image_flow via apply_published_images_edit().

Limitação dura do Telegram (não contornável): não dá pra adicionar/remover
fotos de um álbum já enviado — só trocar as existentes e a legenda.
"""

import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputMediaPhoto, LinkPreviewOptions

from app.access import is_owner_id, reject_callback_if_not_owner
from app.services.preview import send_post_preview
from app.settings import Settings, get_settings
from app.storage.events import log_event
from app.storage.posts import (
    get_post,
    post_image_refs,
    published_message_ids,
    published_photo_ids,
    update_post_caption,
    update_post_images,
    update_post_status,
)
from app.storage.session import set_active_post
from app.ui import (
    published_actions_keyboard,
    published_delete_confirm_keyboard,
    published_edit_menu_keyboard,
)

router = Router()
logger = logging.getLogger(__name__)

PHOTO_CAPTION_LIMIT = 1024


def _format_when(settings: Settings) -> str:
    try:
        return datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y %H:%M")


async def notify_owner_published(
    bot,
    settings: Settings,
    *,
    post: dict,
    channel_title: str | None,
    by_id: int | None,
    by_name: str | None,
) -> None:
    """Manda pro dono a cópia da publicação + metadados + botões. Nunca quebra
    o fluxo de publicação: erros são logados, não propagados."""
    try:
        owner_id = settings.owner_id
        post_id = post["id"]

        # Cópia fiel (mesmo renderizador da publicação real).
        await send_post_preview(bot, owner_id, post)

        who = "Você" if by_id == owner_id else html.escape(by_name or str(by_id or "?"))
        safe_channel = html.escape(channel_title or "canal")
        text = (
            f"📣 <b>Publicação #{post_id}</b>\n"
            f"👤 {who}\n"
            f"🕐 {_format_when(settings)}\n"
            f"📢 {safe_channel}"
        )
        await bot.send_message(
            owner_id, text, reply_markup=published_actions_keyboard(post_id)
        )
    except Exception:
        logger.exception(
            "falha ao notificar dono sobre publicação %s", post.get("id")
        )


async def _delete_channel_messages(bot, chat_id: int, message_ids: list[int]) -> bool:
    """Apaga as mensagens no canal. Tenta em lote; cai pra uma a uma."""
    try:
        await bot.delete_messages(chat_id=chat_id, message_ids=message_ids)
        return True
    except TelegramBadRequest:
        ok = False
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
                ok = True
            except TelegramBadRequest:
                pass
        return ok


# ---------------------------------------------------------------------------
# Aplicadores chamados pelos fluxos de texto/foto (edit_flow / image_flow).
# ---------------------------------------------------------------------------


async def apply_published_text_edit(
    bot, user_id: int, post_id: int, new_html: str
) -> tuple[bool, str]:
    """Edita o texto/legenda de uma publicação no canal. Retorna (ok, mensagem)."""
    settings = get_settings()
    post = await get_post(settings.database_path, post_id)
    if not post or post.get("status") == "deleted":
        return False, "Publicação indisponível (pode ter sido apagada)."

    new_html = (new_html or "").strip()
    if not new_html:
        return False, "Texto vazio — nada foi alterado."

    chat_id = post.get("published_chat_id")
    text_mid = post.get("published_text_message_id")
    on_photo = bool(post.get("published_caption_on_photo"))
    if not chat_id or not text_mid:
        return False, "Sem mensagem registrada pra editar nesta publicação."

    if on_photo and len(new_html) > PHOTO_CAPTION_LIMIT:
        return False, (
            f"O novo texto tem {len(new_html)} caracteres e esta publicação tem a "
            f"legenda dentro da foto (limite {PHOTO_CAPTION_LIMIT}). "
            "Encurte o texto pra conseguir editar."
        )

    try:
        if on_photo:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=text_mid, caption=new_html
            )
        else:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=text_mid,
                text=new_html,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return False, "O texto é igual ao que já está no canal."
        logger.warning("edição de texto recusada post=%s: %s", post_id, exc)
        return False, f"O Telegram recusou a edição: {type(exc).__name__}."

    await update_post_caption(settings.database_path, post_id, new_html)
    await log_event(
        settings.database_path,
        event_type="published_caption_updated",
        payload={"post_id": post_id, "by": user_id},
    )
    return True, f"✅ Texto da publicação #{post_id} atualizado no canal."


async def apply_published_images_edit(
    bot, user_id: int, post_id: int, refs: list[str]
) -> tuple[bool, str]:
    """Troca a(s) foto(s) de uma publicação no canal, posição por posição.
    Não muda a quantidade (limitação do Telegram). Retorna (ok, mensagem)."""
    settings = get_settings()
    post = await get_post(settings.database_path, post_id)
    if not post or post.get("status") == "deleted":
        return False, "Publicação indisponível (pode ter sido apagada)."

    chat_id = post.get("published_chat_id")
    photo_mids = published_photo_ids(post)
    if not chat_id or not photo_mids:
        return False, "Esta publicação não tem foto registrada pra trocar."

    refs = [r for r in refs if r]
    if not refs:
        return False, "Nenhuma foto recebida."

    old_refs = post_image_refs(post)
    text_mid = post.get("published_text_message_id")
    on_photo = bool(post.get("published_caption_on_photo"))
    caption = post.get("caption_html") or ""

    k = min(len(refs), len(photo_mids))
    extra = len(refs) > len(photo_mids)
    # Parte do estado atual e só sobrescreve as posições que de fato trocarem —
    # se uma edição falhar no meio, o DB não pode divergir do que está no canal.
    new_image_refs = list(old_refs)
    edited = 0
    for i in range(k):
        mid = photo_mids[i]
        keep_caption = on_photo and mid == text_mid
        media = InputMediaPhoto(
            media=refs[i], caption=caption if keep_caption else None
        )
        try:
            await bot.edit_message_media(chat_id=chat_id, message_id=mid, media=media)
            if i < len(new_image_refs):
                new_image_refs[i] = refs[i]
            else:
                new_image_refs.append(refs[i])
            edited += 1
        except TelegramBadRequest as exc:
            logger.warning(
                "edit_message_media falhou pos=%s post=%s: %s", i, post_id, exc
            )

    if edited == 0:
        return False, "Não consegui trocar nenhuma foto (o Telegram recusou)."

    await update_post_images(settings.database_path, post_id, new_image_refs)
    await log_event(
        settings.database_path,
        event_type="published_image_updated",
        payload={"post_id": post_id, "by": user_id, "count": edited},
    )

    msg = f"✅ {edited} foto(s) trocada(s) na publicação #{post_id}."
    if extra:
        msg += (
            f"\n⚠️ Ignorei as fotos extras — o álbum tem {len(photo_mids)} e não dá "
            "pra mudar a quantidade depois de publicado."
        )
    return True, msg


# ---------------------------------------------------------------------------
# Callbacks owner-only dos botões da notificação.
# ---------------------------------------------------------------------------


def _post_id_from(callback: CallbackQuery) -> int | None:
    try:
        return int((callback.data or "").split(":")[-1])
    except (ValueError, IndexError):
        return None


@router.callback_query(F.data.regexp(r"^pub:del:\d+$"))
async def pub_delete_prompt(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=published_delete_confirm_keyboard(post_id)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^pub:delno:\d+$"))
async def pub_delete_cancel(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=published_actions_keyboard(post_id)
    )
    await callback.answer("Cancelado")


@router.callback_query(F.data.regexp(r"^pub:delok:\d+$"))
async def pub_delete_confirm(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    settings = get_settings()
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return

    post = await get_post(settings.database_path, post_id)
    if not post:
        await callback.answer("Post não encontrado.", show_alert=True)
        return

    chat_id = post.get("published_chat_id")
    mids = published_message_ids(post)
    if not chat_id or not mids:
        await callback.answer("Sem mensagens registradas pra apagar.", show_alert=True)
        return

    ok = await _delete_channel_messages(callback.bot, chat_id, mids)
    await update_post_status(settings.database_path, post_id, "deleted")
    await log_event(
        settings.database_path,
        event_type="published_deleted",
        payload={"post_id": post_id, "by": callback.from_user.id},
    )
    if ok:
        await callback.message.edit_text(f"🗑 Publicação #{post_id} apagada do canal.")
        await callback.answer("Apagado")
    else:
        await callback.message.edit_text(
            f"⚠️ Não consegui apagar a publicação #{post_id} do canal "
            "(o bot ainda é admin com permissão de excluir?). "
            "Marquei como apagada aqui mesmo assim."
        )
        await callback.answer("Falha ao apagar no canal", show_alert=True)


@router.callback_query(F.data.regexp(r"^pub:edit:\d+$"))
async def pub_edit_menu(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    settings = get_settings()
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return
    post = await get_post(settings.database_path, post_id)
    if not post or post.get("status") == "deleted":
        await callback.answer("Publicação indisponível.", show_alert=True)
        return
    has_images = bool(post_image_refs(post))
    await callback.message.edit_reply_markup(
        reply_markup=published_edit_menu_keyboard(post_id, has_images)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^pubedit:back:\d+$"))
async def pub_edit_back(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return
    await callback.message.edit_reply_markup(
        reply_markup=published_actions_keyboard(post_id)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^pubedit:text:\d+$"))
async def pub_edit_text_start(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    settings = get_settings()
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return
    post = await get_post(settings.database_path, post_id)
    if not post or post.get("status") == "deleted":
        await callback.answer("Publicação indisponível.", show_alert=True)
        return
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=post_id,
        mode="edit_published_text",
    )
    await callback.message.answer(
        f"✏️ Envie o novo texto da publicação #{post_id}.\n"
        "Ele substitui o que está no canal."
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^pubedit:img:\d+$"))
async def pub_edit_image_start(callback: CallbackQuery) -> None:
    if await reject_callback_if_not_owner(callback):
        return
    settings = get_settings()
    post_id = _post_id_from(callback)
    if post_id is None or not callback.message:
        await callback.answer("Botão inválido", show_alert=True)
        return
    post = await get_post(settings.database_path, post_id)
    if not post or post.get("status") == "deleted":
        await callback.answer("Publicação indisponível.", show_alert=True)
        return
    n = len(published_photo_ids(post)) or len(post_image_refs(post))
    if n == 0:
        await callback.answer("Esta publicação não tem imagem.", show_alert=True)
        return
    await set_active_post(
        settings.database_path,
        user_id=callback.from_user.id,
        post_id=post_id,
        mode="edit_published_image",
    )
    if n == 1:
        prompt = f"🖼 Envie a nova foto da publicação #{post_id}."
    else:
        prompt = (
            f"🖼 Envie até {n} fotos (na ordem). Cada uma troca a foto da mesma "
            f"posição no álbum.\n⚠️ Não dá pra mudar a quantidade ({n}) depois de publicado."
        )
    await callback.message.answer(prompt)
    await callback.answer()
