# pCurator

Bot de Telegram para curadoria editorial automatizada (Python 3.12, aiogram).

## User preferences

- **Deploy em produção: Railway.** Este bot já roda no Railway — não configurar deployment no Replit nem sugerir publish. O Replit é apenas ambiente de desenvolvimento/edição.
- Idioma de comunicação: português.
- **Sempre usar as versões mais recentes** de aiogram e Telegram Bot API ao propor mudanças.
- **Motor editorial em uso: Mira (mira_bridge).** O `structured_editor` (OpenAI) existe só como fallback de segurança e não é o caminho real em produção. Toda decisão de prompt, limite de caracteres ou regra editorial deve ser pensada e validada primeiro em `app/services/mira_bridge.py`.
- **Texto de botão inline curto e incisivo.** Convenção (ver docstring no topo de `app/ui.py`): máx. ~12 chars quando 2 botões dividem a linha; 1 emoji + 1–2 palavras; sem verbo redundante com a mensagem acima ("📘 Canal 1", não "📘 Publicar no Canal 1"); pares paralelos na estrutura. Contexto fica na mensagem; o botão é só o objeto/escolha.
- **Cor de botão (ButtonStyle, Bot API 9.4+).** Convenção semântica registrada em `app/ui.py`: `SUCCESS` (🟢) só pra Publicar/Confirmar envio (raro e sagrado), `DANGER` (🔴) sempre que a ação descarta/cancela/marca como ignored (inclui "⏭ Próxima notícia"), `PRIMARY` (🔵) pra seleção entre opções equivalentes (canais, trilhas), e **sem style** pra navegação fraca (Voltar) e ações neutras de revisão (Editar/Trocar imagem) — não pintar tudo é tão importante quanto pintar pra preservar hierarquia.
- **Tom editorial ÚNICO (neutro).** Não existe mais escolha de tom por canal (c1/c2 removidos do fluxo). Todo resumo é gerado automaticamente com um único tom neutro/versátil (claro e direto, nem pop demais nem formal demais), definido na constante `UNIFIED_TONE = "geral"` em `app/services/regenerator.py` e descrito no prompt da Mira (`mira_bridge.build_mira_prompt`) e no fallback (`structured_editor`). A escolha de canal virou só **destino de publicação** (passo após a revisão). Fluxo: intake (link/dup/auto/`/buscar`) → geração imediata → review_keyboard (Publicar/Editar/Trocar imagem/Ignorar) → destination_keyboard (Canal 1/2) → confirmar → publicar.

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
