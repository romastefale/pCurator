import aiosqlite


async def upsert_channel(
    database_path: str,
    *,
    chat_id: int,
    title: str,
    username: str | None = None,
) -> None:
    """Insere ou atualiza um canal pela identidade chat_id. Reativa
    (is_enabled=1) se estava desabilitado. slug = str(chat_id) (a coluna
    legada slug é NOT NULL UNIQUE; usamos o próprio chat_id pra satisfazer)."""
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO channels (slug, chat_id, title, username, is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username,
                is_enabled = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(chat_id), chat_id, title, username),
        )
        await db.commit()


async def set_channel_enabled(database_path: str, chat_id: int, enabled: bool) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE channels SET is_enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?",
            (1 if enabled else 0, chat_id),
        )
        await db.commit()


async def list_channels(database_path: str, only_enabled: bool = True) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT chat_id, title, username, is_enabled FROM channels WHERE chat_id IS NOT NULL"
        if only_enabled:
            query += " AND is_enabled = 1"
        query += " ORDER BY title COLLATE NOCASE"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_channel(database_path: str, chat_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT chat_id, title, username, is_enabled FROM channels WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
