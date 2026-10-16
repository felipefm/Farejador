"""Monta consultas a partir das palavras-chave e agrega os canais que aparecem nos resultados."""
from itertools import combinations


def montar_consultas(unigramas, frases, limite):
    """Frases recorrentes primeiro (mais específicas), depois pares das palavras do topo.

    Palavra solta é evitada: "receita" sozinha devolve o YouTube inteiro.
    """
    consultas, cobertas = [], []

    def add(texto, chaves):
        if len(consultas) >= limite or texto in consultas:
            return
        # pula se repete exatamente as palavras de uma consulta já feita
        if any(chaves <= c for c in cobertas):
            return
        consultas.append(texto)
        cobertas.append(chaves)

    for f in frases[: max(1, (limite + 1) // 2)]:
        add(f["termo"], set(f["chave"].split()))
    top = unigramas[:7]
    for a, b in combinations(top, 2):
        add(f"{a['termo']} {b['termo']}", {a["chave"], b["chave"]})
    for u in top:  # último recurso, se faltaram combinações
        add(u["termo"], {u["chave"]})
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
