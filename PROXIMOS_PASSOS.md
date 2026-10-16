# Próximos passos

Estado em 2026-10-16. A fase 1 ainda não foi aprovada e a fase 2 (FastAPI/Docker) não começou.

## Avaliação da execução com LLM (@LucianoPiresCafeBrasil)

Qualidade: **ruim**. A lista principal tem 11 canais, e 7 deles são grandes veículos generalistas (CNN, Band, Jovem Pan, SBT, Metrópoles, TV Cultura, Olhar Digital). Os candidatos com algum parentesco temático visível são poucos: Canal do Cortella, Joel Jota e, de longe, Africa Wealth Initiative.

### Causa principal: a amostra do canal de referência é enviesada

Os 30 últimos vídeos da aba Vídeos são palestras do Congresso ANDAV (agronegócio, títulos em inglês) e cortes sobre a eleição. O núcleo do canal não está ali, mas nas **playlists da aba Início**. O retorno cru (`data/bruto/destaques2_..._featured.json`) mostra:

- Podcast Café Brasil
- CAFEZINHO | Reflexões Curtas Que Transformam o Dia
- Videocast Iscas Intelectuais
- Videocast Nakata
- Luciano Pires na Mídia
- Bastidores do Estúdio Café Brasil

Daí vieram palavras-chave como "andav", "agribusiness", "candidos presidencia" e "urna eletronica", e as buscas por eleição trouxeram os telejornais. "andav" não é ruído de digitação: é o nome do congresso que domina a amostra.

### O LLM amplificou o viés

O perfil enviado ao modelo veio da mesma amostra, então ele concluiu que a referência é "política e agronegócio" e deu 8/10 à CNN. As consultas que ele gerou respeitaram a proibição de nomes. O custo foi de 17,5 s para as consultas e cerca de 118 s para 11 avaliações (incluindo 7 leituras do YouTube).

### Outros fatos da execução

- **Tamanho:** a referência tem 53,7 mil inscritos; os telejornais têm de 4 a 9 milhões, de 80 a 170 vezes mais. Nesta execução, todos os 11 candidatos já tinham `seguidores` preenchido sem custo extra, porque a reavaliação do LLM leu a página deles.
- **Menções:** 0 canais válidos. Só apareceram links do próprio criador (c/lucianopires1, c/lidercast). O sinal existe, mas não serve para este canal.
- **Destaques:** a aba Canais não existe ("does not have a channels tab"). A aba Início tem só playlists e um link para a aba Vídeos. Conclusão: este canal **não tem** canais em destaque; não é falha do yt-dlp.
- **Palavras genéricas:** "youtube" (20 vídeos), "mesa", "domingo" e "palestra" passaram como palavras-chave. "conciente" (erro de grafia do canal) também.
- **yt-dlp:** 25 avisos de "No supported JavaScript runtime (deno)". Os detalhes foram lidos mesmo assim (30/30 com tags), mas é um risco futuro. Houve também 4 avisos de "Incomplete yt initial data", instabilidade do YouTube.
- **Fracos:** 222 candidatos com 1 sinal só (todos "1 busca"). As 16 buscas são dispersas demais para se cruzarem.

## Propostas, por prioridade (aguardando decisão)

1. **Ampliar a amostra com as playlists da aba Início.** A aba já é lida. Ler os títulos de cada playlist em modo flat custa 1 requisição por playlist (6 aqui). Os títulos de playlists ("Podcast Café Brasil", "Iscas Intelectuais") e os vídeos delas entram nas palavras-chave e no perfil do LLM. Opcional: incluir as abas `/podcasts` e `/streams`.
2. **Proximidade de tamanho.** Penalizar o candidato com N vezes mais inscritos que a referência (ex.: mais de 20 vezes). O dado já chega sem custo para quem passa pela checagem de atividade, pela validação de menção ou pela reavaliação do LLM. Para os demais, custaria 1 requisição. Decidir se aplica só onde o dado já existe.
3. **Prompt do LLM.** Montar o perfil com a descrição do canal e os títulos das playlists, e instruir que um canal generalista de notícias tenha no máximo nota 4. Avaliar o corte por nota mínima (hoje a nota só reordena).
4. **Stopwords:** acrescentar youtube, mesa, domingo, palestra e congresso. Considerar stopwords de títulos em inglês, que já são tratadas.
5. **Atalho imediato, sem código:** pôr os telejornais no `exclude.txt`.
6. **Decisão pendente G, múltiplas sementes** (`farejador.py @a @b @c`). Ajudaria exatamente aqui: com sementes de nicho parecido, os telejornais não se repetem entre elas. Trade-off: custo linear por semente (~80 requisições cada) e ranking somado por semente.
7. **deno.** Para a imagem Docker da fase 2, decidir se inclui o runtime JavaScript (imagem maior) ou se aceita o risco de o yt-dlp parar de ler os detalhes dos vídeos.

## Para retomar

- Rodar de novo usa o cache (7 dias): só as consultas novas vão à rede.
- Comparar com o modo determinístico: o mesmo comando com `--sem-llm`.
- Dados desta execução: `resultado.json`, `data/bruto/` e a tabela `eventos` de `data/farejador.db`.
