from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite

_KEY_PREFIX = "discovery_count:"


def _today_key(timezone: str) -> str:
    now = datetime.now(ZoneInfo(timezone))
    return f"{_KEY_PREFIX}{now.strftime('%Y-%m-%d')}"


async def get_today_count(database_path: str, timezone: str) -> int:
    key = _today_key(timezone)
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def increment_today_count(database_path: str, timezone: str) -> int:
    key = _today_key(timezone)
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        current = int(row[0]) if row else 0
        new_value = current + 1
        await db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, str(new_value)),
        )
        await db.commit()
        return new_value
