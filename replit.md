# pCurator

Bot de Telegram para curadoria editorial automatizada (Python 3.12, aiogram).

## User preferences

- **Deploy em produção: Railway.** Este bot já roda no Railway — não configurar deployment no Replit nem sugerir publish. O Replit é apenas ambiente de desenvolvimento/edição.
- Idioma de comunicação: português.
- **Sempre usar as versões mais recentes** de aiogram e Telegram Bot API ao propor mudanças.
- **Motor editorial em uso: Mira (mira_bridge).** O `structured_editor` (OpenAI) existe só como fallback de segurança e não é o caminho real em produção. Toda decisão de prompt, limite de caracteres ou regra editorial deve ser pensada e validada primeiro em `app/services/mira_bridge.py`.

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
- Storage: SQLite em `./data/pcurator.db`.
