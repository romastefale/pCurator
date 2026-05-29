"""Teclados inline do bot.

CONVENÇÃO DE TEXTO DE BOTÃO (não regredir):
  - Máx. ~12 caracteres por botão quando houver 2 botões na mesma linha
    (telas estreitas truncam ou quebram em 2 linhas, ficando ilegível).
  - 1 emoji + 1–2 palavras curtas. Sem verbo redundante com a mensagem acima
    (ex.: se a mensagem diz "Para qual canal publicar?", o botão é só
    "📘 Canal 1", não "📘 Publicar no Canal 1").
  - Pares lado-a-lado devem ter estrutura paralela (mesma contagem de
    palavras, mesmo padrão de emoji).
  - Contexto/ação fica na mensagem acima do teclado; o botão é o objeto.
"""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# CONVENÇÃO SEMÂNTICA DE COR (ButtonStyle, Bot API 9.4+):
#   - SUCCESS (🟢): raro e sagrado — só "Publicar" e "Confirmar envio".
#   - DANGER  (🔴): qualquer ação que descarta/cancela/marca como ignored.
#   - PRIMARY (🔵): seleção entre opções equivalentes (Canal 1/2, trilhas).
#   - sem style: navegação fraca (Voltar) e ações neutras — deixa a hierarquia
#     visual respirar (não pintar tudo é tão importante quanto pintar).


def _truncate_label(text: str, limit: int = 60) -> str:
    """Trunca texto de botão inline (limite do Telegram é 64 chars) com reticências."""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def review_keyboard(with_next: bool = False) -> InlineKeyboardMarkup:
    """Teclado de revisão — sempre permite publicar. O curador humano decide.

    with_next=True acrescenta '⏭ Próxima notícia' (usado no fluxo /buscar
    pra descartar a atual e pedir outra na mesma trilha)."""
    rows = [
        [InlineKeyboardButton(
            text="✅ Publicar",
            callback_data="post:publish",
            style=ButtonStyle.SUCCESS,
        )],
        [
            InlineKeyboardButton(text="✏️ Editar texto", callback_data="post:edit"),
            InlineKeyboardButton(text="🖼 Trocar imagem", callback_data="post:image"),
        ],
        [
            InlineKeyboardButton(
                text="🚫 Ignorar",
                callback_data="post:ignore",
                style=ButtonStyle.DANGER,
            ),
        ],
    ]
    if with_next:
        rows.append([
            InlineKeyboardButton(
                text="⏭ Próxima notícia (descartar esta)",
                callback_data="post:next",
                style=ButtonStyle.DANGER,
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def discover_topic_keyboard() -> InlineKeyboardMarkup:
    """Escolha de trilha pro comando /buscar."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💻 Tecnologia", callback_data="discover:tech", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="🎬 Cinema", callback_data="discover:cinema", style=ButtonStyle.PRIMARY),
            ],
            [
                InlineKeyboardButton(text="📺 Séries", callback_data="discover:series", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="🌟 Pop", callback_data="discover:pop", style=ButtonStyle.PRIMARY),
            ],
            [
                InlineKeyboardButton(text="📰 Atualidades", callback_data="discover:atualidades", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="🔬 Ciência", callback_data="discover:ciencia", style=ButtonStyle.PRIMARY),
            ],
            [
                InlineKeyboardButton(text="🎮 Geek", callback_data="discover:geek", style=ButtonStyle.PRIMARY),
            ],
            [InlineKeyboardButton(text="🚫 Cancelar", callback_data="discover:cancel", style=ButtonStyle.DANGER)],
        ]
    )


def confirm_keyboard(post_id: int, destination_slug: str) -> InlineKeyboardMarkup:
    """Confirma envio para um destino específico. post_id e destino vão no
    callback_data para evitar publicação no canal errado por estado obsoleto."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirmar envio",
                    callback_data=f"post:confirm:{post_id}:{destination_slug}",
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(text="✏️ Editar texto", callback_data="post:edit"),
                InlineKeyboardButton(
                    text="🚫 Cancelar",
                    callback_data="post:cancel_confirm",
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


def destination_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    """Escolha do CANAL DE DESTINO (após revisão/edição).

    Um botão por canal, exibindo o NOME REAL do canal (texto de botão não é
    HTML, então o título cru é seguro aqui). O callback_data carrega o chat_id
    pra rotear o envio sem depender de estado obsoleto da sessão."""
    rows = [
        [
            InlineKeyboardButton(
                text=_truncate_label(ch["title"]),
                callback_data=f"dest:{ch['chat_id']}",
                style=ButtonStyle.PRIMARY,
            )
        ]
        for ch in channels
    ]
    rows.append([InlineKeyboardButton(text="↩️ Voltar para revisão", callback_data="dest:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def published_actions_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Botões da notificação de publicação (DM do dono): apagar ou editar a
    publicação já no ar. Owner-only nos handlers."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Apagar",
                    callback_data=f"pub:del:{post_id}",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="✏️ Editar", callback_data=f"pub:edit:{post_id}"),
            ]
        ]
    )


def published_delete_confirm_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Confirmação de apagar (apagar publicação é destrutivo e irreversível)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Confirmar",
                    callback_data=f"pub:delok:{post_id}",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="↩️ Voltar", callback_data=f"pub:delno:{post_id}"),
            ]
        ]
    )


def published_edit_menu_keyboard(post_id: int, has_images: bool) -> InlineKeyboardMarkup:
    """Escolha do que editar na publicação: texto sempre; imagem só se houver."""
    first_row = [
        InlineKeyboardButton(
            text="✏️ Texto",
            callback_data=f"pubedit:text:{post_id}",
            style=ButtonStyle.PRIMARY,
        )
    ]
    if has_images:
        first_row.append(
            InlineKeyboardButton(
                text="🖼 Imagem",
                callback_data=f"pubedit:img:{post_id}",
                style=ButtonStyle.PRIMARY,
            )
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first_row,
            [InlineKeyboardButton(text="↩️ Voltar", callback_data=f"pubedit:back:{post_id}")],
        ]
    )


def duplicate_keyboard(article_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔁 Gerar novamente", callback_data=f"duplicate:regenerate:{article_id}", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="🚫 Ignorar", callback_data="duplicate:ignore", style=ButtonStyle.DANGER),
            ]
        ]
    )


def team_keyboard(users: list[dict]) -> InlineKeyboardMarkup | None:
    """Lista de co-autores, um botão de revogar por pessoa (linha cheia, então
    pode passar de 12 chars). Retorna None se não houver ninguém."""
    if not users:
        return None
    rows = [
        [
            InlineKeyboardButton(
                text=_truncate_label(f"🗑 Revogar {u.get('name') or u['user_id']}"),
                callback_data=f"team:revoke:{u['user_id']}",
                style=ButtonStyle.DANGER,
            )
        ]
        for u in users
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
