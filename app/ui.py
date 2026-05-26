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


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirmar envio", callback_data="post:confirm")],
            [
                InlineKeyboardButton(text="✏️ Editar texto", callback_data="post:edit"),
                InlineKeyboardButton(text="🚫 Cancelar", callback_data="post:cancel_confirm"),
            ],
        ]
    )


def channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📘 Canal 1", callback_data="channel:c1"),
                InlineKeyboardButton(text="📰 Canal 2", callback_data="channel:c2"),
            ],
            [InlineKeyboardButton(text="🚫 Ignorar", callback_data="channel:ignore")],
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
