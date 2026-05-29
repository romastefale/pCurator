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


def destination_keyboard() -> InlineKeyboardMarkup:
    """Escolha do CANAL DE DESTINO (passo 5), após revisão/edição."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📘 Canal 1", callback_data="dest:c1", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="📰 Canal 2", callback_data="dest:c2", style=ButtonStyle.PRIMARY),
            ],
            [InlineKeyboardButton(text="↩️ Voltar para revisão", callback_data="dest:back")],
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


def channel_label(channel_slug: str | None) -> str:
    if channel_slug == "c1":
        return "📘 Canal 1"
    if channel_slug == "c2":
        return "📰 Canal 2"
    return "canal não definido"
