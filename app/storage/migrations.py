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

        session_columns = await _columns(db, "editorial_sessions")
        if "active_channel_slug" not in session_columns:
            await db.execute("ALTER TABLE editorial_sessions ADD COLUMN active_channel_slug TEXT")

        await db.commit()
