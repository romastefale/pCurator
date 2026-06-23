"""Motor científico-combinatório de recuperação de canais.

Este módulo não presume que o Telegram reteve permissão depois de /adeus.
Ele coleta todas as evidências locais disponíveis, monta hipóteses por chat_id
histórico e testa com o mesmo token do bot. Se o token ainda conseguir falar no
canal, o canal volta para a lista local. Se o Telegram negar, o motor registra
qual hipótese falhou e por quê.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import html
import json
import logging
from typing import Any

import aiosqlite
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.storage.channels import upsert_channel, update_channel_access_state

logger = logging.getLogger(__name__)

_ADMIN_STATUSES = {"administrator", "creator"}


@dataclass
class ChannelCandidate:
    chat_id: int
    title: str | None = None
    username: str | None = None
    sources: set[str] = field(default_factory=set)
    post_count: int = 0
    reaction_count: int = 0
    score: int = 0

    def add(self, source: str, points: int, *, title: str | None = None, username: str | None = None) -> None:
        self.sources.add(source)
        self.score += points
        if title and not self.title:
            self.title = title
        if username and not self.username:
            self.username = username

    @property
    def evidence_label(self) -> str:
        ordered = sorted(self.sources)
        return ", ".join(ordered) if ordered else "sem evidência"


@dataclass
class RecoveryResult:
    chat_id: int
    title: str | None
    username: str | None
    ok: bool
    restored: bool
    state: str
    reason: str
    status: str | None = None
    can_post_messages: bool | None = None
    can_edit_messages: bool | None = None
    can_delete_messages: bool | None = None
    score: int = 0
    sources: list[str] = field(default_factory=list)
    probe_message_id: int | None = None
    probe_deleted: bool | None = None

    def line(self) -> str:
        marker = "✅" if self.ok else "❌"
        title = html.escape(self.title or str(self.chat_id))
        suffix = f" — @{html.escape(self.username)}" if self.username else ""
        details = html.escape(self.reason)
        src = html.escape(", ".join(self.sources) or "sem evidência")
        return (
            f"{marker} <code>{self.chat_id}</code> — <b>{title}</b>{suffix}\n"
            f"   estado: <code>{html.escape(self.state)}</code> · score: <code>{self.score}</code>\n"
            f"   prova: {details}\n"
            f"   fontes: {src}"
        )


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _status_text(member: Any) -> str | None:
    status = getattr(member, "status", None)
    if status is None:
        return None
    value = getattr(status, "value", None)
    return str(value if value is not None else status)


def _flag(member: Any, name: str) -> bool | None:
    value = getattr(member, name, None)
    if value is None:
        return None
    return bool(value)


def _can_publish(chat_type: str | None, status: str | None, can_post_messages: bool | None) -> bool:
    if status == "creator":
        return True
    if status != "administrator":
        return False
    # Em canal, publicar exige can_post_messages. Em supergrupo, admin já basta
    # para o fluxo histórico do pCurator, mas se o campo vier False, respeita.
    if chat_type == "channel":
        return can_post_messages is True
    return can_post_messages is not False


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table,),
    )
    return await cursor.fetchone() is not None


async def collect_channel_candidates(
    database_path: str,
    *,
    env_chat_ids: list[int | None] | None = None,
    only_chat_id: int | None = None,
) -> list[ChannelCandidate]:
    """Coleta hipóteses de canal a partir do banco inteiro.

    Pontuação: canal cadastrado pesa mais, publicação histórica prova uso real,
    reação/watchlist reforça identidade, env fixa hipótese manual.
    """
    candidates: dict[int, ChannelCandidate] = {}

    def ensure(chat_id: int) -> ChannelCandidate:
        item = candidates.get(chat_id)
        if item is None:
            item = ChannelCandidate(chat_id=chat_id)
            candidates[chat_id] = item
        return item

    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row

        if await _table_exists(db, "channels"):
            cursor = await db.execute(
                """
                SELECT chat_id, title, username, is_enabled,
                       COALESCE(left_by_adeus, 0) AS left_by_adeus
                FROM channels
                WHERE chat_id IS NOT NULL
                """
            )
            for row in await cursor.fetchall():
                chat_id = _as_int(row["chat_id"])
                if chat_id is None:
                    continue
                points = 80 if int(row["is_enabled"] or 0) else 55
                if int(row["left_by_adeus"] or 0):
                    points += 15
                ensure(chat_id).add(
                    "channels" + (":adeus" if int(row["left_by_adeus"] or 0) else ""),
                    points,
                    title=row["title"],
                    username=row["username"],
                )

        if await _table_exists(db, "posts"):
            cursor = await db.execute(
                """
                SELECT published_chat_id AS chat_id,
                       COUNT(*) AS total,
                       MAX(published_at) AS last_published_at
                FROM posts
                WHERE published_chat_id IS NOT NULL
                GROUP BY published_chat_id
                """
            )
            for row in await cursor.fetchall():
                chat_id = _as_int(row["chat_id"])
                if chat_id is None:
                    continue
                item = ensure(chat_id)
                total = int(row["total"] or 0)
                item.post_count += total
                item.add("posts:published_chat_id", 70 + min(total, 50))

            cursor = await db.execute(
                """
                SELECT channel_slug, COUNT(*) AS total
                FROM posts
                WHERE channel_slug GLOB '-[0-9]*' OR channel_slug GLOB '[0-9]*'
                GROUP BY channel_slug
                """
            )
            for row in await cursor.fetchall():
                chat_id = _as_int(row["channel_slug"])
                if chat_id is None:
                    continue
                item = ensure(chat_id)
                total = int(row["total"] or 0)
                item.post_count += total
                item.add("posts:channel_slug", 35 + min(total, 30))

        if await _table_exists(db, "reaction_watches"):
            cursor = await db.execute(
                """
                SELECT chat_id, MAX(channel_title) AS title, MAX(channel_username) AS username,
                       COUNT(*) AS total
                FROM reaction_watches
                WHERE chat_id IS NOT NULL
                GROUP BY chat_id
                """
            )
            for row in await cursor.fetchall():
                chat_id = _as_int(row["chat_id"])
                if chat_id is None:
                    continue
                item = ensure(chat_id)
                total = int(row["total"] or 0)
                item.reaction_count += total
                item.add(
                    "reaction_watches",
                    30 + min(total, 20),
                    title=row["title"],
                    username=row["username"],
                )

        if await _table_exists(db, "reaction_post_metadata"):
            cursor = await db.execute(
                """
                SELECT chat_id, MAX(channel_title) AS title, MAX(channel_username) AS username,
                       COUNT(*) AS total
                FROM reaction_post_metadata
                WHERE chat_id IS NOT NULL
                GROUP BY chat_id
                """
            )
            for row in await cursor.fetchall():
                chat_id = _as_int(row["chat_id"])
                if chat_id is None:
                    continue
                item = ensure(chat_id)
                total = int(row["total"] or 0)
                item.reaction_count += total
                item.add(
                    "reaction_post_metadata",
                    25 + min(total, 20),
                    title=row["title"],
                    username=row["username"],
                )

        if await _table_exists(db, "editorial_sessions"):
            cursor = await db.execute(
                """
                SELECT active_channel_slug, COUNT(*) AS total
                FROM editorial_sessions
                WHERE active_channel_slug IS NOT NULL
                GROUP BY active_channel_slug
                """
            )
            for row in await cursor.fetchall():
                chat_id = _as_int(row["active_channel_slug"])
                if chat_id is None:
                    continue
                ensure(chat_id).add("editorial_sessions", 10 + min(int(row["total"] or 0), 10))

    for chat_id in env_chat_ids or []:
        cid = _as_int(chat_id)
        if cid is not None:
            ensure(cid).add("env:CHANNEL_ID", 60)

    items = list(candidates.values())
    if only_chat_id is not None:
        items = [item for item in items if item.chat_id == only_chat_id]
    items.sort(key=lambda item: (-item.score, item.chat_id))
    return items


async def _active_post_restore_probe(
    bot: Bot,
    database_path: str,
    candidate: ChannelCandidate,
    result: RecoveryResult,
    *,
    previous_state: str,
    previous_reason: str,
) -> bool:
    """Prova máxima: tenta publicar com o mesmo token no chat_id histórico.

    Essa rotina roda mesmo quando get_chat/getChatMember falham. A hipótese do
    usuário é testada de forma objetiva: se o token ainda reteve permissão real
    de postagem no canal, send_message passa e o canal é reativado. Se falhar,
    o banco guarda o erro como evidência, mas mantém a hipótese recuperável.
    """
    chat_id = candidate.chat_id
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text="pCurator prova técnica de restauração — apagando automaticamente.",
            disable_notification=True,
        )
        result.probe_message_id = sent.message_id
        deleted = False
        try:
            await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
            deleted = True
        except TelegramAPIError as delete_exc:
            logger.warning(
                "channel_recovery_probe_delete_failed chat_id=%s message_id=%s err=%s",
                chat_id,
                sent.message_id,
                type(delete_exc).__name__,
            )
        result.probe_deleted = deleted
        await upsert_channel(
            database_path,
            chat_id=chat_id,
            title=result.title or str(chat_id),
            username=result.username,
            access_state="restored_by_direct_token_post",
            access_reason=(
                f"send_message succeeded after {previous_state}; delete_probe={deleted}; "
                f"previous={previous_reason}; evidence={candidate.evidence_label}"
            ),
            recovery_score=candidate.score,
            recovery_evidence=json.dumps(result.sources, ensure_ascii=False),
            bot_member_status=result.status,
            can_post_messages=result.can_post_messages,
            can_edit_messages=result.can_edit_messages,
            can_delete_messages=result.can_delete_messages,
            last_probe_message_id=sent.message_id,
        )
        result.ok = True
        result.restored = True
        result.state = "restored_by_direct_token_post"
        result.reason = "o mesmo token conseguiu postar diretamente no chat_id histórico; canal restaurado"
        return True
    except TelegramAPIError as exc:
        result.state = "direct_token_post_failed"
        result.reason = (
            f"send_message direto negado: {type(exc).__name__}: {exc}; "
            f"passivo={previous_state}: {previous_reason}"
        )
        await update_channel_access_state(
            database_path,
            chat_id,
            is_enabled=False,
            state=result.state,
            reason=result.reason,
            recovery_score=candidate.score,
            recovery_evidence=json.dumps(result.sources, ensure_ascii=False),
            bot_member_status=result.status,
            can_post_messages=result.can_post_messages,
            can_edit_messages=result.can_edit_messages,
            can_delete_messages=result.can_delete_messages,
        )
        return False


async def recover_candidate(
    bot: Bot,
    database_path: str,
    candidate: ChannelCandidate,
    *,
    active_probe: bool = True,
) -> RecoveryResult:
    """Testa uma hipótese de canal com o token atual.

    active_probe=True faz a prova mais forte primeiro quando a leitura passiva
    falha: tenta publicar diretamente no chat_id histórico com o mesmo token.
    Isso evita a falha anterior em que get_chat_failed encerrava o teste antes
    da tentativa real de postagem.
    """
    chat_id = candidate.chat_id
    result = RecoveryResult(
        chat_id=chat_id,
        title=candidate.title,
        username=candidate.username,
        ok=False,
        restored=False,
        state="candidate",
        reason="não testado",
        score=candidate.score,
        sources=sorted(candidate.sources),
    )

    chat_type: str | None = None
    try:
        chat = await bot.get_chat(chat_id)
        result.title = getattr(chat, "title", None) or result.title or str(chat_id)
        result.username = getattr(chat, "username", None) or result.username
        chat_type = str(getattr(chat, "type", None) or "")
        result.state = "get_chat_ok"
        result.reason = "get_chat confirmou acesso ao chat"
    except TelegramAPIError as exc:
        result.state = "get_chat_failed"
        result.reason = f"get_chat negado: {type(exc).__name__}: {exc}"
        if active_probe:
            await _active_post_restore_probe(
                bot,
                database_path,
                candidate,
                result,
                previous_state="get_chat_failed",
                previous_reason=result.reason,
            )
            return result
        await update_channel_access_state(
            database_path,
            chat_id,
            is_enabled=False,
            state=result.state,
            reason=result.reason,
            recovery_score=candidate.score,
            recovery_evidence=json.dumps(result.sources, ensure_ascii=False),
        )
        return result

    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        status = _status_text(member)
        can_post = _flag(member, "can_post_messages")
        can_edit = _flag(member, "can_edit_messages")
        can_delete = _flag(member, "can_delete_messages")
        result.status = status
        result.can_post_messages = can_post
        result.can_edit_messages = can_edit
        result.can_delete_messages = can_delete
        if _can_publish(chat_type, status, can_post):
            await upsert_channel(
                database_path,
                chat_id=chat_id,
                title=result.title or str(chat_id),
                username=result.username,
                access_state="restored_by_member_probe",
                access_reason=(
                    f"status={status}; can_post_messages={can_post}; "
                    f"evidence={candidate.evidence_label}"
                ),
                recovery_score=candidate.score,
                recovery_evidence=json.dumps(result.sources, ensure_ascii=False),
                bot_member_status=status,
                can_post_messages=can_post,
                can_edit_messages=can_edit,
                can_delete_messages=can_delete,
            )
            result.ok = True
            result.restored = True
            result.state = "restored_by_member_probe"
            result.reason = f"getChatMember confirmou permissão de publicar ({status})"
            return result
        result.state = "member_not_publishable"
        result.reason = f"status={status}; can_post_messages={can_post}"
    except TelegramAPIError as exc:
        result.state = "get_chat_member_failed"
        result.reason = f"getChatMember negado: {type(exc).__name__}: {exc}"

    if active_probe:
        await _active_post_restore_probe(
            bot,
            database_path,
            candidate,
            result,
            previous_state=result.state,
            previous_reason=result.reason,
        )
        return result

    await update_channel_access_state(
        database_path,
        chat_id,
        is_enabled=False,
        state=result.state,
        reason=result.reason,
        recovery_score=candidate.score,
        recovery_evidence=json.dumps(result.sources, ensure_ascii=False),
        bot_member_status=result.status,
        can_post_messages=result.can_post_messages,
        can_edit_messages=result.can_edit_messages,
        can_delete_messages=result.can_delete_messages,
    )
    return result


async def recover_channels(
    bot: Bot,
    database_path: str,
    *,
    env_chat_ids: list[int | None] | None = None,
    only_chat_id: int | None = None,
    active_probe: bool = True,
    limit: int = 25,
) -> list[RecoveryResult]:
    candidates = await collect_channel_candidates(
        database_path,
        env_chat_ids=env_chat_ids,
        only_chat_id=only_chat_id,
    )
    results: list[RecoveryResult] = []
    for candidate in candidates[:limit]:
        results.append(
            await recover_candidate(
                bot,
                database_path,
                candidate,
                active_probe=active_probe,
            )
        )
    return results
