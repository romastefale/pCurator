# pCurator

Bot de Telegram para curadoria editorial automatizada (Python 3.12, aiogram).

## User preferences

- **Deploy em produção: Railway.** Este bot já roda no Railway — não configurar deployment no Replit nem sugerir publish. O Replit é apenas ambiente de desenvolvimento/edição.
- Idioma de comunicação: português.

## Overview

- Roda em polling (long-poll), sem webhook.
- Entrada: `python main.py` → `app.runner.main()`.
- Variáveis de ambiente (Railway): `BOT_TOKEN`, `OWNER_ID`, `CHANNEL_1_ID`, `CHANNEL_2_ID`, `OPENAI_KEY` (opcional), `LINKPREVIEW_KEY` (opcional), `DATABASE_PATH`, `TIMEZONE`.
- Storage: SQLite em `./data/pcurator.db`.
