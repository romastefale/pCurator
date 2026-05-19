# pCurator

Redação automática privada para Telegram.

O pCurator transforma links enviados manualmente pelo administrador em publicações editoriais prontas para dois canais, com curadoria por IA, imagem principal da matéria, deduplicação, controle de clickbait, qualidade de fonte, aprendizado por canal e publicação direta no Telegram.

## Stack da v1

- Python 3.12
- aiogram 3.27+
- OpenAI opcional
- LinkPreview opcional
- SQLite
- Railway ou execução local em polling

## Estado da v1

A v1 inicial roda em polling para reduzir pontos frágeis. Webhook deve entrar depois que o fluxo manual estiver validado em produção.

Fluxo principal:

1. Admin envia link.
2. Bot extrai matéria por HTML próprio.
3. Se necessário, usa LinkPreview como fallback de título/imagem/preview.
4. Bot detecta duplicidade por URL e hash textual.
5. Bot calcula risco editorial leve.
6. Bot cria rascunho e prévia.
7. Admin escolhe Canal 1 ou Canal 2.
8. Bot regenera a legenda com IA, se houver chave OpenAI.
9. Admin revisa, edita texto, troca imagem ou ignora.
10. Admin publica no canal escolhido.

## Princípios

- Bot invisível publicamente.
- Uso restrito ao `OWNER_ID`.
- Publicação preferencial como foto com legenda HTML.
- Links enviados manualmente pelo admin têm prioridade imediata.
- Automação cadenciada, editorial e anti-spam.
- Decisões importantes exigem confirmação humana.
- Aprendizado por canal, sempre com confirmação antes de virar regra forte.

## Canais

### Canal 1

Canal leve, pop e de cultura digital.

Permite TikTok, X/Twitter como sinal editorial, cultura pop, música, celebridades, memes, trends e comportamento digital leve.

Bloqueia sem perguntar: política, religião, violência gráfica, crime pesado, guerra, tragédia, conteúdo sexual explícito e assunto sensível incompatível com canal leve.

### Canal 2

Canal sério, maduro, jornalístico e imparcial.

Permite política, economia, instituições, justiça, segurança pública, tecnologia relevante, sociedade, internacional e fatos de relevância pública.

Escândalos repentinos e temas muito polarizados exigem revisão humana antes de publicar.

## Post padrão

```html
#Hashtag1 #Hashtag2 #Hashtag3

<b>Título forte, direto e fiel ao fato</b>

<i>Subtítulo curto, contextualizando a notícia sem exagerar.</i>

<blockquote><i>Corpo da notícia em tom jornalístico, curto e direto, com fato principal, impacto e contexto.</i></blockquote>

<i>Via: Nome da Fonte.</i>
<a href="LINK_REAL_DA_MATERIA">&#8203;</a>
```

## Configuração

Configure as variáveis no Railway ou no ambiente local:

- `BOT_TOKEN`: token do bot Telegram.
- `OWNER_ID`: ID numérico do administrador.
- `CHANNEL_1_ID`: ID do Canal 1.
- `CHANNEL_2_ID`: ID do Canal 2.
- `OPENAI_KEY`: opcional, para gerar texto editorial final.
- `LINKPREVIEW_KEY`: opcional, para fallback de preview/imagem.
- `DATABASE_PATH`: opcional, padrão `./data/pcurator.db`.
- `TIMEZONE`: opcional, padrão `America/Sao_Paulo`.

O bot precisa ser administrador dos canais para publicar.

## Execução

```bash
pip install -r requirements.txt
python -m app.bootstrap
python main.py
```

## Comandos principais

- `/start`: estado inicial.
- `/ph`: ajuda rápida.
- `/ps`: status técnico.
- `/pq`: fila editorial.
- `/pf`: fontes.
- `/pfa Nome | url | escopo | nota`: cadastrar fonte.
- `/pfs ID nota`: alterar nota da fonte.
- `/pfb ID`: bloquear fonte.
- `/pfu ID`: desbloquear fonte.
- `/pr`: regras aprendidas.
- `/pra canal | tipo | regra`: cadastrar regra.

## Botões coloridos

A v1 usa `style` nos botões inline quando a versão instalada do aiogram/Bot API suportar:

- `success`: publicar, salvar, confirmar.
- `danger`: ignorar, bloquear, rejeitar.
- `primary`: editar, trocar imagem, escolher canal.

Se a versão do SDK rejeitar `style`, remover temporariamente esse argumento de `app/ui.py` mantém o fluxo funcional sem cores.
