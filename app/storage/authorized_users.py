import aiosqlite


async def add_authorized_user(
    database_path: str,
    *,
    user_id: int,
    name: str | None,
    added_by: int,
) -> None:
    """Autoriza um co-autor (ou reativa um revogado) pelo Telegram user_id."""
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            INSERT INTO authorized_users (user_id, name, added_by, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                added_by = excluded.added_by,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, name, added_by),
        )
        await db.commit()


async def revoke_authorized_user(database_path: str, user_id: int) -> bool:
    """Revoga um co-autor (is_active=0). Retorna True se havia um ativo."""
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "UPDATE authorized_users SET is_active = 0, updated_at = CURRENT_TIMESTAMP "
            "WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def list_authorized_users(database_path: str, only_active: bool = True) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT user_id, name, added_by, is_active, created_at FROM authorized_users"
        if only_active:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at"
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def is_authorized(database_path: str, user_id: int) -> bool:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT 1 FROM authorized_users WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        return await cursor.fetchone() is not None
