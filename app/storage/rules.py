import aiosqlite


async def add_rule(
    database_path: str,
    *,
    rule_text: str,
    rule_type: str = "general",
    channel_slug: str | None = None,
    weight: int = 1,
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO learned_rules
                (channel_slug, rule_type, rule_text, weight)
            VALUES (?, ?, ?, ?)
            """,
            (channel_slug, rule_type, rule_text, weight),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def list_rules(database_path: str, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, channel_slug, rule_type, rule_text, weight, is_enabled
            FROM learned_rules
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
