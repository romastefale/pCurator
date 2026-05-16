import json
from typing import Any

import aiosqlite


async def log_event(
    database_path: str,
    *,
    event_type: str,
    channel_slug: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO editorial_events
                (channel_slug, event_type, payload)
            VALUES (?, ?, ?)
            """,
            (channel_slug, event_type, json.dumps(payload or {}, ensure_ascii=False)),
        )
        await db.commit()
        return int(cursor.lastrowid)
