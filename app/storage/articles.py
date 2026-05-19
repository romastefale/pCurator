import aiosqlite


async def get_article(article_id: int, database_path: str) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM articles WHERE id = ?",
            (article_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_article_for_post(database_path: str, post_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT articles.*
            FROM articles
            JOIN posts ON posts.article_id = articles.id
            WHERE posts.id = ?
            """,
            (post_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
