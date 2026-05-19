import aiosqlite


async def save_item(
    database_path: str,
    *,
    canonical_url: str,
    title: str | None,
    source_name: str | None,
    text_hash: str | None,
    image_url: str | None = None,
    extracted_text: str | None = None,
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO articles
                (canonical_url, title, source_name, image_url, extracted_text, text_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (canonical_url, title, source_name, image_url, extracted_text, text_hash),
        )
        await db.commit()

        if cursor.lastrowid:
            return int(cursor.lastrowid)

        await db.execute(
            """
            UPDATE articles
            SET title = COALESCE(?, title),
                source_name = COALESCE(?, source_name),
                image_url = COALESCE(?, image_url),
                extracted_text = COALESCE(?, extracted_text),
                text_hash = COALESCE(?, text_hash)
            WHERE canonical_url = ?
            """,
            (title, source_name, image_url, extracted_text, text_hash, canonical_url),
        )
        await db.commit()

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


async def find_duplicate_item(
    database_path: str,
    *,
    canonical_url: str,
    text_hash: str | None,
) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        if text_hash:
            cursor = await db.execute(
                """
                SELECT id, canonical_url, title, source_name
                FROM articles
                WHERE canonical_url = ? OR text_hash = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (canonical_url, text_hash),
            )
        else:
            cursor = await db.execute(
                """
                SELECT id, canonical_url, title, source_name
                FROM articles
                WHERE canonical_url = ?
                LIMIT 1
                """,
                (canonical_url,),
            )
        row = await cursor.fetchone()
        return dict(row) if row else None
