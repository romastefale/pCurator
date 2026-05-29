# pCurator

Bot de Telegram para curadoria editorial automatizada (Python 3.12, aiogram).

## User preferences

- **Deploy em produção: Railway.** Este bot já roda no Railway — não configurar deployment no Replit nem sugerir publish. O Replit é apenas ambiente de desenvolvimento/edição.
- Idioma de comunicação: português.
- **Sempre usar as versões mais recentes** de aiogram e Telegram Bot API ao propor mudanças.
- **Motor editorial em uso: Mira (mira_bridge).** O `structured_editor` (OpenAI) existe só como fallback de segurança e não é o caminho real em produção. Toda decisão de prompt, limite de caracteres ou regra editorial deve ser pensada e validada primeiro em `app/services/mira_bridge.py`.
- **Texto de botão inline curto e incisivo.** Convenção (ver docstring no topo de `app/ui.py`): máx. ~12 chars quando 2 botões dividem a linha; 1 emoji + 1–2 palavras; sem verbo redundante com a mensagem acima ("📘 Canal 1", não "📘 Publicar no Canal 1"); pares paralelos na estrutura. Contexto fica na mensagem; o botão é só o objeto/escolha.
- **Cor de botão (ButtonStyle, Bot API 9.4+).** Convenção semântica registrada em `app/ui.py`: `SUCCESS` (🟢) só pra Publicar/Confirmar envio (raro e sagrado), `DANGER` (🔴) sempre que a ação descarta/cancela/marca como ignored (inclui "⏭ Próxima notícia"), `PRIMARY` (🔵) pra seleção entre opções equivalentes (canais, trilhas), e **sem style** pra navegação fraca (Voltar) e ações neutras de revisão (Editar/Trocar imagem) — não pintar tudo é tão importante quanto pintar pra preservar hierarquia.
- **Tom editorial ÚNICO (neutro).** Não existe mais escolha de tom por canal (c1/c2 removidos do fluxo). Todo resumo é gerado automaticamente com um único tom neutro/versátil (claro e direto, nem pop demais nem formal demais), definido na constante `UNIFIED_TONE = "geral"` em `app/services/regenerator.py` e descrito no prompt da Mira (`mira_bridge.build_mira_prompt`) e no fallback (`structured_editor`). A escolha de canal virou só **destino de publicação** (passo após a revisão). Fluxo: intake (link/dup/auto/`/buscar`) → geração imediata → review_keyboard (Publicar/Editar/Trocar imagem/Ignorar) → destination_keyboard (1 botão por canal, **nome real**) → confirmar → publicar.

- **Canais dinâmicos (não mais c1/c2).** O bot descobre canais sozinho: o handler `my_chat_member` (`app/membership.py`, registrado em `routes.py`) detecta quando o bot vira **administrador** de um canal/supergrupo (`upsert_channel`) ou é removido/rebaixado (`set_channel_enabled(False)`). No startup, `runner._seed_channels()` faz `get_chat` em `CHANNEL_1_ID`/`CHANNEL_2_ID` pra registrar os 2 canais legados com o nome real. O roteamento de publicação é por **`chat_id`** (callback_data `dest:{chat_id}` e `post:confirm:{post_id}:{chat_id}`), resolvido em `callbacks._resolve_channel`/`_dest_title` — não há mais slugs c1/c2 no fluxo. `posts.channel_slug`/`session.active_channel_slug` ainda existem como metadado (guardam o `chat_id` em texto como destino, ou `geral`/`manual` na geração). Storage: `app/storage/channels.py` (`upsert_channel`/`list_channels`/`get_channel`/`set_channel_enabled`); tabela `channels` ganhou `username`/`updated_at` + `UNIQUE INDEX idx_channels_chat_id` (migração deduplica por `chat_id` antes de criar o índice). Comando `/pc` lista os canais detectados (acesso permitido a co-autores). Títulos vindos do Telegram são escapados com `html.escape` em mensagens HTML e truncados (`ui._truncate_label`, limite 64 chars do botão inline).

