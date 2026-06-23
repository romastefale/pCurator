import json

import aiosqlite


def _int_or_none(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


async def upsert_channel(
    database_path: str,
    *,
    chat_id: int,
    title: str,
    username: str | None = None,
    access_state: str | None = None,
    access_reason: str | None = None,
    recovery_score: int | None = None,
    recovery_evidence: str | None = None,
    bot_member_status: str | None = None,
    can_post_messages: bool | None = None,
    can_edit_messages: bool | None = None,
    can_delete_messages: bool | None = None,
    last_probe_message_id: int | None = None,
) -> None:
    """Insere ou atualiza um canal pela identidade chat_id.

    Reativa (is_enabled=1) se estava desabilitado. slug = str(chat_id) (a
    coluna legada slug é NOT NULL UNIQUE; usamos o próprio chat_id para
    satisfazer). Campos de recuperação guardam a prova usada pelo motor
    científico-combinatório.
    """
    evidence = recovery_evidence
    if isinstance(recovery_evidence, (list, tuple, set)):
        evidence = json.dumps(list(recovery_evidence), ensure_ascii=False)

    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO channels (
                slug, chat_id, title, username, is_enabled,
                last_access_state, last_access_reason, last_verified_at,
                last_restored_at, left_by_adeus, recovery_score,
                recovery_evidence, bot_member_status, can_post_messages,
                can_edit_messages, can_delete_messages, last_probe_message_id,
                last_probe_at, created_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, 1,
                ?, ?, CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP, 0, ?,
                ?, ?, ?, ?, ?, ?,
                CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username,
                is_enabled = 1,
                last_access_state = COALESCE(excluded.last_access_state, channels.last_access_state),
                last_access_reason = COALESCE(excluded.last_access_reason, channels.last_access_reason),
                last_verified_at = CURRENT_TIMESTAMP,
                last_restored_at = CURRENT_TIMESTAMP,
                left_by_adeus = 0,
                recovery_score = COALESCE(excluded.recovery_score, channels.recovery_score),
                recovery_evidence = COALESCE(excluded.recovery_evidence, channels.recovery_evidence),
                bot_member_status = COALESCE(excluded.bot_member_status, channels.bot_member_status),
                can_post_messages = COALESCE(excluded.can_post_messages, channels.can_post_messages),
                can_edit_messages = COALESCE(excluded.can_edit_messages, channels.can_edit_messages),
                can_delete_messages = COALESCE(excluded.can_delete_messages, channels.can_delete_messages),
                last_probe_message_id = COALESCE(excluded.last_probe_message_id, channels.last_probe_message_id),
                last_probe_at = CASE
                    WHEN excluded.last_probe_message_id IS NULL THEN channels.last_probe_at
                    ELSE CURRENT_TIMESTAMP
                END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(chat_id),
                chat_id,
                title,
                username,
                access_state,
                access_reason,
                recovery_score,
                evidence,
                bot_member_status,
                _int_or_none(can_post_messages),
                _int_or_none(can_edit_messages),
                _int_or_none(can_delete_messages),
                last_probe_message_id,
                last_probe_message_id,
            ),
        )
        await db.commit()


