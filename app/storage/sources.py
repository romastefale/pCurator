import aiosqlite


async def list_sources(database_path: str, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, name, scope, quality_score, is_blocked
            FROM sources
            ORDER BY quality_score DESC, name ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def upsert_source(
    database_path: str,
    *,
    name: str,
    url: str | None = None,
    scope: str = "global",
    quality_score: int = 70,
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO sources (name, url, scope, quality_score)
            VALUES (?, ?, ?, ?)
            """,
            (name, url, scope, quality_score),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def update_source_score(database_path: str, source_id: int, quality_score: int) -> None:
    quality_score = max(0, min(100, quality_score))
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE sources SET quality_score = ? WHERE id = ?",
            (quality_score, source_id),
        )
        await db.commit()


async def set_source_blocked(database_path: str, source_id: int, is_blocked: bool) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE sources SET is_blocked = ? WHERE id = ?",
            (1 if is_blocked else 0, source_id),
        )
        await db.commit()
