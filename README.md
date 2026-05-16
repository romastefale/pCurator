# pCurator

Redação automática privada para Telegram.

O pCurator transforma links e fontes de notícia em publicações editoriais prontas para dois canais, com curadoria por IA, imagem principal da matéria, deduplicação, controle de clickbait, qualidade de fonte, aprendizado por canal e publicação direta no Telegram.

## Stack da v1

- Python 3.12
- aiogram 3.27+
- OpenAI
- SQLite
- Railway com webhook leve

## Princípios

- Bot invisível publicamente.
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

## Imagem

- Se houver imagem válida, publicar sempre com `send_photo`.
- Se não houver imagem válida, avisar o admin para permitir envio manual de imagem.
- A origem da imagem fica apenas em log interno.

## Botões coloridos

A v1 usará botões coloridos nativos via aiogram/Bot API quando disponíveis:

- `success`: publicar, salvar, confirmar.
- `danger`: ignorar, bloquear, rejeitar.
- `primary`: editar, trocar imagem, escolher canal, agendar.

## Aplicação incremental

O projeto será aplicado por etapas pequenas para reduzir erro, facilitar revisão e evitar mudanças grandes demais no GitHub.