async def set_channel_enabled(database_path: str, chat_id: int, enabled: bool) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            UPDATE channels SET
                is_enabled = ?,
                last_access_state = CASE WHEN ? = 1 THEN 'enabled_manual' ELSE 'disabled_manual' END,
                last_verified_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
            """,
            (1 if enabled else 0, 1 if enabled else 0, chat_id),
        )
        await db.commit()


async def update_channel_access_state(
    database_path: str,
    chat_id: int,
    *,
    is_enabled: bool | None = None,
    state: str | None = None,
    reason: str | None = None,
    recovery_score: int | None = None,
    recovery_evidence: str | None = None,
    bot_member_status: str | None = None,
    can_post_messages: bool | None = None,
    can_edit_messages: bool | None = None,
    can_delete_messages: bool | None = None,
) -> None:
    assignments = [
        "last_access_state = COALESCE(?, last_access_state)",
        "last_access_reason = COALESCE(?, last_access_reason)",
        "recovery_score = COALESCE(?, recovery_score)",
        "recovery_evidence = COALESCE(?, recovery_evidence)",
        "bot_member_status = COALESCE(?, bot_member_status)",
        "can_post_messages = COALESCE(?, can_post_messages)",
        "can_edit_messages = COALESCE(?, can_edit_messages)",
        "can_delete_messages = COALESCE(?, can_delete_messages)",
        "last_verified_at = CURRENT_TIMESTAMP",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    values: list[object] = [
        state,
        reason,
        recovery_score,
        recovery_evidence,
        bot_member_status,
        _int_or_none(can_post_messages),
        _int_or_none(can_edit_messages),
        _int_or_none(can_delete_messages),
    ]
    if is_enabled is not None:
        assignments.insert(0, "is_enabled = ?")
        values.insert(0, 1 if is_enabled else 0)
    values.append(chat_id)
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            f"UPDATE channels SET {', '.join(assignments)} WHERE chat_id = ?",
            values,
        )
        if cursor.rowcount == 0:
            await db.execute(
                """
                INSERT OR IGNORE INTO channels (
                    slug, chat_id, title, is_enabled, last_access_state,
                    last_access_reason, last_verified_at, recovery_score,
                    recovery_evidence, bot_member_status, can_post_messages,
                    can_edit_messages, can_delete_messages, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    str(chat_id),
                    chat_id,
                    str(chat_id),
                    1 if is_enabled else 0,
                    state,
                    reason,
                    recovery_score,
                    recovery_evidence,
                    bot_member_status,
                    _int_or_none(can_post_messages),
                    _int_or_none(can_edit_messages),
                    _int_or_none(can_delete_messages),
                ),
            )
        await db.commit()


async def mark_channel_left_by_adeus(
    database_path: str,
    chat_id: int,
    *,
    title: str | None = None,
    username: str | None = None,
    reason: str | None = None,
) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO channels (
                slug, chat_id, title, username, is_enabled, left_by_adeus,
                left_at, last_access_state, last_access_reason,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 0, 1, CURRENT_TIMESTAMP, 'left_by_adeus', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = COALESCE(excluded.title, channels.title),
                username = COALESCE(excluded.username, channels.username),
                is_enabled = 0,
                left_by_adeus = 1,
                left_at = CURRENT_TIMESTAMP,
                last_access_state = 'left_by_adeus',
                last_access_reason = COALESCE(excluded.last_access_reason, channels.last_access_reason),
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(chat_id), chat_id, title or str(chat_id), username, reason),
        )
        await db.commit()


async def list_channels(database_path: str, only_enabled: bool = True) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT chat_id, title, username, is_enabled,
                   last_access_state, last_access_reason, last_verified_at,
                   last_restored_at, left_by_adeus, left_at, recovery_score,
                   recovery_evidence, bot_member_status, can_post_messages,
                   can_edit_messages, can_delete_messages, last_probe_message_id,
                   last_probe_at
            FROM channels
            WHERE chat_id IS NOT NULL
        """
        if only_enabled:
            query += " AND is_enabled = 1"
        query += " ORDER BY title COLLATE NOCASE"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def list_channel_memory(database_path: str) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT chat_id, title, username, is_enabled,
                   last_access_state, last_access_reason, last_verified_at,
                   last_restored_at, left_by_adeus, left_at, recovery_score,
                   recovery_evidence, bot_member_status, can_post_messages,
                   can_edit_messages, can_delete_messages, last_probe_message_id,
                   last_probe_at
            FROM channels
            WHERE chat_id IS NOT NULL
            ORDER BY COALESCE(left_at, updated_at, created_at) DESC, title COLLATE NOCASE
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_channel(database_path: str, chat_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT chat_id, title, username, is_enabled,
                   last_access_state, last_access_reason, last_verified_at,
                   last_restored_at, left_by_adeus, left_at, recovery_score,
                   recovery_evidence, bot_member_status, can_post_messages,
                   can_edit_messages, can_delete_messages, last_probe_message_id,
                   last_probe_at
            FROM channels
            WHERE chat_id = ?
            """,
            (chat_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
