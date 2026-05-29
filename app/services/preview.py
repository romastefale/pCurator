from app.services.publisher import publish_post


async def send_post_preview(bot, chat_id: int, post: dict) -> list[int]:
    """Pré-visualização é renderizada exatamente igual à publicação real.
    Retorna os message_ids enviados para que o chamador possa rastrear/deletar."""
    result = await publish_post(bot, chat_id, post)
    return result.message_ids
