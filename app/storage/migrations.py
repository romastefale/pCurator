import aiosqlite


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def apply_migrations(database_path: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        article_columns = await _columns(db, "articles")
        if "image_url" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN image_url TEXT")
        if "extracted_text" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN extracted_text TEXT")
        if "auto_drafted" not in article_columns:
            await db.execute(
                "ALTER TABLE articles ADD COLUMN auto_drafted INTEGER NOT NULL DEFAULT 0"
            )
        if "discovered_at" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN discovered_at TEXT")

        session_columns = await _columns(db, "editorial_sessions")
        if "active_channel_slug" not in session_columns:
            await db.execute("ALTER TABLE editorial_sessions ADD COLUMN active_channel_slug TEXT")
        if "last_preview_message_ids" not in session_columns:
            await db.execute("ALTER TABLE editorial_sessions ADD COLUMN last_preview_message_ids TEXT")

        channel_columns = await _columns(db, "channels")
        if "username" not in channel_columns:
            await db.execute("ALTER TABLE channels ADD COLUMN username TEXT")
        if "updated_at" not in channel_columns:
            await db.execute("ALTER TABLE channels ADD COLUMN updated_at TEXT")
        # Desduplica por chat_id antes do índice UNIQUE: mantém o rowid mais alto
        # (linha mais recente) por chat_id, senão o CREATE INDEX falharia em bases
        # antigas com duplicatas e travaria o startup.
        await db.execute(
            "DELETE FROM channels WHERE rowid NOT IN "
            "(SELECT MAX(rowid) FROM channels GROUP BY chat_id)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_chat_id ON channels(chat_id)"
        )

        await db.commit()
