import aiosqlite


async def save_post(
    database_path: str,
    *,
    article_id: int | None,
    channel_slug: str,
    caption_html: str,
    image_url: str | None = None,
    status: str = "draft",
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO posts
                (article_id, channel_slug, caption_html, image_url, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (article_id, channel_slug, caption_html, image_url, status),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def update_post_channel_slug(database_path: str, post_id: int, channel_slug: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET channel_slug = ? WHERE id = ?",
            (channel_slug, post_id),
        )
        await db.commit()


async def update_post_caption(database_path: str, post_id: int, caption_html: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET caption_html = ? WHERE id = ?",
            (caption_html, post_id),
        )
        await db.commit()


async def update_post_image(database_path: str, post_id: int, image_url: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET image_url = ? WHERE id = ?",
            (image_url, post_id),
        )
        await db.commit()


async def update_post_status(database_path: str, post_id: int, status: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id),
        )
        await db.commit()


async def try_lock_post_for_publish(database_path: str, post_id: int) -> bool:
    """Transição atômica draft -> publishing. Retorna True se ganhou a trava."""
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "UPDATE posts SET status = 'publishing' WHERE id = ? AND status = 'draft'",
            (post_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_post(database_path: str, post_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM posts WHERE id = ?",
            (post_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def count_posts_by_status(database_path: str) -> dict[str, int]:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM posts GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}


async def reopen_failed_post(database_path: str, post_id: int) -> bool:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "UPDATE posts SET status = 'draft' WHERE id = ? AND status = 'failed'",
            (post_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def last_published_at(database_path: str) -> str | None:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT created_at FROM posts WHERE status = 'published' ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def list_recent_posts(database_path: str, limit: int = 5) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, channel_slug, status, image_url, created_at
            FROM posts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
