import json
from typing import Any

import aiosqlite


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def upsert_reaction_watch(
    database_path: str,
    *,
    chat_id: int,
    message_id: int,
    channel_username: str | None,
    channel_title: str | None,
    post_link: str,
    created_by: int | None,
) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO reaction_watches (
                chat_id, message_id, channel_username, channel_title,
                post_link, created_by, is_active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                channel_username = excluded.channel_username,
                channel_title = excluded.channel_title,
                post_link = excluded.post_link,
                is_active = 1
            """,
            (chat_id, message_id, channel_username, channel_title, post_link, created_by),
        )
        await db.commit()


async def get_reaction_watch(database_path: str, chat_id: int, message_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM reaction_watches
            WHERE chat_id = ? AND message_id = ?
            """,
            (chat_id, message_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_reaction_watches(database_path: str, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM reaction_watches
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def deactivate_reaction_watch(database_path: str, chat_id: int, message_id: int) -> bool:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            UPDATE reaction_watches
            SET is_active = 0
            WHERE chat_id = ? AND message_id = ? AND is_active = 1
            """,
            (chat_id, message_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def record_reaction_event(
    database_path: str,
    *,
    chat_id: int,
    message_id: int,
    event_type: str,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    actor_name: str | None = None,
    actor_chat_id: int | None = None,
    actor_chat_title: str | None = None,
    old_reaction: Any = None,
    new_reaction: Any = None,
    reactions: Any = None,
) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO reaction_events (
                chat_id, message_id, event_type,
                actor_user_id, actor_username, actor_name,
                actor_chat_id, actor_chat_title,
                old_reaction_json, new_reaction_json, reactions_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                chat_id,
                message_id,
                event_type,
                actor_user_id,
                actor_username,
                actor_name,
                actor_chat_id,
                actor_chat_title,
                _json_dumps(old_reaction),
                _json_dumps(new_reaction),
                _json_dumps(reactions),
            ),
        )
        await db.execute(
            """
            UPDATE reaction_watches
            SET last_event_at = CURRENT_TIMESTAMP
            WHERE chat_id = ? AND message_id = ?
            """,
            (chat_id, message_id),
        )
        await db.commit()


async def list_reaction_events(
    database_path: str,
    chat_id: int,
    message_id: int,
    limit: int = 20,
) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM reaction_events
            WHERE chat_id = ? AND message_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, message_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]
