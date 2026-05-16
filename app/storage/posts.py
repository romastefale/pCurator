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


async def update_post_caption(database_path: str, post_id: int, caption_html: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET caption_html = ? WHERE id = ?",
            (caption_html, post_id),
        )
        await db.commit()


async def update_post_status(database_path: str, post_id: int, status: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id),
        )
        await db.commit()


async def get_post(database_path: str, post_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM posts WHERE id = ?",
            (post_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
