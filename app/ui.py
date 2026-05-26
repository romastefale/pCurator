from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def review_keyboard(can_publish: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_publish:
        rows.append([InlineKeyboardButton(text="✅ Publicar", callback_data="post:publish")])
    rows.append(
        [
            InlineKeyboardButton(text="✏️ Editar texto", callback_data="post:edit"),
            InlineKeyboardButton(text="🖼 Trocar imagem", callback_data="post:image"),
        ]
    )
    rows.append([InlineKeyboardButton(text="🚫 Ignorar", callback_data="post:ignore")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(post_id: int, destination_slug: str) -> InlineKeyboardMarkup:
    """Confirma envio para um destino específico. post_id e destino vão no
    callback_data para evitar publicação no canal errado por estado obsoleto."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirmar envio",
                    callback_data=f"post:confirm:{post_id}:{destination_slug}",
                )
            ],
            [
                InlineKeyboardButton(text="✏️ Editar texto", callback_data="post:edit"),
                InlineKeyboardButton(text="🚫 Cancelar", callback_data="post:cancel_confirm"),
            ],
        ]
    )


def channel_keyboard() -> InlineKeyboardMarkup:
    """Escolha de TOM editorial (passo 2). Gera a prévia com o estilo de cada canal."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎨 Tom do Canal 1", callback_data="channel:c1"),
                InlineKeyboardButton(text="🎨 Tom do Canal 2", callback_data="channel:c2"),
            ],
            [InlineKeyboardButton(text="🚫 Ignorar", callback_data="channel:ignore")],
        ]
    )


def destination_keyboard() -> InlineKeyboardMarkup:
    """Escolha do CANAL DE DESTINO (passo 5), após revisão/edição."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📘 Publicar no Canal 1", callback_data="dest:c1"),
                InlineKeyboardButton(text="📰 Publicar no Canal 2", callback_data="dest:c2"),
            ],
            [InlineKeyboardButton(text="↩️ Voltar para revisão", callback_data="dest:back")],
        ]
    )


def duplicate_keyboard(article_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Gerar novamente", callback_data=f"duplicate:regenerate:{article_id}"),
                InlineKeyboardButton(text="🚫 Ignorar", callback_data="duplicate:ignore"),
            ]
        ]
    )


def channel_label(channel_slug: str | None) -> str:
    if channel_slug == "c1":
        return "📘 Canal 1"
    if channel_slug == "c2":
        return "📰 Canal 2"
    return "canal não definido"
