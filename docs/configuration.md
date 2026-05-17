# Configuração

Configure as variáveis no ambiente do Railway ou no ambiente local antes de iniciar o projeto.

## Variáveis obrigatórias

- `BOT_TOKEN`: token do bot no Telegram.
- `OWNER_ID`: ID numérico do administrador autorizado.

## Variáveis dos canais

- `CHANNEL_1_ID`: ID numérico do Canal 1.
- `CHANNEL_2_ID`: ID numérico do Canal 2.

O bot precisa ser administrador dos canais para publicar.

## Variáveis opcionais

- `OPENAI_KEY`: chave para recursos editoriais com IA.
- `DATABASE_PATH`: caminho do banco SQLite. Padrão: `./data/pcurator.db`.
- `TIMEZONE`: fuso horário. Padrão: `America/Sao_Paulo`.

## Execução local inicial

```bash
python -m app.bootstrap
python main.py
```

## Estado atual

A v1 inicial roda em polling para reduzir pontos frágeis. O webhook para Railway deve entrar depois que o fluxo manual estiver validado.
