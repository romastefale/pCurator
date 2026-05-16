from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ PUB", callback_data="post:publish", style="success"),
                InlineKeyboardButton(text="✏️ EDT", callback_data="post:edit", style="primary"),
            ],
            [
                InlineKeyboardButton(text="🖼 IMG", callback_data="post:image", style="primary"),
                InlineKeyboardButton(text="🚫 IGN", callback_data="post:ignore", style="danger"),
            ],
        ]
    )


def channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📘 C1", callback_data="channel:c1", style="primary"),
                InlineKeyboardButton(text="📰 C2", callback_data="channel:c2", style="primary"),
            ],
            [InlineKeyboardButton(text="🚫 IGN", callback_data="channel:ignore", style="danger")],
        ]
    )
