# Farejador

Descobre canais novos do YouTube a partir de um canal de referência. Usa só o **yt-dlp**: sem YouTube Data API, sem chave, sem login.

## Como funciona

1. Lê os últimos ~30 vídeos do canal (modo flat, 1 requisição) e abre alguns por completo para pegar as tags (padrão: 5).
2. Procura os canais em destaque: primeiro a aba "Canais"; se ela não existir (o YouTube a removeu de muitos canais), usa a prateleira da aba Início. O resultado diz qual fonte foi usada.
3. Extrai palavras-chave e frases de títulos e tags. Conta em quantos vídeos cada termo aparece, ignora stopwords PT/EN, palavras genéricas de YouTube e o nome do próprio canal.
4. Faz até 8 buscas `ytsearch` (frases recorrentes primeiro, depois pares de palavras) e junta os canais que aparecem.
5. Remove o próprio canal, os canais do `exclude.txt` e os canais automáticos ("- Topic", VEVO).
6. Ranqueia: +10 por busca distinta em que o canal apareceu, +1 por vídeo extra (máx. +5), +15 se estiver em destaque no canal de referência, +5 se publicou nos últimos 60 dias e −10 se não publicou.
7. Mostra uma tabela com o motivo de cada score e grava `resultado.json`.

Para respeitar o YouTube: pausa de 2,5 s entre requisições, cache em SQLite (7 dias; `0` = nunca expira), retry com backoff exponencial e parada imediata se aparecer anti-bot ou HTTP 429. Toda requisição e todo erro ficam na tabela `eventos` de `data/farejador.db`.

## Rodar com Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python farejador.py @canal
.venv/bin/python farejador.py https://www.youtube.com/@canal --max-buscas 12 --pausa 4
```

`exclude.txt` (opcional): um @handle, ID `UC...` ou URL por linha. Use `#` para comentários.

## Configuração

Toda opção da CLI também pode vir de uma variável de ambiente `FAREJADOR_<NOME>`. A CLI tem prioridade.

| Variável | Padrão | O que é |
|---|---|---|
| `FAREJADOR_PAUSA` | 2.5 | segundos entre requisições |
| `FAREJADOR_MAX_BUSCAS` | 8 | número de buscas |
| `FAREJADOR_RESULTADOS_POR_BUSCA` | 20 | vídeos por busca |
| `FAREJADOR_VIDEOS_REFERENCIA` | 30 | vídeos lidos do canal de referência |
| `FAREJADOR_DETALHES_VIDEOS` | 5 | vídeos abertos por completo (tags) |
| `FAREJADOR_VERIFICAR_ATIVIDADE` | 10 | candidatos com atividade checada no próprio canal |
| `FAREJADOR_DIAS_ATIVO` | 60 | janela de "atividade recente" |
| `FAREJADOR_CACHE_HORAS` | 168 | validade do cache (0 = nunca expira) |
| `FAREJADOR_TENTATIVAS` / `FAREJADOR_BACKOFF` | 3 / 5 | retry e base do backoff (s) |
| `FAREJADOR_TOP` | 20 | linhas na tabela |
| `FAREJADOR_DADOS` | data | pasta do SQLite e do cache do yt-dlp |
| `FAREJADOR_EXCLUDE` / `FAREJADOR_SAIDA` | exclude.txt / resultado.json | arquivos |

Caminhos relativos são resolvidos dentro da pasta do projeto. Nem o cache do yt-dlp sai dela.

## Auditoria

```bash
sqlite3 data/farejador.db "SELECT quando, nivel, tipo, alvo, mensagem FROM eventos WHERE nivel != 'info' ORDER BY id DESC LIMIT 30"
```

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Os testes não acessam a rede: o yt-dlp é simulado.

## Limitações conhecidas

- As datas dos resultados flat são aproximadas ("3 weeks ago"). Isso basta para dizer se o canal publicou nos últimos 60 dias, mas não para saber o dia exato.
- Versões recentes do yt-dlp querem um runtime JavaScript (deno) para a extração completa de vídeos. Sem ele, ler as tags pode falhar. Nesse caso o aviso aparece na saída e as palavras-chave vêm só dos títulos e das tags do canal.
- Docker: fica para a fase 2.
