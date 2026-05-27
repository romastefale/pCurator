from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite

_KEY_PREFIX = "discovery_count:"
_CALLS_KEY_PREFIX = "gnews_calls:"


def _today_key(timezone: str, prefix: str = _KEY_PREFIX) -> str:
    now = datetime.now(ZoneInfo(timezone))
    return f"{prefix}{now.strftime('%Y-%m-%d')}"


async def _get_count(database_path: str, key: str) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def _increment_count(database_path: str, key: str) -> int:
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


async def get_today_count(database_path: str, timezone: str) -> int:
    """Quantas notícias novas (artigos virando rascunho) já entregues hoje."""
    return await _get_count(database_path, _today_key(timezone))


async def increment_today_count(database_path: str, timezone: str) -> int:
    return await _increment_count(database_path, _today_key(timezone))


async def get_calls_today(database_path: str, timezone: str) -> int:
    """Quantas chamadas HTTP ao GNews foram feitas hoje (auto + manual)."""
    return await _get_count(database_path, _today_key(timezone, _CALLS_KEY_PREFIX))


async def increment_calls_today(database_path: str, timezone: str) -> int:
    return await _increment_count(database_path, _today_key(timezone, _CALLS_KEY_PREFIX))
