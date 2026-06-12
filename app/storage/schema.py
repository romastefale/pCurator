SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    chat_id INTEGER,
    title TEXT NOT NULL,
    username TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS authorized_users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    added_by INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    scope TEXT NOT NULL DEFAULT 'global',
    quality_score INTEGER NOT NULL DEFAULT 70,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT UNIQUE,
    title TEXT,
    source_name TEXT,
    published_at TEXT,
    image_url TEXT,
    extracted_text TEXT,
    text_hash TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    auto_drafted INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER,
    channel_slug TEXT NOT NULL,
    caption_html TEXT NOT NULL,
    image_url TEXT,
    image_urls TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    published_chat_id INTEGER,
    published_message_ids TEXT,
    published_photo_message_ids TEXT,
    published_text_message_id INTEGER,
    published_caption_on_photo INTEGER NOT NULL DEFAULT 0,
    published_by INTEGER,
    published_by_name TEXT,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(article_id) REFERENCES articles(id)
);

CREATE TABLE IF NOT EXISTS editorial_sessions (
    user_id INTEGER PRIMARY KEY,
    active_post_id INTEGER,
    active_channel_slug TEXT,
    mode TEXT,
    last_preview_message_ids TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learned_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_slug TEXT,
    rule_type TEXT NOT NULL,
    rule_text TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS editorial_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_slug TEXT,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
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
);

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
);

CREATE INDEX IF NOT EXISTS idx_reaction_watches_post
ON reaction_watches(chat_id, message_id);

CREATE INDEX IF NOT EXISTS idx_reaction_events_post
ON reaction_events(chat_id, message_id, id);

"""
