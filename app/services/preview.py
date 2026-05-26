from app.services.publisher import publish_post


async def send_post_preview(bot, chat_id: int, post: dict) -> None:
    """Pré-visualização é renderizada exatamente igual à publicação real."""
    await publish_post(bot, chat_id, post)
