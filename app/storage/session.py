import aiosqlite


async def set_active_post(
    database_path: str,
    *,
    user_id: int,
    post_id: int | None,
    mode: str | None = None,
) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO editorial_sessions (user_id, active_post_id, mode, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                active_post_id = excluded.active_post_id,
                mode = excluded.mode,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, post_id, mode),
        )
        await db.commit()


async def get_active_post(database_path: str, user_id: int) -> tuple[int | None, str | None]:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT active_post_id, mode FROM editorial_sessions WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None, None
        return row[0], row[1]
