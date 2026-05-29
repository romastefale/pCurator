import html

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message

from datetime import datetime
from zoneinfo import ZoneInfo

from app.access import reject_message_if_not_allowed, reject_message_if_not_owner
from app.storage.authorized_users import add_authorized_user, list_authorized_users
from app.storage.channels import list_channels
from app.services.discovery_scheduler import (
    GNEWS_DAILY_BUDGET,
    auto_cycles_remaining_today,
    safe_manual_searches,
)
from app.services.manual_discovery import clear_search
from app.services.news_discovery import ROTATION_BY_HOUR
from app.services.preview import send_post_preview
from app.settings import get_settings
from app.storage.discovery_stats import get_calls_today
from app.storage.posts import (
    count_posts_by_status,
    get_post,
    last_published_at,
    list_recent_posts,
    reopen_failed_post,
    update_post_status,
)
from app.storage.rules import add_rule, list_rules
from app.storage.session import (
    get_active_context,
    pop_last_preview_message_ids,
    set_active_post,
)
from app.storage.sources import (
    list_sources,
    set_source_blocked,
    update_source_score,
    upsert_source,
)
from app.ui import discover_topic_keyboard, review_keyboard, team_keyboard

router = Router()


@router.message(Command("start"))
async def start_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    await message.answer(
        "<b>pCurator ativo.</b>\n\n"
        "Envie um link de notícia para iniciar uma curadoria manual.\n"
        "Use /ph para ver os comandos disponíveis."
    )


@router.message(Command("ph"))
async def help_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    await message.answer(
        "<b>Comandos pCurator</b>\n\n"
        "<b>Fluxo de publicação</b>\n"
        "1. Envie o link da matéria.\n"
        "2. Receba a prévia exata (gerada automaticamente) e revise: ✏️ Editar texto, 🖼 Trocar imagem ou 🚫 Ignorar.\n"
        "3. Clique em ✅ Publicar e escolha o <b>canal de destino</b> (os canais onde o bot é admin aparecem pelo nome real).\n"
        "4. Confirme o envio na prévia final.\n\n"
        "<b>Comandos gerais</b>\n"
        "/start — estado inicial\n"
        "/ph — ajuda rápida\n"
        "/ps — status técnico\n"
        "/pq — fila editorial\n"
        "/pfr ID — reabrir post 'failed' como rascunho\n"
        "/buscar — pedir uma notícia agora (escolhe a trilha, gera a prévia, botão ⏭ Próxima para descartar e pedir outra)\n\n"
        "<b>Canais</b>\n"
        "/pc — listar canais detectados (o bot aparece aqui ao virar admin de um canal)\n\n"
        "<b>Equipe (só o dono)</b>\n"
        "/pe — listar co-autores e revogar acesso\n"
        "/pea ID Nome — autorizar um co-autor pelo ID do Telegram\n\n"
        "<b>Fontes</b>\n"
        "/pf — listar fontes\n"
        "/pfa Nome | url | escopo | nota — cadastrar fonte\n"
        "/pfs ID nota — alterar nota da fonte\n"
        "/pfb ID — bloquear fonte\n"
        "/pfu ID — desbloquear fonte\n\n"
        "<b>Regras</b>\n"
        "/pr — listar regras aprendidas\n"
        "/pra canal | tipo | regra — cadastrar regra"
    )


@router.message(Command("ps"))
async def status_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    settings = get_settings()
    counts = await count_posts_by_status(settings.database_path)
    last_pub = await last_published_at(settings.database_path)

    channels = await list_channels(settings.database_path)
    if channels:
        channels_line = "\n".join(f"• {html.escape(c['title'])}" for c in channels)
    else:
        channels_line = "nenhum detectado (adicione o bot como admin em um canal)"
    openai_state = "configurado" if settings.openai_key else "não configurado"
    mira_state = "configurado" if settings.mira_group_id else "não configurado"
    linkprev_state = "configurado" if settings.linkpreview_key else "não configurado"

    counts_line = (
        f"draft: {counts.get('draft', 0)} · "
        f"publishing: {counts.get('publishing', 0)} · "
        f"published: {counts.get('published', 0)} · "
        f"failed: {counts.get('failed', 0)}"
    )

    await message.answer(
        "<b>Status pCurator</b>\n\n"
        "Base: carregada\n"
        f"Banco: <code>{settings.database_path}</code>\n"
        f"<b>Canais</b>\n{channels_line}\n"
        f"OpenAI: {openai_state}\n"
        f"Mira: {mira_state}\n"
        f"LinkPreview: {linkprev_state}\n\n"
        f"<b>Posts</b>\n{counts_line}\n"
        f"Última publicação: {last_pub or '—'}"
    )


