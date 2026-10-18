# Farejador

Descobre canais novos do YouTube a partir de um canal de referência. Usa só o **yt-dlp**: sem YouTube Data API, sem chave, sem login.

## Como funciona

1. **Canal de referência.** Lê os últimos 30 vídeos em modo flat (1 requisição) e abre cada um por completo para obter o título original, a descrição e as tags (1 requisição por vídeo, com cache).
2. **Canais em destaque.** Tenta a aba "Canais" e depois a prateleira da aba Início. O aviso na saída diz se a aba *falhou* (erro do yt-dlp), se veio *vazia* (0 itens) ou se veio *sem canais* (só vídeos/playlists). Também avisa quando o yt-dlp declarou ter ignorado itens que não sabe ler.
3. **Playlists da aba Início.** Lê até 6 playlists, com 15 títulos cada (1 requisição por playlist). O núcleo do canal costuma estar nelas, não nos vídeos mais recentes: no Café Brasil, os recentes eram palestras de um congresso e cortes de eleição. Os vídeos das playlists entram na contagem das palavras-chave, e os títulos das playlists reforçam termos, como as tags do canal. Os títulos das playlists também vão para o LLM.
4. **Palavras-chave.** Vêm de títulos e tags dos vídeos. Um termo só conta se aparecer em pelo menos 3 vídeos distintos. São ignorados: stopwords PT/EN, palavras genéricas de YouTube, o nome do canal, qualquer palavra de 4 ou mais letras contida no @handle (`@LucianoPiresCafeBrasil` elimina café, brasil, pires, luciano) e os termos passados em `--ignorar-termos`. **Palavras quase iguais contam como uma só:** com 5 letras ou mais, as mesmas 4 primeiras letras e uma letra de diferença, a forma menos frequente vira a mais frequente ("minnue" → "minnie", "carros" → "carro", "eletronico" → "eletronica"). Sem isso, um erro de digitação repetido nos títulos virava uma segunda busca quase idêntica e dava dois sinais ao mesmo canal. A saída mostra as variantes unidas.
5. **Menções.** Busca nas descrições links de canais do YouTube (`/@handle`, `/channel/UC…`, `/c/…`, `/user/…`) e conta em quantos vídeos distintos cada um aparece. Ignora o próprio canal, canais cujo nome/handle contém o nome do criador e links presentes em 80% ou mais das descrições (rodapé). Cada canal citado é validado pelo yt-dlp: até 15, 1 requisição cada.
6. **Buscas** (8 no total, `ytsearch`), nesta ordem de prioridade:
   1. 3 títulos de vídeos recentes, limpos de nome do programa, número de episódio e hashtags, diferentes entre si e com pelo menos uma palavra-chave;
   2. frases recorrentes (uma frase que só estende outra pelo menos tão frequente é descartada: "filtro linha gamer" sai quando há "filtro linha");
   3. pares de palavras-chave;
   4. palavra solta, só se sobrar espaço.
7. **Filtros.** Remove o próprio canal, os canais do `exclude.txt`, os canais automáticos ("- Topic", VEVO) e os **inativos** (sem vídeo em 60 dias). Um resultado de busca recente basta para marcar o canal como ativo. Fora isso, a atividade é confirmada na aba Vídeos do candidato (até 25).
8. **Ranking:**

   | Sinal | Pontos |
   |---|---|
   | Cada busca distinta em que o canal apareceu | +10 |
   | Citado em descrições | +20 pelo 1º vídeo, +5 por vídeo adicional (teto de 40) |
   | Em destaque no canal de referência | +15 |

   A lista principal só aceita candidatos com **2 sinais independentes ou mais**: cada busca distinta conta 1, a menção conta 1 e o destaque conta 1. Os demais aparecem com `--mostrar-fracos`.
9. **Saída.** Tabela com o motivo de cada score e `resultado.json` com tudo: termos, consultas, diagnóstico das abas, menções, removidos e custo por etapa.

