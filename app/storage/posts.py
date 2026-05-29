import json

import aiosqlite


def post_image_refs(post: dict) -> list[str]:
    """Lista de file_ids/URLs de imagem do post (1 a 4).

    Prefere a coluna `image_urls` (JSON). Cai pra `image_url` (legado de 1 foto)
    se a lista estiver vazia/ausente. Retorna [] se não houver imagem."""
    raw = post.get("image_urls")
    if raw:
        try:
            refs = json.loads(raw)
            if isinstance(refs, list):
                cleaned = [r for r in refs if r]
                if cleaned:
                    return cleaned
        except (json.JSONDecodeError, TypeError):
            pass
    single = post.get("image_url")
    return [single] if single else []


async def save_post(
    database_path: str,
    *,
    article_id: int | None,
    channel_slug: str,
    caption_html: str,
    image_url: str | None = None,
    status: str = "draft",
) -> int:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO posts
                (article_id, channel_slug, caption_html, image_url, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (article_id, channel_slug, caption_html, image_url, status),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def update_post_channel_slug(database_path: str, post_id: int, channel_slug: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET channel_slug = ? WHERE id = ?",
            (channel_slug, post_id),
        )
        await db.commit()


async def update_post_caption(database_path: str, post_id: int, caption_html: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET caption_html = ? WHERE id = ?",
            (caption_html, post_id),
        )
        await db.commit()


async def update_post_image(database_path: str, post_id: int, image_url: str | None) -> None:
    """Define uma única imagem (limpa a lista de álbum)."""
    image_urls = json.dumps([image_url]) if image_url else None
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET image_url = ?, image_urls = ? WHERE id = ?",
            (image_url, image_urls, post_id),
        )
        await db.commit()


async def update_post_images(database_path: str, post_id: int, image_refs: list[str]) -> None:
    """Define de 1 a 4 imagens (álbum). `image_url` guarda a primeira (legado)."""
    image_refs = [r for r in image_refs if r][:4]
    first = image_refs[0] if image_refs else None
    image_urls = json.dumps(image_refs) if image_refs else None
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET image_url = ?, image_urls = ? WHERE id = ?",
            (first, image_urls, post_id),
        )
        await db.commit()


def _parse_int_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[int] = []
    for x in data:
        try:
            out.append(int(x))
        except (ValueError, TypeError):
            continue
    return out


def published_message_ids(post: dict) -> list[int]:
    """Todos os message_ids da publicação no canal (pra apagar)."""
    return _parse_int_list(post.get("published_message_ids"))


def published_photo_ids(post: dict) -> list[int]:
    """Só os message_ids das fotos no canal, na ordem (pra trocar imagem)."""
    return _parse_int_list(post.get("published_photo_message_ids"))


async def set_post_published(
    database_path: str,
    post_id: int,
    *,
    chat_id: int,
    message_ids: list[int],
    photo_message_ids: list[int],
    text_message_id: int | None,
    caption_on_photo: bool,
    published_by: int | None,
    published_by_name: str | None,
) -> None:
    """Marca o post como publicado e grava onde foi parar no canal, pra permitir
    editar/apagar depois (status -> 'published', + published_at)."""
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            UPDATE posts SET
                status = 'published',
                published_chat_id = ?,
                published_message_ids = ?,
                published_photo_message_ids = ?,
                published_text_message_id = ?,
                published_caption_on_photo = ?,
                published_by = ?,
                published_by_name = ?,
                published_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                chat_id,
                json.dumps(message_ids),
                json.dumps(photo_message_ids),
                text_message_id,
                1 if caption_on_photo else 0,
                published_by,
                published_by_name,
                post_id,
            ),
        )
        await db.commit()


async def update_post_status(database_path: str, post_id: int, status: str) -> None:
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "UPDATE posts SET status = ? WHERE id = ?",
            (status, post_id),
        )
        await db.commit()


async def try_lock_post_for_publish(database_path: str, post_id: int) -> bool:
    """Transição atômica draft -> publishing. Retorna True se ganhou a trava."""
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "UPDATE posts SET status = 'publishing' WHERE id = ? AND status = 'draft'",
            (post_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def get_post(database_path: str, post_id: int) -> dict | None:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM posts WHERE id = ?",
            (post_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def count_posts_by_status(database_path: str) -> dict[str, int]:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM posts GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {row[0]: int(row[1]) for row in rows}


async def reopen_failed_post(database_path: str, post_id: int) -> bool:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "UPDATE posts SET status = 'draft' WHERE id = ? AND status = 'failed'",
            (post_id,),
        )
        await db.commit()
        return cursor.rowcount == 1


async def last_published_at(database_path: str) -> str | None:
    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT created_at FROM posts WHERE status = 'published' ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def list_recent_posts(database_path: str, limit: int = 5) -> list[dict]:
    async with aiosqlite.connect(database_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, channel_slug, status, image_url, created_at
            FROM posts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