@router.message(Command("pc"))
async def channels_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    settings = get_settings()
    channels = await list_channels(settings.database_path)
    if not channels:
        await message.answer(
            "<b>Canais</b>\n\n"
            "Nenhum canal detectado ainda.\n"
            "Adicione o bot como <b>administrador</b> em um canal — ele aparece "
            "aqui automaticamente, já com o nome real."
        )
        return

    lines = "\n".join(
        f"• {html.escape(c['title'])}"
        + (f" (@{html.escape(c['username'])})" if c.get("username") else "")
        for c in channels
    )
    await message.answer(
        "<b>Canais disponíveis para publicar</b>\n\n"
        f"{lines}\n\n"
        "Promova o bot a administrador em outros canais para que apareçam aqui."
    )


@router.message(Command("pe"))
async def team_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    users = await list_authorized_users(settings.database_path)
    if not users:
        await message.answer(
            "<b>Equipe (co-autores)</b>\n\n"
            "Nenhum co-autor autorizado ainda.\n\n"
            "Para autorizar: <code>/pea ID Nome</code>\n"
            "O ID é o número do Telegram da pessoa — ela descobre o dela "
            "enviando /start pra @userinfobot."
        )
        return

    lines = "\n".join(
        f"• {html.escape(u.get('name') or 'sem nome')} — <code>{u['user_id']}</code>"
        for u in users
    )
    await message.answer(
        "<b>Equipe (co-autores)</b>\n\n"
        f"{lines}\n\n"
        "Toque para revogar o acesso. Autorizar mais: <code>/pea ID Nome</code>",
        reply_markup=team_keyboard(users),
    )


