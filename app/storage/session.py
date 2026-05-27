import json

import aiosqlite


async def set_active_post(
    database_path: str,
    *,
    user_id: int,
    post_id: int | None,
    mode: str | None = None,
    channel_slug: str | None = None,
    clear_channel: bool = False,
) -> None:
    async with aiosqlite.connect(database_path) as db:
        if clear_channel:
            await db.execute(
                """
                INSERT INTO editorial_sessions
                    (user_id, active_post_id, active_channel_slug, mode, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    active_post_id = excluded.active_post_id,
                    active_channel_slug = NULL,
                    mode = excluded.mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, post_id, None, mode),
            )
        else:
            await db.execute(
                """
                INSERT INTO editorial_sessions
                    (user_id, active_post_id, active_channel_slug, mode, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    active_post_id = excluded.active_post_id,
                    active_channel_slug = COALESCE(excluded.active_channel_slug, active_channel_slug),
                    mode = excluded.mode,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, post_id, channel_slug, mode),
            )
        await db.commit()


async def try_claim_idle_session(
    database_path: str,
    *,
    user_id: int,
    post_id: int,
    mode: str,
    channel_slug: str | None = None,
) -> bool:
    """Reserva atômica: só seta active_post_id se a sessão estiver ociosa
    (linha inexistente ou active_post_id IS NULL). Devolve True se ganhou
    a sessão; False se já havia rascunho ativo (auto-discovery deve abortar
    sem clobberar o trabalho manual em curso)."""
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO editorial_sessions
                (user_id, active_post_id, active_channel_slug, mode, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                active_post_id = excluded.active_post_id,
                active_channel_slug = excluded.active_channel_slug,
                mode = excluded.mode,
                updated_at = CURRENT_TIMESTAMP
            WHERE editorial_sessions.active_post_id IS NULL
            """,
            (user_id, post_id, channel_slug, mode),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_active_post(database_path: str, user_id: int) -> tuple[int | None, str | None]:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT active_post_id, mode FROM editorial_sessions WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None, None
        return row[0], row[1]


async def set_last_preview_message_ids(
    database_path: str, user_id: int, message_ids: list[int]
) -> None:
    payload = json.dumps(message_ids) if message_ids else None
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE editorial_sessions SET last_preview_message_ids = ? WHERE user_id = ?",
            (payload, user_id),
        )
        await db.commit()


async def pop_last_preview_message_ids(database_path: str, user_id: int) -> list[int]:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT last_preview_message_ids FROM editorial_sessions WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return []
        await db.execute(
            "UPDATE editorial_sessions SET last_preview_message_ids = NULL WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
        try:
            ids = json.loads(row[0])
            return [int(x) for x in ids if isinstance(x, (int, str))]
        except (ValueError, TypeError):
            return []


async def get_active_context(database_path: str, user_id: int) -> tuple[int | None, str | None, str | None]:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            SELECT active_post_id, active_channel_slug, mode
            FROM editorial_sessions
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None, None, None
        return row[0], row[1], row[2]
