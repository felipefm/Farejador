"""Extração de palavras-chave de títulos e tags, sem bibliotecas pesadas.

Ideia: uma palavra é relevante se aparece em MUITOS vídeos diferentes do canal
(frequência por documento), não se aparece muitas vezes num só título.
"""
import re
import unicodedata
from collections import Counter, defaultdict

STOP_PT = """
a à ao aos as às até com como contra da das de dela dele deles do dos e é ela elas ele eles em entre era
essa essas esse esses esta está estão estas este estes eu foi for há isso isto já la lá lhe mais mas me
mesmo meu minha muito na nas não nem no nos nós num numa o os ou para pela pelas pelo pelos por porque
qual quando que quem se sem ser seu sua são só também te tem têm tu tua um uma umas uns você vocês vai
vão ter tá to pra pro pras pros aqui ali onde sobre depois antes ainda cada todo toda todos todas
fazer faz fiz feito fica ficou tudo nada algo alguém coisa coisas vez vezes ano anos dia dias hoje agora
melhor melhores maior pior novo nova novos novas bom boa grande primeiro primeira parte
""".split()

STOP_EN = """
a about after all also an and any are as at be been but by can could did do does for from get got had
has have he her his how i if in into is it its just like me more most my new no not now of on one only
or our out over she so some than that the their them then there these they this to too up us very was
we were what when where which who why will with would you your vs best top first make made way back
""".split()

# Ruído típico de títulos do YouTube: não descreve o assunto do canal.
GENERICAS = """
video videos vídeo vídeos canal channel inscreva inscrevase subscribe like likes comenta comente
ep episodio episódio episode parte part cap capitulo capítulo live ao vivo shorts short official oficial
full completo completa trailer teaser react reagindo reação reaction review news noticias notícias
hd 4k official vlog clip clipe compilation compilação especial special edition versão version
""".split()

STOPWORDS = {unicodedata.normalize("NFC", w) for w in STOP_PT + STOP_EN + GENERICAS}
RE_PALAVRA = re.compile(r"[\w']+", re.UNICODE)


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


STOP_NORM = {sem_acento(w) for w in STOPWORDS}


class Ignorados:
    """Termos que não podem virar palavra-chave: nome/@handle do canal e a lista do usuário.

    O @handle costuma vir colado ("@LucianoPiresCafeBrasil"), então qualquer token com
    4+ letras contido nele também é ignorado ("cafe", "brasil", "pires").
    """

    def __init__(self, nome="", handle="", extras=()):
        self.tokens = set()
        for texto in [nome, *extras]:
            self.tokens |= {c for c, _ in tokens(texto)}
            self.tokens.add(sem_acento(texto.lower().strip()))
        self.colados = [sem_acento(t.lower()) for t in (handle.lstrip("@"), re.sub(r"\W", "", nome)) if len(t) >= 4]

    def __contains__(self, chave):
        if chave in self.tokens:
            return True
        return len(chave) >= 4 and any(chave in c for c in self.colados)

    def lista(self):
        return sorted(t for t in self.tokens if t) + [f"(tudo contido em '{c}')" for c in self.colados]



def tokens(texto, ignorar=frozenset()):
    """Lista de (chave_normalizada, forma_original) sem stopwords, números puros ou tokens curtos."""
    saida = []
    for bruto in RE_PALAVRA.findall(texto.lower().replace("_", " ")):
        w = bruto.strip("'")
        chave = sem_acento(w)
        if not chave or chave.isdigit():
            continue
        tem_digito = any(c.isdigit() for c in chave)
        if len(chave) < 3 and not tem_digito:  # mantém "f1", "ps5"
            continue
        if chave in STOP_NORM or chave in ignorar:
            continue
        saida.append((chave, w))
    return saida


SEM_IGNORADOS = Ignorados()


def _bigramas(toks):
    return [(f"{a[0]} {b[0]}", f"{a[1]} {b[1]}") for a, b in zip(toks, toks[1:]) if a[0] != b[0]]


