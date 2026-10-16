# Farejador

Descobre canais novos do YouTube a partir de um canal de referência. Usa só o **yt-dlp**: sem YouTube Data API, sem chave, sem login.

## Como funciona

1. **Canal de referência.** Lê os últimos 30 vídeos em modo flat (1 requisição) e abre cada um por completo para obter descrição e tags (1 requisição por vídeo, com cache).
2. **Canais em destaque.** Tenta a aba "Canais" e depois a prateleira da aba Início. O aviso na saída diz se a aba *falhou* (erro do yt-dlp), se veio *vazia* (0 itens) ou se veio *sem canais* (só vídeos/playlists). Também avisa quando o yt-dlp declarou ter ignorado itens que não sabe ler.
3. **Palavras-chave.** Vêm de títulos e tags dos vídeos. Um termo só conta se aparecer em pelo menos 3 vídeos distintos. São ignorados: stopwords PT/EN, palavras genéricas de YouTube, o nome do canal, qualquer palavra de 4 ou mais letras contida no @handle (`@LucianoPiresCafeBrasil` elimina café, brasil, pires, luciano) e os termos passados em `--ignorar-termos`.
4. **Menções.** Busca nas descrições links de canais do YouTube (`/@handle`, `/channel/UC…`, `/c/…`, `/user/…`) e conta em quantos vídeos distintos cada um aparece. Ignora o próprio canal, canais cujo nome/handle contém o nome do criador e links presentes em 80% ou mais das descrições (rodapé). Cada canal citado é validado pelo yt-dlp: até 15, 1 requisição cada.
5. **Buscas** (8 no total, `ytsearch`), nesta ordem de prioridade:
   1. 3 títulos de vídeos recentes, limpos de nome do programa, número de episódio e hashtags, e diferentes entre si;
   2. frases recorrentes;
   3. pares de palavras-chave;
   4. palavra solta, só se sobrar espaço.
6. **Filtros.** Remove o próprio canal, os canais do `exclude.txt`, os canais automáticos ("- Topic", VEVO) e os **inativos** (sem vídeo em 60 dias). Um resultado de busca recente basta para marcar o canal como ativo. Fora isso, a atividade é confirmada na aba Vídeos do candidato (até 25).
7. **Ranking:**

   | Sinal | Pontos |
   |---|---|
   | Cada busca distinta em que o canal apareceu | +10 |
   | Citado em descrições | +20 pelo 1º vídeo, +5 por vídeo adicional (teto de 40) |
   | Em destaque no canal de referência | +15 |

   A lista principal só aceita candidatos com **2 sinais independentes ou mais**: cada busca distinta conta 1, a menção conta 1 e o destaque conta 1. Os demais aparecem com `--mostrar-fracos`.
8. **Saída.** Tabela com o motivo de cada score e `resultado.json` com tudo: termos, consultas, diagnóstico das abas, menções, removidos e custo por etapa.

Para respeitar o YouTube: pausa de 2,5 s entre requisições, cache em SQLite (7 dias; `0` = nunca expira), retry com backoff exponencial e parada imediata se aparecer anti-bot ou HTTP 429. Toda requisição e todo erro ficam na tabela `eventos` de `data/farejador.db`.

## Rodar com Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python farejador.py @canal
.venv/bin/python farejador.py @canal --ignorar-termos "podcast,lídercast" --verbose --mostrar-fracos
```

- `--verbose`: requisições e tempo por etapa, menções ignoradas/inválidas, inativos removidos e número de avisos do yt-dlp.
- `--salvar-bruto`: grava o retorno cru do yt-dlp (info dict + avisos emitidos) em `data/bruto/`. As abas de destaque são relidas da rede para isso; o resto só é gravado quando vai à rede (o cache guarda a versão reduzida).
- `exclude.txt` (opcional): um @handle, ID `UC...` ou URL por linha. Use `#` para comentários.

Custo típico sem cache: cerca de 1 + 30 + 2 + 15 + 8 + 25 ≈ 80 requisições, ou seja, uns 3 a 4 minutos só de pausa. Rodar de novo com o cache quente custa uma fração disso.

## Configuração

Toda opção da CLI também pode vir de uma variável de ambiente `FAREJADOR_<NOME>`. A CLI tem prioridade.

