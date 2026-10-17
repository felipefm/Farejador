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

## Comparativo: @SERTECMANUTENCAO (eletrônica, canal de nicho)

Qualidade aparente: **bem melhor**, mas só você confirma. Os 20 nomes da lista principal são, quase todos, canais de eletrônica ou elétrica (Global Tec Brasil, Electrolab, Eletrônica Brothers, Eletrônica Fácil, JuliaLabs, WR Kits…).

- **O LLM agregou:** rebaixou Manual do Mundo (score 70, o mais alto, nota 3: ciência geral), BRODIG TV e Comprou Avaliou (nota 2: generalistas).
- **Leitura:** em canal de nicho técnico, as palavras-chave funcionam. Em canal generalista de comentário, com amostra recente enviesada (Café Brasil), o pipeline falha.
- **Custo:** 78 requisições e cerca de 6 min (detalhes 82 s, checagem de atividade 59 s, LLM 148 s para 15 notas, ~10 s cada).

### BUG confirmado: os títulos da lista de vídeos vêm traduzidos para o inglês

Comparei `data/bruto/canal_*` (lista flat) com `data/bruto/video_*` (extração completa) nos 30 vídeos do Sertec. **Os 30 diferem.** O flat traz "Happy Teacher's Day" onde o original é "Feliz dia do Professor", e "Mastering Switch-Mode Power Supply Repair" onde o original é "Domine o reparo em Fontes Chaveadas". O YouTube entrega a tradução automática porque o yt-dlp pede a página em inglês. Isso explica:

- buscas por título em inglês ("AstroAI Smart Digital Multimeter MUS10KRD", "Happy Teacher's Day");
- palavras-chave e frases mistas ("electronic components" ao lado de "componentes eletrônicos"), que dividem a contagem por vídeo;
- no Café Brasil, os títulos "The challenges of marketing in agribusiness" etc. O viés para ANDAV/eleição continua valendo, mas o idioma também atrapalhou.

**Correção proposta:** usar o título da extração completa, que já é feita para os 30 vídeos. É preciso guardar `title` em `_reduzir_video` e versionar a chave do cache (`video2:`), o que custa reler os 30 vídeos uma vez por canal já em cache.

Alternativa descartada: pedir o YouTube em português (`lang=pt`). Isso quebraria as datas aproximadas, que o yt-dlp só sabe ler em inglês ("3 weeks ago") e das quais depende a checagem de atividade.

Os títulos dos candidatos (nos resultados de busca e nas abas Vídeos), que vão para o LLM, provavelmente também vêm em inglês. Corrigir isso custaria 1 extração completa por vídeo; não vale. O LLM lida bem com títulos traduzidos.

### Outros problemas vistos no Sertec

- **Título sem palavra-chave virou busca** ("Happy Teacher's Day"). Exigir pelo menos uma palavra-chave no título escolhido.
- **Bloco de tags repetido infla frases:** "filtro linha", "filtro linha ferro", "filtro linha gamer" e "filtro linha metal", todas em 6 vídeos. Descartar a frase que só estende outra com a mesma contagem.
- **5 candidatos ficaram sem nota** (MW Informática, Ser Eletricista, WR Kits, Tech em 10, Zoide Tech) pelo limite de 15 e afundaram para 2,9. A normalização divide pelo maior score, que era o Manual do Mundo (70, rebaixado pelo LLM), e isso comprime todo mundo. Opções: subir `FAREJADOR_LLM_AVALIAR` para 20 ou normalizar pelo percentil 90.
- **2 canais "só menção" ficaram ocultos** (@abstratoeletronica, @dktecnologia-s9g). Vale olhar com `--mostrar-fracos`; é a decisão pendente sobre menção valer 2 sinais.
- **Cosmético:** "(tudo contido em 'sertecmanutencao')" aparece duas vezes, porque o nome e o handle compactados coincidem. Remover a duplicata.
- O `--ignorar-termos` do Café Brasil foi reaproveitado aqui; não teve efeito.

## Fechamento da fase 1 (2026-10-17): implementado, aguardando o teste prático

Escolha: grupo A + playlists.

- [x] Título original da extração completa no lugar do traduzido (cache `video2:`; relê os 30 vídeos uma vez por canal).
- [x] Playlists da aba Início na amostra (até 6 × 15 títulos, pedidos em `FAREJADOR_IDIOMA=pt`), também no prompt e no perfil do LLM.
- [x] Título sem palavra-chave não vira busca.
- [x] Frase que só estende outra pelo menos tão frequente é descartada.
- [x] Stopwords novas: youtube, mesa, domingo, palestra.
- [x] "(tudo contido em …)" sem duplicata.
- [x] Teste prático (2026-10-17) com @LucianoPiresCafeBrasil, @SERTECMANUTENCAO e @DisneyDesenhos: Sertec e Disney bons; Café Brasil ruim (nomes de série e patrocinador nas playlists; canal eclético). O LLM deu de 1 a 5 a todos os candidatos do Café Brasil.
- [x] Corte opcional por nota (`FAREJADOR_LLM_NOTA_MIN`) e normalização pelo percentil 90 + média das notas para quem não foi avaliado.
- [ ] Você confirma a aprovação da fase 1.

Ficam para depois da fase 1, se você quiser: detectar nomes de série e patrocinador (Café Brasil), bloco de tags presente em 100% dos vídeos (Disney), penalidade de tamanho, ajuste do prompt do LLM (nota máxima para canal generalista), menção valendo 2 sinais, `FAREJADOR_LLM_AVALIAR` 20 e múltiplas sementes (G). O deno vai para a fase 2.

## Propostas, por prioridade (aguardando decisão)

0. **Corrigir os títulos traduzidos** (bug acima): mudança pequena, custa reler os detalhes uma vez.
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