def extrair(videos, tags_canal=(), descricao_canal="", ignorar=SEM_IGNORADOS, min_videos=3, limite=15):
    """Retorna (unigramas, frases) ordenados por relevância.

    videos: [{"titulo": str, "tags": [str]}]. Só títulos e tags dos vídeos contam como evidência:
    um termo/frase precisa estar em `min_videos` vídeos distintos. Tags e descrição do canal só
    reforçam termos que já passaram nesse corte (descrições de vídeo ficam de fora: são cheias de
    rodapé repetido — patrocínio, redes sociais).
    Cada item: {"termo", "chave", "score", "videos"}.
    """
    score, df, forma = Counter(), Counter(), defaultdict(Counter)
    score_f, df_f, forma_f = Counter(), Counter(), defaultdict(Counter)

    for v in videos:
        toks_titulo = tokens(v.get("titulo", ""), ignorar)
        uni = {c for c, _ in toks_titulo}
        for c, w in toks_titulo:
            forma[c][w] += 1
        frases = set()
        for c, w in _bigramas(toks_titulo):
            frases.add(c)
            forma_f[c][w] += 1
        uni_tag = set()
        for tag in v.get("tags") or []:
            toks = tokens(tag, ignorar)
            for c, w in toks:
                uni_tag.add(c)
                forma[c][w] += 1
            if 2 <= len(toks) <= 3:
                c = " ".join(t[0] for t in toks)
                frases.add(c)
                forma_f[c][" ".join(t[1] for t in toks)] += 1
        for c in uni:
            score[c] += 1.0
        for c in uni_tag - uni:
            score[c] += 0.7  # tag vale um pouco menos que título (tags costumam ser genéricas)
        for c in uni | uni_tag:
            df[c] += 1
        for c in frases:
            score_f[c] += 1.0
            df_f[c] += 1

    # tags do canal: o dono descrevendo o próprio assunto; reforço, não evidência
    for tag in tags_canal:
        toks = tokens(tag, ignorar)
        for c, _ in toks:
            score[c] += 2.0
        if 2 <= len(toks) <= 3:
            score_f[" ".join(t[0] for t in toks)] += 2.0
    for c in {c for c, _ in tokens(descricao_canal, ignorar)}:
        score[c] += 0.5

    def montar(sc, dfs, formas, peso):
        itens = [
            {"chave": c, "termo": formas[c].most_common(1)[0][0], "score": round(sc[c] * peso, 2), "videos": n}
            for c, n in dfs.items() if n >= min_videos and formas[c]
        ]
        itens.sort(key=lambda x: (-x["score"], -x["videos"], x["chave"]))
        return itens[:limite]

    return montar(score, df, forma, 1.0), montar(score_f, df_f, forma_f, 1.0)


SEPARADORES = re.compile(r"\s*[|•–—]\s*|\s+-\s+|\s*:\s+")


def limpar_titulo(titulo, ignorar=SEM_IGNORADOS):
    """Título pronto para busca: sem nome do canal/programa, números de episódio, hashtags e emojis.

    "Café Brasil 950 – O Fim da Verdade" -> "O Fim da Verdade". Fica com o maior trecho que sobra.
    """
    trechos = []
    for trecho in SEPARADORES.split(titulo):
        palavras = []
        for w in trecho.split():
            if w.startswith("#"):
                continue
            nucleo = RE_PALAVRA.findall(w.lower())
            if not nucleo:
                continue  # emoji/pontuação solta
            chave = sem_acento(nucleo[0].strip("'"))
            if chave.isdigit() or chave in ignorar or chave in {"ep", "episodio", "cap"}:
                continue
            palavras.append(w.strip("\"'“”()[]"))
        conteudo = [c for c, _ in tokens(" ".join(palavras), ignorar)]
        if palavras and len(conteudo) >= 2:
            trechos.append(" ".join(p for p in palavras if p))
    return max(trechos, key=len) if trechos else ""


def titulos_representativos(videos, unigramas, frases, ignorar=SEM_IGNORADOS, n=3, janela=15):
    """Até n títulos limpos, entre os `janela` vídeos mais recentes, que mais usam as palavras-chave."""
    chaves = {u["chave"] for u in unigramas}
    chaves_f = {f["chave"] for f in frases}
    candidatos = []
    for pos, v in enumerate(videos[:janela]):
        limpo = limpar_titulo(v.get("titulo", ""), ignorar)
        if not limpo:
            continue
        toks = [c for c, _ in tokens(limpo, ignorar)]
        bigr = {f"{a} {b}" for a, b in zip(toks, toks[1:])}
        pontos = len(set(toks) & chaves) + 2 * len(bigr & chaves_f)
        candidatos.append((-pontos, pos, limpo))
    candidatos.sort()
    escolhidos, conjuntos = [], []
    for _, _, limpo in candidatos:
        toks = {c for c, _ in tokens(limpo, ignorar)}
        # diversidade: título que repete metade das palavras de outro já escolhido gasta busca à toa
        if any(len(toks & o) >= 0.5 * len(toks | o) for o in conjuntos):
            continue
        escolhidos.append(limpo)
        conjuntos.append(toks)
        if len(escolhidos) == n:
            break
    return escolhidos
