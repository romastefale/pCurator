import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message

from app.access import reject_message_if_not_allowed
from app.services.preview import send_post_preview
from app.settings import get_settings
from app.storage.events import log_event
from app.storage.posts import get_post, update_post_images
from app.storage.session import get_active_post, set_active_post, set_last_preview_message_ids
from app.ui import review_keyboard

router = Router()
logger = logging.getLogger(__name__)

MAX_ALBUM = 4
# O Telegram entrega álbum como mensagens separadas (mesmo media_group_id), uma
# de cada vez. Esperamos um instante por mais fotos do mesmo grupo antes de aplicar.
ALBUM_DEBOUNCE_SECONDS = 1.2

# Buffer in-memory de álbuns em montagem, por (user_id, media_group_id).
# Perdido em restart — aceitável, é estado efêmero de UI.
_album_buffers: dict[tuple[int, str], dict] = {}


async def _apply_images(
    *,
    bot,
    chat_id: int,
    user_id: int,
    post_id: int,
    refs: list[str],
    truncated: bool,
) -> None:
    """Salva as fotos no post, volta pra review e mostra a prévia final."""
    settings = get_settings()
    post = await get_post(settings.database_path, post_id)
    if not post:
        logger.warning("post #%s não encontrado ao aplicar imagens", post_id)
        await bot.send_message(
            chat_id,
            f"⚠️ Post #{post_id} não encontrado — as imagens não foram salvas.",
        )
        return

    await update_post_images(settings.database_path, post_id, refs)
    await log_event(
        settings.database_path,
        event_type="image_updated",
        payload={"user_id": user_id, "post_id": post_id, "count": len(refs)},
    )
    await set_active_post(
        settings.database_path,
        user_id=user_id,
        post_id=post_id,
        mode="review",
    )

    count = len(refs)
    if count == 1:
        head = f"🖼 Imagem do post #{post_id} atualizada. Veja como vai ficar:"
    else:
        head = f"🖼 {count} imagens definidas pro post #{post_id} (álbum). Veja como vai ficar:"
    if truncated:
        head += f"\n⚠️ Usei só as primeiras {MAX_ALBUM} fotos (máximo do álbum)."

    header = await bot.send_message(chat_id, head)
    tracked: list[int] = [header.message_id]
    post = await get_post(settings.database_path, post_id)
    if post:
        tracked.extend(await send_post_preview(bot, chat_id, post))
    footer = await bot.send_message(
        chat_id,
        "Confirme a publicação ou edite novamente.",
        reply_markup=review_keyboard(),
    )
    tracked.append(footer.message_id)
    await set_last_preview_message_ids(settings.database_path, user_id, tracked)


async def _flush_album(key: tuple[int, str]) -> None:
    """Aplica o álbum acumulado após a janela de debounce."""
    try:
        await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return  # chegou outra foto do mesmo grupo; o flush foi reagendado.

    buf = _album_buffers.pop(key, None)
    if not buf or not buf["refs"]:
        return

    # Revalida o contexto: durante o debounce o usuário pode ter trocado de
    # rascunho/modo. Sem isso, o flush tardio gravaria no post errado e/ou
    # sobrescreveria a sessão atual.
    settings = get_settings()
    active_post_id, active_mode = await get_active_post(settings.database_path, buf["user_id"])
    if active_mode != "edit_image" or active_post_id != buf["post_id"]:
        logger.info(
            "álbum descartado: contexto mudou (esperado post=%s edit_image, atual post=%s mode=%s)",
            buf["post_id"], active_post_id, active_mode,
        )
        return

    try:
        await _apply_images(
            bot=buf["bot"],
            chat_id=buf["chat_id"],
            user_id=buf["user_id"],
            post_id=buf["post_id"],
            refs=buf["refs"],
            truncated=buf["truncated"],
        )
    except Exception:
        logger.exception("falha ao aplicar álbum de imagens post=%s", buf.get("post_id"))


@router.message(F.photo)
async def handle_manual_image(message: Message) -> None:
    settings = get_settings()
    post_id, mode = await get_active_post(settings.database_path, message.from_user.id)

    if mode != "edit_image" or post_id is None:
        return

    if await reject_message_if_not_allowed(message):
        return

    image_ref = message.photo[-1].file_id
    group_id = message.media_group_id

    # Foto única (sem álbum): aplica na hora.
    if not group_id:
        await _apply_images(
            bot=message.bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            post_id=post_id,
            refs=[image_ref],
            truncated=False,
        )
        return

    # Álbum: acumula no buffer e (re)agenda o flush (debounce por nova foto).
    key = (message.from_user.id, group_id)
    buf = _album_buffers.get(key)
    if buf is None:
        buf = {
            "bot": message.bot,
            "chat_id": message.chat.id,
            "user_id": message.from_user.id,
            "post_id": post_id,
            "refs": [],
            "truncated": False,
            "task": None,
        }
        _album_buffers[key] = buf

    if len(buf["refs"]) < MAX_ALBUM:
        buf["refs"].append(image_ref)
    else:
        buf["truncated"] = True

    if buf["task"]:
        buf["task"].cancel()
    buf["task"] = asyncio.create_task(_flush_album(key))
