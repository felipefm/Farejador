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


def tokens(texto, extras_stop=frozenset()):
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
        if chave in STOP_NORM or chave in extras_stop:
            continue
        saida.append((chave, w))
    return saida


def _bigramas(toks):
    return [(f"{a[0]} {b[0]}", f"{a[1]} {b[1]}") for a, b in zip(toks, toks[1:]) if a[0] != b[0]]


def extrair(videos, tags_canal=(), descricao_canal="", ignorar=(), limite=15):
    """Retorna (unigramas, frases) ordenados por relevância.

    videos: [{"titulo": str, "tags": [str]}]
    ignorar: textos cujas palavras devem sumir (nome/handle do próprio canal).
    Cada item: {"termo", "chave", "score", "videos"}.
    """
    extras = {c for t in ignorar for c, _ in tokens(t.replace("@", " "))}
    # o handle costuma ser uma palavra só ("@canaldojoao"); some com ele inteiro também
    extras |= {sem_acento(t.lower().lstrip("@")) for t in ignorar if t}

    score = Counter()
    df = Counter()
    forma = defaultdict(Counter)
    score_f = Counter()
    df_f = Counter()
    forma_f = defaultdict(Counter)

    for v in videos:
        uni, frases = set(), set()
        for c, w in tokens(v.get("titulo", ""), extras):
            uni.add(c)
            forma[c][w] += 1
        for c, w in _bigramas(tokens(v.get("titulo", ""), extras)):
            frases.add(c)
            forma_f[c][w] += 1
        uni_tag = set()
        for tag in v.get("tags") or []:
            toks = tokens(tag, extras)
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

    # tags do canal: o dono descrevendo o próprio assunto, sinal forte
    for tag in tags_canal:
        toks = tokens(tag, extras)
        for c, w in toks:
            score[c] += 2.0
            forma[c][w] += 1
        if 2 <= len(toks) <= 3:
            c = " ".join(t[0] for t in toks)
            score_f[c] += 2.0
            df_f[c] += 1
            forma_f[c][" ".join(t[1] for t in toks)] += 1
    for c, w in tokens(descricao_canal, extras):
        if c in score:
            score[c] += 0.5

    def montar(sc, dfs, formas, minimo):
        itens = [
            {"chave": c, "termo": formas[c].most_common(1)[0][0], "score": round(s, 2), "videos": dfs[c]}
            for c, s in sc.items() if s >= minimo and formas[c]
        ]
        itens.sort(key=lambda x: (-x["score"], -x["videos"], x["chave"]))
        return itens[:limite]

    # palavra/frase em um único vídeo é acaso, não tema do canal
    return montar(score, df, forma, 1.5), montar(score_f, df_f, forma_f, 2.0)
