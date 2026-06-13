import aiosqlite


async def _columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def apply_migrations(database_path: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        article_columns = await _columns(db, "articles")
        if "image_url" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN image_url TEXT")
        if "extracted_text" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN extracted_text TEXT")
        if "auto_drafted" not in article_columns:
            await db.execute(
                "ALTER TABLE articles ADD COLUMN auto_drafted INTEGER NOT NULL DEFAULT 0"
            )
        if "discovered_at" not in article_columns:
            await db.execute("ALTER TABLE articles ADD COLUMN discovered_at TEXT")

        post_columns = await _columns(db, "posts")
        if "image_urls" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN image_urls TEXT")
        if "published_chat_id" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_chat_id INTEGER")
        if "published_message_ids" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_message_ids TEXT")
        if "published_photo_message_ids" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_photo_message_ids TEXT")
        if "published_text_message_id" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_text_message_id INTEGER")
        if "published_caption_on_photo" not in post_columns:
            await db.execute(
                "ALTER TABLE posts ADD COLUMN published_caption_on_photo INTEGER NOT NULL DEFAULT 0"
            )
        if "published_by" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_by INTEGER")
        if "published_by_name" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_by_name TEXT")
        if "published_at" not in post_columns:
            await db.execute("ALTER TABLE posts ADD COLUMN published_at TEXT")

        session_columns = await _columns(db, "editorial_sessions")
        if "active_channel_slug" not in session_columns:
            await db.execute("ALTER TABLE editorial_sessions ADD COLUMN active_channel_slug TEXT")
        if "last_preview_message_ids" not in session_columns:
            await db.execute("ALTER TABLE editorial_sessions ADD COLUMN last_preview_message_ids TEXT")

        channel_columns = await _columns(db, "channels")
        if "username" not in channel_columns:
            await db.execute("ALTER TABLE channels ADD COLUMN username TEXT")
        if "updated_at" not in channel_columns:
            await db.execute("ALTER TABLE channels ADD COLUMN updated_at TEXT")
        # Desduplica por chat_id antes do índice UNIQUE: mantém o rowid mais alto
        # (linha mais recente) por chat_id, senão o CREATE INDEX falharia em bases
        # antigas com duplicatas e travaria o startup.
        await db.execute(
            "DELETE FROM channels WHERE rowid NOT IN "
            "(SELECT MAX(rowid) FROM channels GROUP BY chat_id)"
        )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_chat_id ON channels(chat_id)"
        )


        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_username TEXT,
                channel_title TEXT,
                post_link TEXT NOT NULL,
                created_by INTEGER,
                source TEXT NOT NULL DEFAULT 'manual',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_event_at TEXT,
                UNIQUE(chat_id, message_id)
            )
            """
        )
        reaction_watch_columns = await _columns(db, "reaction_watches")
        if "source" not in reaction_watch_columns:
            await db.execute(
                "ALTER TABLE reaction_watches ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
            )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor_user_id INTEGER,
                actor_username TEXT,
                actor_name TEXT,
                actor_chat_id INTEGER,
                actor_chat_title TEXT,
                old_reaction_json TEXT,
                new_reaction_json TEXT,
                reactions_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_reaction_watches_post ON reaction_watches(chat_id, message_id)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                reaction_key TEXT NOT NULL,
                reaction_type TEXT NOT NULL,
                total_count INTEGER NOT NULL,
                previous_count INTEGER,
                delta_count INTEGER,
                total_reactions INTEGER,
                reaction_kinds INTEGER,
                dominant_reaction TEXT,
                data_mode TEXT NOT NULL DEFAULT 'aggregate_anonymous',
                telegram_date TEXT,
                captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_reaction_snapshots_post ON reaction_snapshots(chat_id, message_id, id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_reaction_snapshots_key ON reaction_snapshots(chat_id, message_id, reaction_key, id)"
        )

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_reaction_events_post ON reaction_events(chat_id, message_id, id)"
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_post_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_username TEXT,
                channel_title TEXT,
                post_link TEXT,
                text_preview TEXT,
                signature TEXT,
                content_type TEXT,
                dump_can_view_list INTEGER,
                dump_recent_peers_count INTEGER,
                dump_top_peers_count INTEGER,
                dump_paid_reactors_count INTEGER,
                dump_are_tags INTEGER,
                dump_reactions_json TEXT,
                dump_total_reactions INTEGER,
                dump_reaction_kinds INTEGER,
                dump_dominant_reaction TEXT,
                dump_data_mode TEXT,
                raw_count_values_json TEXT,
                source TEXT NOT NULL DEFAULT 'dump',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        reaction_post_metadata_columns = await _columns(db, "reaction_post_metadata")
        for column_name, column_type in {
            "possible_view_count": "INTEGER",
            "possible_forward_count": "INTEGER",
            "raw_attribute_counts_json": "TEXT",
            "view_confidence": "TEXT",
            "forward_confidence": "TEXT",
            "stable_id": "INTEGER",
            "stable_version": "INTEGER",
            "source_format": "TEXT",
            "dump_hash": "TEXT",
        }.items():
            if column_name not in reaction_post_metadata_columns:
                await db.execute(f"ALTER TABLE reaction_post_metadata ADD COLUMN {column_name} {column_type}")

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_reaction_post_metadata_post ON reaction_post_metadata(chat_id, message_id, id)"
        )
        await db.execute(
            """
            DELETE FROM reaction_post_metadata
            WHERE dump_hash IS NOT NULL
              AND rowid NOT IN (
                  SELECT MIN(rowid)
                  FROM reaction_post_metadata
                  WHERE dump_hash IS NOT NULL
                  GROUP BY chat_id, message_id, source, dump_hash
              )
            """
        )
        await db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_reaction_post_metadata_dump_hash
            ON reaction_post_metadata(chat_id, message_id, source, dump_hash)
            WHERE dump_hash IS NOT NULL
            """
        )

        await db.commit()