Para respeitar o YouTube: pausa de 2,5 s entre requisições, cache em SQLite (7 dias; `0` = nunca expira) e retry com backoff exponencial. Se o anti-bot ou o HTTP 429 fizerem uma requisição falhar duas vezes, a execução para. Quando o yt-dlp contorna o 429 sozinho, a execução continua, mas o resumo informa quantas requisições foram limitadas (ver [Cookies](#cookies-do-youtube-opcional)). Toda requisição e todo erro ficam na tabela `eventos` de `data/farejador.db`.

## Rodar com Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # yt-dlp + yt-dlp-ejs + deno (ficam no .venv, nada global)
.venv/bin/python farejador.py @canal
.venv/bin/python farejador.py @canal --ignorar-termos "podcast,lídercast" --verbose --mostrar-fracos
```

- `--verbose`: requisições e tempo por etapa, menções ignoradas/inválidas, inativos removidos e número de avisos do yt-dlp.
- `--salvar-bruto`: grava o retorno cru do yt-dlp (info dict + avisos emitidos) em `data/bruto/`. As abas de destaque são relidas da rede para isso; o resto só é gravado quando vai à rede (o cache guarda a versão reduzida).
- `exclude.txt` (opcional): um @handle, ID `UC...` ou URL por linha. Use `#` para comentários.

Custo típico sem cache: cerca de 1 + 30 + 2 + 6 + 15 + 8 + 25 ≈ 87 requisições, ou seja, uns 4 minutos só de pausa. Rodar de novo com o cache quente custa uma fração disso.

## Servidor web e Docker (fase 2)

A mesma descoberta, com API, tela de aprovação e estado persistente no SQLite (`data/farejador.db`, o mesmo arquivo do cache).

### Docker (homelab)

```bash
docker compose up -d --build      # imagem farejador:prd, container "farejador"
# abra http://<ip-do-servidor>:8765
```

- **Configuração no `environment:` do compose** (que está no formato do CasaOS): LLM e MeTube ficam lá. Depois de mudar uma variável, rode `docker compose up -d` (recria o container, sem rebuild) ou salve pelo CasaOS. As demais `FAREJADOR_*` da seção Configuração podem ser acrescentadas no mesmo bloco.
- **Código montado por volume:** o compose monta `./farejador` dentro do container e roda o uvicorn com `--reload`. Salvou um arquivo, o servidor recarrega sozinho. **Rebuild só quando mudar `requirements*.txt` ou o `Dockerfile`.**
  - Recarregar no meio de uma descoberta a interrompe. Ela fica marcada como `interrompida` e basta rodar de novo, porque o que já foi buscado está no cache.
- **Dados em `./data`:** `farejador.db`, cache do yt-dlp, `cookies.txt` (se enviado) e `bruto/`. A lista de exclusão vira `./data/exclude.txt`. Os arquivos ficam com o dono `1000:1000` (linha `user:` do compose).
- **Recursos:**
  - **Imagem:** ~400 MB, dos quais ~130 MB são do deno. O deno vem pelo extra `yt-dlp[deno]` do pip; o `yt-dlp[default]` traz o `yt-dlp-ejs`. Os dois resolvem o desafio JavaScript do YouTube, sem o qual a leitura de detalhes pode falhar.
  - **Memória:** limite de 1 GB (`deploy.resources.limits.memory`, controlado pelo CasaOS). Ocioso, o servidor usa ~85 MB. Não use `mem_limit` junto: com valores diferentes, o compose recusa o arquivo.
  - **Processos:** a descoberta roda numa **thread em segundo plano** do próprio processo, uma por vez, com o progresso gravado no SQLite. Não há fila nem processo extra.
- **Sem autenticação.** Use só na rede local.

### Sem Docker

```bash
.venv/bin/pip install -r requirements.txt -r requirements-web.txt
.venv/bin/uvicorn --factory farejador.web:criar_app --host 0.0.0.0 --port 8765 --reload --reload-dir farejador
```

### Tela

Tem quatro blocos:

- **Sementes:** adicionar ou remover canais de referência.
- **Cookies do YouTube:** enviar ou remover o `cookies.txt` e ver se ele está em uso.
- **Descoberta:** um botão para rodar todas as sementes, com o progresso ao vivo e o resumo de cada semente: requisições, quantas levaram 429, se usou cookies e os avisos.
- **Candidatos:** abas Novos, Aprovados, Descartados e Arquivados. Cada candidato mostra o score, a nota e a justificativa do LLM, o motivo e as sementes em que apareceu, com os botões Aprovar e Descartar (na aba Descartados, Aprovar desfaz um descarte por engano). No topo ficam "Exportar aprovados", "Inscrever aprovados no MeTube" (só com o MeTube ligado) e "Arquivar decididos". Todas as abas têm uma busca por nome, @handle ou semente; a aba Arquivados tem o botão "Remover do arquivo".

Fluxo de uma rodada: rodar a descoberta → aprovar e descartar → inscrever os aprovados no MeTube → arquivar os decididos.

### Estados dos candidatos

- `novo` pode ir para `aprovado` ou `descartado`; `aprovado` e `descartado` podem trocar entre si enquanto não forem arquivados.
- **Descartado nunca volta como novo** e nunca é sobrescrito por uma descoberta nova; só sai dali se você aprovar.
- Aprovados e descartados entram na exclusão das próximas descobertas e não gastam busca nem avaliação do LLM de novo.
- **Arquivar** tira aprovados e descartados das abas e da exportação, mas eles **continuam na exclusão**. **Remover do arquivo** apaga o registro: o canal sai da exclusão e pode reaparecer como novo numa descoberta futura.
- **Várias sementes:** um canal que aparece em mais de uma semente acumula a lista `sementes` e sobe na lista de novos. A ordem é `final + FAREJADOR_BONUS_SEMENTE × (sementes − 1)` (padrão 3, na escala 0–10 do final), e o cartão mostra o bônus. Fica guardada a versão de maior score entre as sementes.
- **Fracos cruzados:** quem teve poucos sinais numa semente (por exemplo, 1 busca) normalmente fica de fora. Ele entra na lista se também apareceu em **outra** semente, na mesma rodada ou como novo de uma rodada anterior. Só entram fracos com vídeo recente nos resultados de busca, porque os fracos não passam pela checagem de atividade. O motivo começa com "fraco nesta semente, mas apareceu em outra", e o resumo mostra quantos entraram assim. Isso só acontece no servidor; a CLI roda uma semente por vez.

### API

| Método e rota | O que faz |
|---|---|
| `GET /api/saude` | estado: descoberta rodando, LLM, MeTube e cookies |
| `GET/POST /api/sementes`, `DELETE /api/sementes/{id}` | sementes (`{"canal": "@x"}`) |
| `POST /api/descobertas` | roda todas as sementes, ou `{"sementes": [...]}`; 202 com `id`, 409 se já houver uma rodando |
| `GET /api/descobertas`, `GET /api/descobertas/{id}` | histórico e progresso |
| `GET /api/candidatos?estado=novo\|aprovado\|descartado` | lista |
| `GET /api/candidatos?estado=arquivado` | lista o arquivo |
| `POST /api/candidatos/{channel_id}/aprovar` ou `/descartar` | decide (409 em transição proibida) |
| `POST /api/candidatos/{channel_id}/metube` | envia um aprovado ao MeTube (o botão da tela chama esta rota para cada aprovado) |
| `POST /api/arquivar` | arquiva aprovados e descartados: saem das abas e da exportação, mas continuam excluídos |
| `DELETE /api/candidatos/{channel_id}` | remove um arquivado; o canal pode reaparecer numa descoberta |
| `GET /api/exportar` | URLs dos aprovados não arquivados, uma por linha (texto); `?arquivados=true` inclui os arquivados |
| `GET` / `PUT` / `DELETE /api/cookies` | estado, envio (corpo cru) e remoção do cookies.txt |
| `GET /api/docs` | documentação interativa |

### MeTube (opcional, desligado por padrão; ligado no compose deste homelab)

O endereço é o IP do host (`http://192.168.0.11:8081`), porque o MeTube está em outra rede Docker e o nome `metube` não resolve a partir deste container.

Com `FAREJADOR_METUBE_URL` preenchida, a tela ganha o botão **"Inscrever aprovados no MeTube"**. Ele envia, um por vez, os aprovados da rodada atual que ainda não foram enviados e mostra o progresso. Os que falharem ficam marcados e têm um botão para reenviar. Com `FAREJADOR_METUBE_AO_APROVAR=true`, o canal já é enviado no momento em que você clica em "Aprovar". O formato foi lido do código do MeTube (`app/main.py` e `app/format_catalog.py`):

- **`FAREJADOR_METUBE_MODO=assinar` (padrão):** `POST /subscribe` com `{"url", "download_type": "video", "format", "quality", "codec"}`, valores definidos por `FAREJADOR_METUBE_FORMATO`, `_QUALIDADE` e `_CODEC`. Na hora da inscrição, o MeTube lê o canal e marca os vídeos atuais como vistos, por isso cada envio pode levar alguns segundos (`FAREJADOR_METUBE_TIMEOUT`, padrão 60). Depois disso, ele baixa **só os vídeos novos**. Se a URL já estiver inscrita, o envio conta como sucesso. O MeTube compara a URL exata, então `@canal` e `/channel/UC…` contam como inscrições diferentes. `FAREJADOR_METUBE_INTERVALO` (minutos) define o intervalo de checagem; 0 usa o padrão do MeTube.
- **`baixar`:** `POST /add` com os mesmos campos mais `playlist_item_limit = FAREJADOR_METUBE_LIMITE` (padrão 5). O limite é sempre enviado, porque mandar um canal sem limite faria o MeTube **baixar o canal inteiro** (o padrão dele é 0, que significa tudo).
- **Sucesso e falha:** é sucesso quando a resposta é HTTP 2xx e não traz `{"status": "error"}`. O MeTube pode responder 200 com erro no corpo. Envios e erros vão para a tabela `eventos` (`metube` e `metube_erro`).

## Cookies do YouTube (opcional)

Sem cookies, o yt-dlp acessa o YouTube anonimamente, e o YouTube pode responder `429 Too Many Requests`. Quando isso acontece, o resumo da descoberta mostra quantas requisições levaram 429, mesmo que o yt-dlp tenha contornado o erro.

O esquema é o mesmo do MeTube:

- **Envio pela tela** (ou `PUT /api/cookies` com o arquivo no corpo): o arquivo vai para `data/cookies.txt`, com permissão 600. O limite é 1 MB, e só é aceito o formato Netscape com cookies de youtube.com. A API nunca devolve o conteúdo.
- **`FAREJADOR_COOKIES`:** caminho para um arquivo já existente. Se houver um arquivo enviado pela tela, ele tem prioridade. "Remover" na tela (`DELETE /api/cookies`) só apaga o enviado.
- **Aviso "ffmpeg not found":** com a conta logada, o yt-dlp avalia formatos de download e reclama da falta do ffmpeg. O Farejador nunca baixa vídeo, então esse aviso não é registrado.
- **Escrita:** o yt-dlp regrava o arquivo a cada extração com os cookies renovados, então ele precisa ser gravável pelo usuário do container (1000).

Cuidados:
- Use uma conta secundária. Com cookies, as requisições ficam ligadas à conta, e o YouTube pode restringi-la.
- Exporte os cookies de uma janela anônima e feche a janela depois. Se o navegador continuar usando aquela sessão, o YouTube troca os cookies e o arquivo para de valer. Quando o yt-dlp avisa que os cookies "are no longer valid", ele segue sem login. O Farejador registra o aviso, e a tela passa a mostrar "EXPIRADOS" no bloco de cookies e no resumo da rodada até um arquivo novo ser enviado (ou o atual ser removido). A marca não sai sozinha, porque o aviso não aparece em toda requisição: a ausência dele não prova que os cookies voltaram a valer.
- Cookies reduzem o 429, mas não o eliminam: o limite também é aplicado por IP.

## LLM local (opcional, desligado por padrão)

Com um servidor compatível com a API da OpenAI (testado contra o formato do LM Studio), o Farejador faz duas coisas a mais:

1. **Pede de 8 a 10 consultas sobre o tema** a partir de nome, títulos, tags e trechos de descrição do canal. O prompt proíbe o nome do canal e dos programas. Consultas com termo proibido, repetidas, com menos de 2 ou mais de 8 palavras, ou iguais a uma determinística são descartadas. As válidas **somam** às buscas determinísticas, até `FAREJADOR_LLM_MAX_BUSCAS` (padrão 8), e aparecem com origem `[llm]`.
2. **Reavalia os primeiros candidatos da lista principal** (`FAREJADOR_LLM_AVALIAR`, padrão 15). O modelo recebe o perfil da referência e até 10 títulos recentes do candidato e devolve uma nota de 0 a 10 de afinidade temática, com uma justificativa de uma frase. Quando a aba Vídeos do candidato ainda não foi lida, ela é lida agora (1 requisição ao YouTube, com cache).
   - **Ordem final:** `(1 − peso) × score normalizado (0–10) + peso × nota`, com peso `FAREJADOR_LLM_PESO` (padrão 0,5). O score normalizado é o score dividido pelo percentil 90 dos scores da lista, × 10, com teto 10. Assim, um único canal com score muito alto não comprime os outros perto de zero.
   - **Sem nota** (falha ou fora do limite): o candidato recebe a média das notas dadas na execução. Se nenhum foi avaliado, usa o próprio score normalizado.
   - **Corte opcional:** `FAREJADOR_LLM_NOTA_MIN` (padrão 0, desligado) tira da lista principal quem teve nota abaixo do valor. Os reprovados ficam no JSON (`reprovados_llm`) e aparecem com `--verbose` ou `--mostrar-fracos`. Quem não foi avaliado nunca é cortado.

```bash
export FAREJADOR_LLM_URL=http://192.168.0.6:1234      # /v1 é acrescentado se faltar
export FAREJADOR_LLM_MODEL=google/gemma-4-e4b          # vazio = primeiro modelo carregado
.venv/bin/python farejador.py @canal                   # usa o LLM
.venv/bin/python farejador.py @canal --sem-llm         # força o modo determinístico
```

O endereço é só configuração. Se o IP mudar, troque a variável ou passe `--llm-url`.

### Como ligar o servidor no LM Studio

1. Carregue o modelo (ex.: `google/gemma-4-e4b`).
2. Na aba **Developer**, ligue o servidor. Pelo terminal, `lms server start` faz o mesmo. A porta padrão é 1234.
3. Nas configurações do servidor, ative **Serve on Local Network**. Sem isso, o servidor só aceita conexões da própria máquina.
4. Deixe **Require Authentication** desligado: o Farejador não envia token.
5. Se houver firewall na máquina do LM Studio, libere a porta TCP 1234 para a rede local.
6. Teste da máquina do Farejador: `curl http://192.168.0.6:1234/v1/models` deve listar o modelo.

### Falhas: o LLM nunca derruba a execução

- **Timeout ou servidor fora do ar:** o LLM é desligado na primeira ocorrência e a execução segue no modo determinístico, com AVISO. Não espera um timeout por candidato.
- **Resposta fora do formato:** é descartada (não entra no cache). Com 3 respostas inválidas ou erros HTTP seguidos, o LLM é desligado.
- **Cache:** respostas válidas ficam no SQLite com chave = hash de (modelo, prompt, schema). Trocar de modelo invalida o cache.
- **Log:** latência e erros vão para a tabela `eventos`. Os tipos são `llm`, `llm_indisponivel`, `llm_invalido` e `llm_erro`.
- **`--salvar-bruto`:** grava cada pedido e cada resposta crua em `data/bruto/llm-<tipo>-<hash>.json`.

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
| `FAREJADOR_MAX_PLAYLISTS` | 6 | playlists da aba Início lidas |
| `FAREJADOR_VIDEOS_PLAYLIST` | 15 | títulos lidos por playlist |
| `FAREJADOR_IDIOMA` | pt | idioma pedido ao YouTube ao ler playlists (vazio = padrão do yt-dlp, inglês) |
| `FAREJADOR_MIN_VIDEOS_TERMO` | 3 | vídeos distintos para um termo valer |
| `FAREJADOR_IGNORAR_TERMOS` | — | termos extras a ignorar, separados por vírgula |
| `FAREJADOR_MAX_MENCOES` | 15 | canais citados validados |
| `FAREJADOR_MIN_SINAIS` | 2 | sinais para entrar na lista principal |
| `FAREJADOR_BONUS_SEMENTE` | 3 | servidor: bônus na ordem dos novos por semente extra (0 = desliga) |
| `FAREJADOR_VERIFICAR_ATIVIDADE` | 25 | candidatos com atividade checada no canal |
| `FAREJADOR_DIAS_ATIVO` | 60 | janela de atividade (inativo é excluído) |
| `FAREJADOR_CACHE_HORAS` | 168 | validade do cache (0 = nunca expira) |
| `FAREJADOR_TENTATIVAS` / `FAREJADOR_BACKOFF` | 3 / 5 | retry e base do backoff (s) |
| `FAREJADOR_TOP` | 20 | linhas na tabela |
| `FAREJADOR_VERBOSE` / `FAREJADOR_MOSTRAR_FRACOS` / `FAREJADOR_SALVAR_BRUTO` | false | flags (`1`/`true`) |
| `FAREJADOR_LLM_URL` | — | servidor OpenAI-compatível; vazio = LLM desligado |
| `FAREJADOR_LLM_MODEL` | — | id do modelo; vazio = primeiro de `/v1/models` |
| `FAREJADOR_LLM_TIMEOUT` | 60 | segundos por chamada |
| `FAREJADOR_LLM_MAX_BUSCAS` | 8 | consultas do LLM somadas às determinísticas |
| `FAREJADOR_LLM_AVALIAR` | 15 | candidatos reavaliados |
| `FAREJADOR_LLM_PESO` | 0.5 | peso da nota na ordem final (0 a 1) |
| `FAREJADOR_LLM_NOTA_MIN` | 0 | nota mínima para ficar na lista principal (0 = sem corte) |
| `FAREJADOR_SEM_LLM` / `--sem-llm` | false | ignora o LLM mesmo configurado |
| `FAREJADOR_METUBE_URL` | — | endereço do MeTube; vazio = desligado |
| `FAREJADOR_METUBE_MODO` | assinar | `assinar` (só vídeos novos) ou `baixar` (os últimos N) |
| `FAREJADOR_METUBE_FORMATO` / `_QUALIDADE` / `_CODEC` | any / best / — | campos do pedido ao MeTube |
| `FAREJADOR_METUBE_INTERVALO` | 0 | assinar: minutos entre checagens (0 = padrão do MeTube) |
| `FAREJADOR_METUBE_LIMITE` | 5 | baixar: quantos vídeos |
| `FAREJADOR_METUBE_AO_APROVAR` | false | envia já ao clicar em Aprovar |
| `FAREJADOR_METUBE_TIMEOUT` | 60 | segundos por envio |
| `FAREJADOR_COOKIES` | — | cookies.txt para o yt-dlp (o enviado pela tela tem prioridade) |
| `FAREJADOR_DADOS` | data | pasta do SQLite, do cache do yt-dlp e de `bruto/` |
| `FAREJADOR_EXCLUDE` / `FAREJADOR_SAIDA` | exclude.txt / resultado.json | arquivos |

Caminhos relativos são resolvidos dentro da pasta do projeto. Nem o cache do yt-dlp sai dela.

## Auditoria

```bash
sqlite3 data/farejador.db "SELECT quando, nivel, tipo, alvo, mensagem FROM eventos WHERE nivel != 'info' ORDER BY id DESC LIMIT 30"
sqlite3 data/farejador.db "SELECT quando, alvo, mensagem FROM eventos WHERE mensagem LIKE '%429%' ORDER BY id DESC LIMIT 30"
```

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

Os testes não acessam a rede: o yt-dlp, o LLM e o MeTube são simulados. Para os testes da API: `.venv/bin/pip install -r requirements-web.txt -r requirements-dev.txt`.

## Suposições e limitações

- **Datas aproximadas.** As datas nos resultados flat vêm de textos como "3 weeks ago". Servem para a janela de 60 dias, não para o dia exato. Um resultado de busca antigo **não** prova inatividade (a busca pode ter trazido um vídeo velho), por isso a confirmação é feita na aba Vídeos do canal. Candidato que não pôde ser checado fica com "atividade não verificada" em vez de ser excluído.
- **Títulos traduzidos.** Em modo flat, o YouTube devolve os títulos traduzidos para o idioma da interface que o yt-dlp pede (inglês). Nos 30 vídeos do @SERTECMANUTENCAO, os 30 chegaram assim: "Feliz dia do Professor" virou "Happy Teacher's Day".
  - **Vídeos do canal de referência:** o título vem da extração completa, que traz o original. O resumo mostra quantos foram corrigidos.
  - **Playlists:** pedidas no idioma de `FAREJADOR_IDIOMA` (padrão `pt`). Num canal em português, isso devolve o original; num canal em outro idioma, ajuste a variável. Com idioma diferente de inglês as datas aproximadas deixam de ser lidas, mas as playlists não usam datas.
  - **Candidatos:** títulos de resultados de busca e da aba Vídeos dos candidatos, que vão para o LLM, continuam traduzidos. Corrigir custaria 1 extração completa por vídeo.
  - O idioma não é aplicado no resto, porque o yt-dlp só sabe ler datas relativas em inglês ("3 weeks ago"), e a checagem de atividade depende delas.
- **Funciona bem para canais de nicho, mal para canais ecléticos.** Contar palavras por vídeo exige que o assunto se repita nos títulos. Em canais de nicho (testados @SERTECMANUTENCAO, de eletrônica, e @DisneyDesenhos) a lista principal saiu no nicho. Em canais ecléticos, cada episódio trata de um assunto, e o que se repete é o nome da série ou do patrocinador.
  - No @LucianoPiresCafeBrasil, "Iscas Intelectuais" e "Videocast Nakata" (Nakata é um patrocinador de autopeças) viraram as principais palavras-chave, e as buscas trouxeram lojas de autopeças.
  - O que ajuda: `--ignorar-termos` com os nomes de série e patrocinador e `FAREJADOR_LLM_NOTA_MIN`. Com esse corte ligado, a saída honesta pode ser "nenhum canal parecido encontrado".
  - Várias sementes do mesmo nicho ajudam: o servidor dá bônus a quem aparece em mais de uma e recupera os fracos que se repetem entre elas. Um telejornal que surge numa semente eclética raramente se repete nas outras.
- **Bloco de tags repetido em todos os vídeos** ("alta qualidade excelente imagem dublado" no @DisneyDesenhos) vira palavra-chave com contagem máxima. Costuma não ocupar vaga de busca porque as frases vêm antes, mas aparece na lista de palavras-chave.
- **Palavras-chave só de títulos e tags.** As descrições dos vídeos ficam de fora das palavras-chave: costumam repetir rodapé (patrocínio, redes sociais), que dominaria a contagem. Elas são usadas só para as menções.
- **Ignorar pelo @handle é agressivo.** Qualquer palavra de 4 ou mais letras contida no handle some, mesmo quando é assunto legítimo (ex.: "brasil" num canal sobre o Brasil). Os nomes de quadros e programas que não estão no handle precisam de `--ignorar-termos`.
- **Menções só por link.** Um "@fulano" solto no texto é ambíguo (Instagram, X…) e não conta. "Canal do próprio criador" é heurística: o nome/handle contém o nome ou o handle da referência, ou o link aparece em 80% ou mais das descrições (com 5 vídeos ou mais).
- **Contagem de sinais.** Cada busca distinta conta 1, a menção conta 1 (não importa em quantos vídeos) e o destaque conta 1. Um canal citado em vários vídeos que não apareceu em nenhuma busca tem 1 sinal e fica entre os fracos. O número de vídeos que o citam pesa no score, não na contagem de sinais.
- **Proximidade de tamanho não implementada.** O yt-dlp não traz inscritos nos resultados de busca, só na página do canal. Para comparar o tamanho de todos os candidatos seria preciso 1 requisição extra por candidato. Hoje o número só aparece no JSON (`seguidores`) para os canais cuja página já é lida (menções e checagem de atividade).
- **Destaques: "o canal não tem" vs. "o yt-dlp não expõe".** Só é possível distinguir em parte. A saída diz se a aba falhou, veio vazia ou veio sem canais, e se o yt-dlp avisou que ignorou itens desconhecidos. O HTML cru do YouTube não é salvo (seriam vários MB por página).
- **Runtime JavaScript.** O yt-dlp precisa de um runtime JavaScript (deno) para a extração completa de vídeos. O `requirements.txt` já instala o deno pelo pip, no `.venv` e na imagem. Se ele faltar, a leitura de detalhes pode falhar, e a saída avisa quantos vídeos tiveram detalhes lidos.
- **Formato da resposta do LLM.** Supõe-se o formato `/v1/chat/completions` da OpenAI, com o JSON em texto dentro de `choices[0].message.content`.
  - O pedido usa `response_format: {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}` (structured output do LM Studio). Se o servidor responder HTTP 400, o pedido é repetido sem `response_format`.
  - O LM Studio avisa que modelos abaixo de ~7B nem sempre obedecem ao schema, e o gemma-4-e4b é um deles. Por isso a resposta é sempre validada aqui: o parser tolera blocos `<think>…</think>`, cercas \`\`\`json e texto antes ou depois do objeto.
  - Consultas: `{"consultas": [string]}`. Nota: `{"nota": número de 0 a 10, "justificativa": string}`. Nota em string (`"7"`) é rejeitada.
- **Sem mensagem `system`.** Tudo vai numa única mensagem `user`, porque alguns templates (Gemma) recusam o papel `system`. A temperatura é fixa em 0,2.
- **A nota do LLM é opinião de um modelo pequeno.** Por padrão, ela só reordena e não substitui os sinais determinísticos. Só tira alguém da lista se `FAREJADOR_LLM_NOTA_MIN` estiver ligado.
- **Servidor sem autenticação e uma descoberta por vez.** Pensado para uma pessoa na rede local.
- **Junção de palavras quase iguais é heurística.** Ela também junta gênero e plural ("brasileira" → "brasileiro"), o que em geral ajuda a contagem, e pode juntar palavras distintas que começam igual e diferem numa letra no fim ("virar" → "viram"). A regra das 4 primeiras letras evita os casos vistos nos testes ("steam"/"stream", "estudo"/"estado"). As variantes unidas aparecem na saída.

## Ideias não implementadas

Levantadas nos testes; nenhuma foi decidida:

- Detectar nomes de série e de patrocinador (Café Brasil) e blocos de tags presentes em todos os vídeos (Disney).
- Penalidade de tamanho (candidato muito maior que a referência).
- Prompt do LLM com teto de nota para canais generalistas; `FAREJADOR_LLM_AVALIAR` 20.
- Menção valendo 2 sinais.
- Desarquivar um canal sem apagá-lo; favicon na tela.
