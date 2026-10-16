"""Monta consultas a partir das palavras-chave e agrega os canais que aparecem nos resultados."""
from itertools import combinations


def montar_consultas(unigramas, frases, limite, titulos=()):
    """Lista de (consulta, origem). Ordem de prioridade dentro do limite:

    1. títulos limpos de vídeos recentes representativos (até metade do limite);
    2. frases recorrentes (bigramas/tags em vários vídeos), mais específicas que palavras soltas;
    3. pares das palavras do topo; 4. palavra solta, só se ainda sobrar espaço.
    """
    consultas, cobertas = [], []

    def add(texto, chaves, origem):
        if len(consultas) >= limite or texto.lower() in (q.lower() for q, _ in consultas):
            return
        # pula se repete exatamente as palavras de uma consulta já feita
        if chaves and any(chaves <= c for c in cobertas):
            return
        consultas.append((texto, origem))
        if chaves:
            cobertas.append(chaves)

    for t in list(titulos)[: limite // 2]:
        add(t, set(), "título")  # título não "cobre" frases: a busca por frase é outra, mais ampla
    for f in frases:
        add(f["termo"], set(f["chave"].split()), "frase")
    top = unigramas[:7]
    for a, b in combinations(top, 2):
        add(f"{a['termo']} {b['termo']}", {a["chave"], b["chave"]}, "par")
    for u in top:
        add(u["termo"], {u["chave"]}, "palavra")
    return consultas


def agregar(resultados):
    """resultados: [(consulta, [entrada_video])] -> {channel_id: candidato}."""
    candidatos = {}
    for consulta, entradas in resultados:
        for e in entradas or []:
            cid = e.get("channel_id")
            if not cid:
                continue
            c = candidatos.setdefault(cid, {
                "channel_id": cid,
                "nome": e.get("canal"),
                "handle": e.get("handle"),
                "consultas": [],
                "videos": [],
                "timestamps": [],
            })
            c["nome"] = c["nome"] or e.get("canal")
            c["handle"] = c["handle"] or e.get("handle")
            if consulta not in c["consultas"]:
                c["consultas"].append(consulta)
            if e.get("titulo") and e["titulo"] not in c["videos"]:
                c["videos"].append(e["titulo"])
            if e.get("timestamp"):
                c["timestamps"].append(e["timestamp"])
    return candidatos