@router.message(Command("pea"))
async def team_add_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer(
            "Uso: <code>/pea ID Nome</code>\n"
            "Ex.: <code>/pea 123456789 Maria</code>"
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("ID inválido — precisa ser o número do Telegram da pessoa.")
        return

    if user_id == settings.owner_id:
        await message.answer("Você já é o dono — não precisa se autorizar.")
        return

    name = parts[2].strip() if len(parts) > 2 else None
    await add_authorized_user(
        settings.database_path,
        user_id=user_id,
        name=name,
        added_by=message.from_user.id,
    )
    await message.answer(
        f"✅ {html.escape(name or str(user_id))} autorizado como co-autor.\n"
        "A pessoa já pode operar o bot. Use /pe para gerenciar."
    )


@router.message(Command("buscar"))
async def discover_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    settings = get_settings()
    if not settings.gnews_key:
        await message.answer(
            "❌ <b>GNEWS_KEY</b> não está configurada no Railway.\n"
            "Sem a chave do GNews não posso buscar notícias automaticamente."
        )
        return

    # Fecha qualquer sessão/rascunho anterior — se o usuário está pedindo
    # uma nova busca, ele já abandonou o anterior. Rascunho ativo vira
    # 'ignored' e o estado in-memory da busca anterior é descartado.
    user_id = message.from_user.id
    active_id, _, _ = await get_active_context(settings.database_path, user_id)
    closed_note = ""
    if active_id:
        post = await get_post(settings.database_path, active_id)
        if post and post.get("status") == "draft":
            await update_post_status(settings.database_path, active_id, "ignored")
            closed_note = f"\n♻️ Rascunho #{active_id} anterior marcado como ignorado.\n"

        ids = await pop_last_preview_message_ids(settings.database_path, user_id)
        if ids:
            try:
                await message.bot.delete_messages(chat_id=message.chat.id, message_ids=ids)
            except TelegramBadRequest:
                for mid in ids:
                    try:
                        await message.bot.delete_message(
                            chat_id=message.chat.id, message_id=mid,
                        )
                    except TelegramBadRequest:
                        pass

        await set_active_post(
            settings.database_path, user_id=user_id, post_id=None,
            mode=None, clear_channel=True,
        )

    clear_search(user_id)

    # Orçamento de busca manual sem afetar o auto-loop
    now = datetime.now(ZoneInfo(settings.timezone))
    calls_used = await get_calls_today(settings.database_path, settings.timezone)
    cycles_left = auto_cycles_remaining_today(
        now.hour,
        set(ROTATION_BY_HOUR.keys()),
        settings.discovery_quiet_start,
        settings.discovery_quiet_end,
    )
    safe_searches = safe_manual_searches(calls_used, cycles_left)
    budget_line = (
        f"\n📊 <b>{safe_searches}</b> busca(s) manual(is) cabem hoje sem "
        f"afetar o auto-loop.\n"
        f"<i>(GNews usado hoje: {calls_used}/{GNEWS_DAILY_BUDGET} · "
        f"reserva auto restante: {cycles_left} ciclos)</i>\n"
    )

    await message.answer(
        "🔍 <b>Buscar notícia agora</b>"
        f"{closed_note}"
        f"{budget_line}\n"
        "Escolha a trilha:",
        reply_markup=discover_topic_keyboard(),
    )


@router.message(Command("pq"))
async def queue_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    settings = get_settings()
    posts = await list_recent_posts(settings.database_path, limit=8)
    counts = await count_posts_by_status(settings.database_path)

    if not posts:
        await message.answer("Fila editorial vazia.")
        return

    lines = [
        "<b>Últimos rascunhos</b>",
        (
            f"draft: {counts.get('draft', 0)} · "
            f"publishing: {counts.get('publishing', 0)} · "
            f"published: {counts.get('published', 0)} · "
            f"failed: {counts.get('failed', 0)}"
        ),
        "",
    ]
    for post in posts:
        image_status = "com imagem" if post.get("image_url") else "sem imagem"
        lines.append(
            f"#{post['id']} · {post['status']} · {post['channel_slug']} · {image_status}"
        )
    if counts.get("failed", 0) > 0:
        lines.append("")
        lines.append("Use <code>/pfr ID</code> para reabrir um post failed após verificar o canal.")

    await message.answer("\n".join(lines))


@router.message(Command("pfr"))
async def reopen_failed_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Formato: <code>/pfr ID</code>")
        return

    try:
        post_id = int(parts[1])
    except ValueError:
        await message.answer("ID precisa ser número.")
        return

    settings = get_settings()
    post = await get_post(settings.database_path, post_id)
    if not post:
        await message.answer(f"Post #{post_id} não encontrado.")
        return

    if post.get("status") != "failed":
        await message.answer(
            f"Post #{post_id} está com status '{post.get('status')}', não 'failed'. Nada a fazer."
        )
        return

    ok = await reopen_failed_post(settings.database_path, post_id)
    if not ok:
        await message.answer(f"Não foi possível reabrir o post #{post_id}.")
        return

    channel_slug = post.get("channel_slug")
    await set_active_post(
        settings.database_path,
        user_id=message.from_user.id,
        post_id=post_id,
        mode="review",
        channel_slug=channel_slug,
    )

    await message.answer(
        f"♻️ Post #{post_id} reaberto como rascunho.\n"
        "Confirme se a publicação anterior **não** saiu antes de tentar de novo."
    )
    refreshed = await get_post(settings.database_path, post_id)
    if refreshed:
        await send_post_preview(message.bot, message.chat.id, refreshed)
    await message.answer("Revise o rascunho:", reply_markup=review_keyboard())


@router.message(Command("pf"))
async def sources_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
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

    await message.answer("\n".join(lines))


@router.message(Command("pfa"))
async def add_source_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    text = message.text or ""
    raw = text.replace("/pfa", "", 1).strip()
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) < 1 or not parts[0]:
        await message.answer(
            "Formato: <code>/pfa Nome | url | escopo | nota</code>\n"
            "Exemplo: <code>/pfa G1 | https://g1.globo.com | global | 80</code>"
        )
        return

    name = parts[0]
    url = parts[1] if len(parts) > 1 and parts[1] else None
    scope = parts[2] if len(parts) > 2 and parts[2] else "global"

    try:
        quality_score = int(parts[3]) if len(parts) > 3 and parts[3] else 70
    except ValueError:
        quality_score = 70

    quality_score = max(0, min(100, quality_score))
    settings = get_settings()
    source_id = await upsert_source(
        settings.database_path,
        name=name,
        url=url,
        scope=scope,
        quality_score=quality_score,
    )

    await message.answer(
        f"✅ Fonte salva: #{source_id}\n"
        f"Nome: {name}\nEscopo: {scope}\nNota: {quality_score}\n"
        f"URL: {url or '—'}"
    )


