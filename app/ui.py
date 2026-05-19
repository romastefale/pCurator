from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _button(*, text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    try:
        return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)
    except TypeError:
        return InlineKeyboardButton(text=text, callback_data=callback_data)


def review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(text="✅ PUB", callback_data="post:publish", style="success"),
                _button(text="✏️ EDT", callback_data="post:edit", style="primary"),
            ],
            [
                _button(text="🖼 IMG", callback_data="post:image", style="primary"),
                _button(text="🚫 IGN", callback_data="post:ignore", style="danger"),
            ],
        ]
    )


def channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(text="📘 C1", callback_data="channel:c1", style="primary"),
                _button(text="📰 C2", callback_data="channel:c2", style="primary"),
            ],
            [_button(text="🚫 IGN", callback_data="channel:ignore", style="danger")],
        ]
    )
