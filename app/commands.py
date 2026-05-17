from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.access import reject_message_if_not_owner
from app.settings import get_settings
from app.storage.posts import list_recent_posts
from app.storage.rules import add_rule, list_rules
from app.storage.sources import (
    list_sources,
    set_source_blocked,
    update_source_score,
    upsert_source,
)

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
        "/pfa Nome | url | escopo | nota — cadastrar fonte\n"
        "/pfs ID nota — alterar nota da fonte\n"
        "/pfb ID — bloquear fonte\n"
        "/pfu ID — desbloquear fonte\n"
        "/pr — regras aprendidas\n"
        "/pra canal | tipo | regra — cadastrar regra\n",
        parse_mode="HTML",
    )


@router.message(Command("ps"))
async def status_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    c1 = "configurado" if settings.channel_1_id else "pendente"
    c2 = "configurado" if settings.channel_2_id else "pendente"

    await message.answer(
        "<b>Status pCurator</b>\n\n"
        "Base: carregada\n"
        f"Banco: <code>{settings.database_path}</code>\n"
        f"Canal 1: {c1}\n"
        f"Canal 2: {c2}\n"
        "Modo atual: manual assistido\n",
        parse_mode="HTML",
    )


@router.message(Command("pq"))
async def queue_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    settings = get_settings()
    posts = await list_recent_posts(settings.database_path, limit=5)

    if not posts:
        await message.answer("Fila editorial vazia.")
        return

    lines = ["<b>Últimos rascunhos</b>", ""]
    for post in posts:
        image_status = "com imagem" if post.get("image_url") else "sem imagem"
        lines.append(
            f"#{post['id']} · {post['status']} · {post['channel_slug']} · {image_status}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("pf"))
async def sources_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
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

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("pfa"))
async def add_source_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    text = message.text or ""
    raw = text.replace("/pfa", "", 1).strip()
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) < 1 or not parts[0]:
        await message.answer(
            "Formato: <code>/pfa Nome | url | escopo | nota</code>\n"
            "Exemplo: <code>/pfa G1 | https://g1.globo.com | global | 80</code>",
            parse_mode="HTML",
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
        f"Fonte cadastrada: #{source_id} · {name} · {scope} · {quality_score}"
    )


@router.message(Command("pfs"))
async def source_score_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Formato: <code>/pfs ID nota</code>", parse_mode="HTML")
        return

    try:
        source_id = int(parts[1])
        quality_score = max(0, min(100, int(parts[2])))
    except ValueError:
        await message.answer("ID e nota precisam ser números.")
        return

    settings = get_settings()
    await update_source_score(settings.database_path, source_id, quality_score)
    await message.answer(f"Fonte #{source_id} atualizada para nota {quality_score}.")


@router.message(Command("pfb"))
async def source_block_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Formato: <code>/pfb ID</code>", parse_mode="HTML")
        return

    try:
        source_id = int(parts[1])
    except ValueError:
        await message.answer("ID precisa ser número.")
        return

    settings = get_settings()
    await set_source_blocked(settings.database_path, source_id, True)
    await message.answer(f"Fonte #{source_id} bloqueada.")


@router.message(Command("pfu"))
async def source_unblock_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("Formato: <code>/pfu ID</code>", parse_mode="HTML")
        return

    try:
        source_id = int(parts[1])
    except ValueError:
        await message.answer("ID precisa ser número.")
        return

    settings = get_settings()
    await set_source_blocked(settings.database_path, source_id, False)
    await message.answer(f"Fonte #{source_id} desbloqueada.")


@router.message(Command("pr"))
async def rules_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
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

    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("pra"))
async def add_rule_command(message: Message) -> None:
    if await reject_message_if_not_owner(message):
        return

    text = message.text or ""
    raw = text.replace("/pra", "", 1).strip()
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) < 3:
        await message.answer(
            "Formato: <code>/pra canal | tipo | regra</code>\n"
            "Exemplo: <code>/pra c1 | tom | evitar assunto pesado no canal leve</code>",
            parse_mode="HTML",
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

    await message.answer(f"Regra cadastrada: #{rule_id}")
