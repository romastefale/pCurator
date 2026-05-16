import aiosqlite


async def save_item(
    database_path: str,
    *,
    canonical_url: str,
    title: str | None,
    source_name: str | None,
    text_hash: str | None,
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO articles
                (canonical_url, title, source_name, text_hash)
            VALUES (?, ?, ?, ?)
            """,
            (canonical_url, title, source_name, text_hash),
        )
        await db.commit()

        if cursor.lastrowid:
            return int(cursor.lastrowid)

        existing = await db.execute(
            "SELECT id FROM articles WHERE canonical_url = ?",
            (canonical_url,),
        )
        row = await existing.fetchone()
        return int(row[0])


async def item_exists(database_path: str, canonical_url: str) -> bool:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT 1 FROM articles WHERE canonical_url = ? LIMIT 1",
            (canonical_url,),
        )
        return await cursor.fetchone() is not None