| Variável | Padrão | O que é |
|---|---|---|
| `FAREJADOR_PAUSA` | 2.5 | segundos entre requisições |
| `FAREJADOR_MAX_BUSCAS` | 8 | total de buscas |
| `FAREJADOR_BUSCAS_TITULOS` | 3 | quantas delas usam títulos (máx. metade do total) |
| `FAREJADOR_RESULTADOS_POR_BUSCA` | 20 | vídeos por busca |
| `FAREJADOR_VIDEOS_REFERENCIA` | 30 | vídeos lidos do canal de referência |
| `FAREJADOR_DETALHES_VIDEOS` | 30 | vídeos abertos por completo (descrição/tags) |
| `FAREJADOR_MIN_VIDEOS_TERMO` | 3 | vídeos distintos para um termo valer |
| `FAREJADOR_IGNORAR_TERMOS` | — | termos extras a ignorar, separados por vírgula |
| `FAREJADOR_MAX_MENCOES` | 15 | canais citados validados |
| `FAREJADOR_MIN_SINAIS` | 2 | sinais para entrar na lista principal |
| `FAREJADOR_VERIFICAR_ATIVIDADE` | 25 | candidatos com atividade checada no canal |
| `FAREJADOR_DIAS_ATIVO` | 60 | janela de atividade (inativo é excluído) |
| `FAREJADOR_CACHE_HORAS` | 168 | validade do cache (0 = nunca expira) |
| `FAREJADOR_TENTATIVAS` / `FAREJADOR_BACKOFF` | 3 / 5 | retry e base do backoff (s) |
| `FAREJADOR_TOP` | 20 | linhas na tabela |
| `FAREJADOR_VERBOSE` / `FAREJADOR_MOSTRAR_FRACOS` / `FAREJADOR_SALVAR_BRUTO` | false | flags (`1`/`true`) |
| `FAREJADOR_DADOS` | data | pasta do SQLite, do cache do yt-dlp e de `bruto/` |
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

## Suposições e limitações

- **Datas aproximadas.** As datas nos resultados flat vêm de textos como "3 weeks ago". Servem para a janela de 60 dias, não para o dia exato. Um resultado de busca antigo **não** prova inatividade (a busca pode ter trazido um vídeo velho), por isso a confirmação é feita na aba Vídeos do canal. Candidato que não pôde ser checado fica com "atividade não verificada" em vez de ser excluído.
- **Palavras-chave só de títulos e tags.** As descrições dos vídeos ficam de fora das palavras-chave: costumam repetir rodapé (patrocínio, redes sociais), que dominaria a contagem. Elas são usadas só para as menções.
- **Ignorar pelo @handle é agressivo.** Qualquer palavra de 4 ou mais letras contida no handle some, mesmo quando é assunto legítimo (ex.: "brasil" num canal sobre o Brasil). Os nomes de quadros e programas que não estão no handle precisam de `--ignorar-termos`.
- **Menções só por link.** Um "@fulano" solto no texto é ambíguo (Instagram, X…) e não conta. "Canal do próprio criador" é heurística: o nome/handle contém o nome ou o handle da referência, ou o link aparece em 80% ou mais das descrições (com 5 vídeos ou mais).
- **Contagem de sinais.** Cada busca distinta conta 1, a menção conta 1 (não importa em quantos vídeos) e o destaque conta 1. Um canal citado em vários vídeos que não apareceu em nenhuma busca tem 1 sinal e fica entre os fracos. O número de vídeos que o citam pesa no score, não na contagem de sinais.
- **Proximidade de tamanho não implementada.** O yt-dlp não traz inscritos nos resultados de busca, só na página do canal. Para comparar o tamanho de todos os candidatos seria preciso 1 requisição extra por candidato. Hoje o número só aparece no JSON (`seguidores`) para os canais cuja página já é lida (menções e checagem de atividade).
- **Destaques: "o canal não tem" vs. "o yt-dlp não expõe".** Só é possível distinguir em parte. A saída diz se a aba falhou, veio vazia ou veio sem canais, e se o yt-dlp avisou que ignorou itens desconhecidos. O HTML cru do YouTube não é salvo (seriam vários MB por página).
- **Runtime JavaScript.** Versões recentes do yt-dlp querem um runtime JavaScript (deno) para a extração completa de vídeos. Sem ele, a leitura de detalhes pode falhar; nesse caso a saída avisa quantos vídeos tiveram detalhes lidos.
- **Docker:** fica para a fase 2.