@router.message(Command("pfs"))
async def source_score_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Formato: <code>/pfs ID nota</code>")
        return

    try:
        source_id = int(parts[1])
        quality_score = max(0, min(100, int(parts[2])))
    except ValueError:
        await message.answer("ID e nota precisam ser números.")
        return

    settings = get_settings()
    sources = await list_sources(settings.database_path, limit=1000)
    current = next((s for s in sources if s["id"] == source_id), None)
    if not current:
        await message.answer(f"Fonte #{source_id} não encontrada.")
        return

    old_score = current["quality_score"]
    await update_source_score(settings.database_path, source_id, quality_score)
    await message.answer(
        f"✅ Fonte #{source_id} ({current['name']}): nota {old_score} → {quality_score}."
    )


@router.message(Command("pfb"))
async def source_block_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Formato: <code>/pfb ID</code>")
        return

    try:
        source_id = int(parts[1])
    except ValueError:
        await message.answer("ID precisa ser número.")
        return

    settings = get_settings()
    sources = await list_sources(settings.database_path, limit=1000)
    current = next((s for s in sources if s["id"] == source_id), None)
    if not current:
        await message.answer(f"Fonte #{source_id} não encontrada.")
        return

    await set_source_blocked(settings.database_path, source_id, True)
    await message.answer(f"🚫 Fonte #{source_id} ({current['name']}) bloqueada.")


@router.message(Command("pfu"))
async def source_unblock_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Formato: <code>/pfu ID</code>")
        return

    try:
        source_id = int(parts[1])
    except ValueError:
        await message.answer("ID precisa ser número.")
        return

    settings = get_settings()
    sources = await list_sources(settings.database_path, limit=1000)
    current = next((s for s in sources if s["id"] == source_id), None)
    if not current:
        await message.answer(f"Fonte #{source_id} não encontrada.")
        return

    await set_source_blocked(settings.database_path, source_id, False)
    await message.answer(f"✅ Fonte #{source_id} ({current['name']}) desbloqueada.")


@router.message(Command("pr"))
async def rules_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    settings = get_settings()
    rules = await list_rules(settings.database_path, limit=10)

    if not rules:
        await message.answer("Nenhuma regra aprendida cadastrada ainda.")
        return

    lines = ["<b>Regras aprendidas</b>", ""]
    for rule in rules:
        state = "ativa" if rule["is_enabled"] else "inativa"
        channel = rule["channel_slug"] or "global"
        lines.append(
            f"#{rule['id']} · {channel} · {rule['rule_type']} · peso {rule['weight']} · {state}\n{rule['rule_text']}"
        )

    await message.answer("\n\n".join(lines))


@router.message(Command("pra"))
async def add_rule_command(message: Message) -> None:
    if await reject_message_if_not_allowed(message):
        return

    text = message.text or ""
    raw = text.replace("/pra", "", 1).strip()
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) < 3:
        await message.answer(
            "Formato: <code>/pra canal | tipo | regra</code>\n"
            "Exemplo: <code>/pra c1 | tom | evitar assunto pesado no canal leve</code>"
        )
        return

    channel_slug = parts[0] or None
    rule_type = parts[1] or "general"
    rule_text = parts[2]

    settings = get_settings()
    rule_id = await add_rule(
        settings.database_path,
        channel_slug=channel_slug,
        rule_type=rule_type,
        rule_text=rule_text,
    )

    await message.answer(
        f"✅ Regra #{rule_id} cadastrada para canal '{channel_slug or 'global'}', tipo '{rule_type}'."
    )
