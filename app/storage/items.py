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
    auto_drafted: bool = False,
) -> int:
    item_id, _was_new = await save_item_with_flag(
        database_path,
        canonical_url=canonical_url,
        title=title,
        source_name=source_name,
        text_hash=text_hash,
        image_url=image_url,
        extracted_text=extracted_text,
        auto_drafted=auto_drafted,
    )
    return item_id


async def save_item_with_flag(
    database_path: str,
    *,
    canonical_url: str,
    title: str | None,
    source_name: str | None,
    text_hash: str | None,
    image_url: str | None = None,
    extracted_text: str | None = None,
    auto_drafted: bool = False,
) -> tuple[int, bool]:
    """Como save_item, mas devolve também was_new=True só se a row foi
    realmente inserida agora (lastrowid != 0). Em corrida com outro insert
    concorrente, was_new=False — o auto-discovery usa isso pra abortar
    e não criar post duplicado pro mesmo artigo."""
    auto_flag = 1 if auto_drafted else 0
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO articles
                (canonical_url, title, source_name, image_url, extracted_text, text_hash,
                 auto_drafted, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (canonical_url, title, source_name, image_url, extracted_text, text_hash,
             auto_flag, auto_flag),
        )
        await db.commit()

        if cursor.lastrowid:
            return int(cursor.lastrowid), True

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
        return int(row[0]), False


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
