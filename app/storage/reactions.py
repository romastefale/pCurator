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
    source: str = "manual",
) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO reaction_watches (
                chat_id, message_id, channel_username, channel_title,
                post_link, created_by, source, is_active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id, message_id) DO UPDATE SET
                channel_username = COALESCE(excluded.channel_username, reaction_watches.channel_username),
                channel_title = COALESCE(excluded.channel_title, reaction_watches.channel_title),
                post_link = excluded.post_link,
                created_by = COALESCE(excluded.created_by, reaction_watches.created_by),
                source = excluded.source,
                is_active = 1
            """,
            (chat_id, message_id, channel_username, channel_title, post_link, created_by, source),
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
            ORDER BY created_at DESC, id DESC
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
        return (cursor.rowcount or 0) > 0


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

async def record_reaction_snapshot(
    database_path: str,
    *,
    chat_id: int,
    message_id: int,
    reaction_key: str,
    reaction_type: str,
    total_count: int,
    data_mode: str,
    telegram_date: str | None = None,
    total_reactions: int | None = None,
    reaction_kinds: int | None = None,
    dominant_reaction: str | None = None,
) -> dict:
    """Persiste um snapshot estatístico de reação e calcula delta contra o último snapshot salvo."""
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT total_count
            FROM reaction_snapshots
            WHERE chat_id = ? AND message_id = ? AND reaction_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, message_id, reaction_key),
        )
        previous = await cursor.fetchone()
        previous_count = int(previous["total_count"]) if previous else None
        delta_count = None if previous_count is None else int(total_count) - previous_count
        await db.execute(
            """
            INSERT INTO reaction_snapshots (
                chat_id, message_id, reaction_key, reaction_type,
                total_count, previous_count, delta_count,
                total_reactions, reaction_kinds, dominant_reaction,
                data_mode, telegram_date, captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                chat_id,
                message_id,
                reaction_key,
                reaction_type,
                total_count,
                previous_count,
                delta_count,
                total_reactions,
                reaction_kinds,
                dominant_reaction,
                data_mode,
                telegram_date,
            ),
        )
        await db.commit()
        cursor = await db.execute(
            """
            SELECT *
            FROM reaction_snapshots
            WHERE rowid = last_insert_rowid()
            """
        )
        row = await cursor.fetchone()
        return dict(row)


async def latest_reaction_snapshots(
    database_path: str,
    chat_id: int,
    message_id: int,
) -> list[dict]:
    """Retorna o snapshot mais recente de cada reação para um post."""
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.*
            FROM reaction_snapshots s
            JOIN (
                SELECT reaction_key, MAX(id) AS max_id
                FROM reaction_snapshots
                WHERE chat_id = ? AND message_id = ?
                GROUP BY reaction_key
            ) last ON last.max_id = s.id
            ORDER BY s.total_count DESC, s.reaction_key ASC
            """,
            (chat_id, message_id),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def list_recent_reaction_snapshots(
    database_path: str,
    limit: int = 500,
) -> list[dict]:
    """Retorna snapshots recentes para comandos agregados em DM."""
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT s.*, w.channel_title, w.channel_username, w.post_link, w.source
            FROM reaction_snapshots s
            LEFT JOIN reaction_watches w
              ON w.chat_id = s.chat_id AND w.message_id = s.message_id
            ORDER BY s.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def reaction_event_count(database_path: str, chat_id: int, message_id: int) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            SELECT COUNT(*)
            FROM reaction_events
            WHERE chat_id = ? AND message_id = ?
            """,
            (chat_id, message_id),
        )
        row = await cursor.fetchone()
        return int(row[0] or 0)


async def record_reaction_post_metadata(
    database_path: str,
    *,
    chat_id: int,
    message_id: int,
    channel_username: str | None = None,
    channel_title: str | None = None,
    post_link: str | None = None,
    text_preview: str | None = None,
    signature: str | None = None,
    content_type: str | None = None,
    dump_can_view_list: bool | None = None,
    dump_recent_peers_count: int | None = None,
    dump_top_peers_count: int | None = None,
    dump_paid_reactors_count: int | None = None,
    dump_are_tags: bool | None = None,
    dump_reactions: Any = None,
    dump_total_reactions: int | None = None,
    dump_reaction_kinds: int | None = None,
    dump_dominant_reaction: str | None = None,
    dump_data_mode: str | None = None,
    raw_count_values: Any = None,
    source: str = "dump",
) -> dict:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO reaction_post_metadata (
                chat_id, message_id, channel_username, channel_title, post_link,
                text_preview, signature, content_type,
                dump_can_view_list, dump_recent_peers_count, dump_top_peers_count,
                dump_paid_reactors_count, dump_are_tags, dump_reactions_json,
                dump_total_reactions, dump_reaction_kinds, dump_dominant_reaction,
                dump_data_mode, raw_count_values_json, source, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                chat_id,
                message_id,
                channel_username,
                channel_title,
                post_link,
                text_preview,
                signature,
                content_type,
                None if dump_can_view_list is None else int(bool(dump_can_view_list)),
                dump_recent_peers_count,
                dump_top_peers_count,
                dump_paid_reactors_count,
                None if dump_are_tags is None else int(bool(dump_are_tags)),
                _json_dumps(dump_reactions),
                dump_total_reactions,
                dump_reaction_kinds,
                dump_dominant_reaction,
                dump_data_mode,
                _json_dumps(raw_count_values),
                source,
            ),
        )
        await db.commit()
        cursor = await db.execute(
            """
            SELECT *
            FROM reaction_post_metadata
            WHERE rowid = last_insert_rowid()
            """
        )
        row = await cursor.fetchone()
        return dict(row)


async def get_latest_reaction_post_metadata(
    database_path: str,
    chat_id: int,
    message_id: int,
) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT *
            FROM reaction_post_metadata
            WHERE chat_id = ? AND message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, message_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def find_reaction_posts_by_message_id(
    database_path: str,
    message_id: int,
    limit: int = 8,
) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT chat_id, message_id, channel_title, channel_username, post_link, source, last_event_at, created_at
            FROM reaction_watches
            WHERE message_id = ?
            ORDER BY COALESCE(last_event_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (message_id, limit),
        )
        rows = await cursor.fetchall()
        if rows:
            return [dict(row) for row in rows]

        cursor = await db.execute(
            """
            SELECT s.chat_id, s.message_id, w.channel_title, w.channel_username, w.post_link,
                   COALESCE(w.source, s.data_mode) AS source, s.captured_at AS last_event_at, s.captured_at AS created_at
            FROM reaction_snapshots s
            LEFT JOIN reaction_watches w
              ON w.chat_id = s.chat_id AND w.message_id = s.message_id
            WHERE s.message_id = ?
            GROUP BY s.chat_id, s.message_id
            ORDER BY MAX(s.id) DESC
            LIMIT ?
            """,
            (message_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