- **Co-autores (autorização por ID).** Além do `OWNER_ID`, o dono pode autorizar outros usuários a operar o bot. Co-autor tem **acesso total ao fluxo editorial** (publicar/editar/buscar), mas **não** gerencia equipe. `app/access.py`: `is_allowed_user` (dono OU co-autor ativo) + `reject_*_if_not_allowed` (permissivo, usado em todo o fluxo) e `reject_*_if_not_owner` (estrito, só na gestão de equipe). Storage: `app/storage/authorized_users.py` (`add`/`revoke`/`list`/`is_authorized`) + tabela `authorized_users`. Comandos **owner-only**: `/pe` (lista co-autores com botões de revogar — callback `team:revoke:{id}`), `/pea ID Nome` (autoriza pelo ID do Telegram). Naming: `/p` + letra (pe=equipe, pea=equipe add, pc=canais).

## Versões de referência (última checagem: 26/05/2026)

- **aiogram**: `3.28.2` (PyPI, lançada em 10/05/2026). Suporta Python `>=3.10, <3.15`.
- **Telegram Bot API**: `10.0` (changelog oficial, lançada em 03/04/2026). Features de 10.0 (bot-to-bot, gifts em canais, reactions em service messages, verifyUser/verifyChat) não afetam o fluxo atual do pCurator; aiogram 3.28.2 já cobre.
- **Python (runtime do projeto)**: 3.12.3 (compatível).
- Deprecações relevantes vigentes em aiogram 3.7+:
  - `disable_web_page_preview=True` → usar `link_preview_options=LinkPreviewOptions(is_disabled=True)`.
  - `parse_mode=...` direto no `Bot(...)` → usar `default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))`.
  - O kwarg antigo ainda funciona, mas emite `DeprecationWarning`.

## Overview

- Roda em polling (long-poll), sem webhook.
- Entrada: `python main.py` → `app.runner.main()`.
- Variáveis de ambiente (Railway): `BOT_TOKEN`, `OWNER_ID`, `CHANNEL_1_ID`, `CHANNEL_2_ID`, `OPENAI_KEY` (opcional), `LINKPREVIEW_KEY` (opcional), `DATABASE_PATH`, `TIMEZONE`.
- News discovery (opcional, desligado por padrão): `GNEWS_KEY`, `DISCOVERY_ENABLED=false`, `DISCOVERY_DAILY_CAP=20`, `DISCOVERY_QUIET_START=1`, `DISCOVERY_QUIET_END=5`, `DISCOVERY_TOPICS=` (csv vazio = todas as 7 trilhas: tech,cinema,series,pop,atualidades,ciencia,geek). Loop roda **a cada 1h** em janela 06h–00h local (cobertura completa de 19h ativas); o resumo é gerado direto no tom único neutro (`UNIFIED_TONE`), já indo pro review. Cada busca combina 2 endpoints do GNews (top-headlines + search) serialmente com pausa de 1.2s entre eles (respeita o rate limit ~1 req/seg do free tier).
- Busca manual: comando `/buscar` (precisa só de `GNEWS_KEY`, não respeita `DISCOVERY_ENABLED`, mas conta no mesmo `DISCOVERY_DAILY_CAP`). Fecha sessão/rascunho anterior automaticamente. Mostra orçamento de busca manual disponível pro dia (`safe_manual_searches` em `discovery_scheduler.py`, baseado em chamadas GNews já feitas vs reserva do auto-loop até o fim do dia, com `GNEWS_DAILY_BUDGET=100`). Teclado de trilhas; cada notícia entregue tem botão "⏭ Próxima notícia" que descarta a atual (status=ignored) e busca outra na mesma trilha. Estado da busca é in-memory por usuário, perdido em restart.
- Contadores diários em `app_settings`: `discovery_count:YYYY-MM-DD` (notícias entregues, usado no cap) e `gnews_calls:YYYY-MM-DD` (chamadas HTTP ao GNews, usado no orçamento do `/buscar`).
- Storage: SQLite em `./data/pcurator.db`.
