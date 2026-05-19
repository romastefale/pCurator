# Configuração

Configure as variáveis no Railway ou no ambiente local antes de iniciar o projeto.

## Variáveis obrigatórias

- `BOT_TOKEN`: token do bot no Telegram.
- `OWNER_ID`: ID numérico do administrador autorizado.
- `CHANNEL_1_ID`: ID numérico do Canal 1.
- `CHANNEL_2_ID`: ID numérico do Canal 2.

O bot precisa ser administrador dos canais para publicar.

## Motor editorial principal

O motor editorial principal é a Mira em grupo fechado.

- `MIRA_GROUP_ID`: grupo fechado usado para enviar o pedido editorial. Padrão: `-5027293000`.
- `MIRA_TIMEOUT_SECONDS`: tempo máximo de espera pela resposta. Padrão: `90`.

Fluxo editorial:

1. O pCurator cria o rascunho interno.
2. Ao escolher C1 ou C2, o pCurator envia o pedido no grupo fechado.
3. A Mira responde em reply com JSON.
4. O pCurator coleta a resposta, valida, renderiza e mostra a prévia.
5. Se a Mira falhar, usa OpenAI como fallback.
6. Se OpenAI falhar, usa fallback local e avisa na interface.

## Variáveis opcionais

- `OPENAI_KEY`: fallback editorial caso a Mira falhe.
- `LINKPREVIEW_KEY`: fallback para metadados e imagem do link.
- `DATABASE_PATH`: caminho do banco SQLite. Padrão: `./data/pcurator.db`.
- `TIMEZONE`: fuso horário. Padrão: `America/Sao_Paulo`.

## Exemplo Railway

```env
BOT_TOKEN=cole_o_token_do_bot
OWNER_ID=8505890439
CHANNEL_1_ID=-100xxxxxxxxxx
CHANNEL_2_ID=-100xxxxxxxxxx
MIRA_GROUP_ID=-5027293000
MIRA_TIMEOUT_SECONDS=90
OPENAI_KEY=
LINKPREVIEW_KEY=
DATABASE_PATH=/app/data/pcurator.db
TIMEZONE=America/Sao_Paulo
```

## Execução local inicial

```bash
python -m app.bootstrap
python main.py
```

## Estado atual

A v1 inicial roda em polling para reduzir pontos frágeis. O webhook para Railway deve entrar depois que o fluxo manual estiver validado.
