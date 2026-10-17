"""Pontuação dos candidatos, com o motivo de cada ponto à vista.

Atividade não pontua: inativo é filtrado antes (ver descoberta). Quantidade de vídeos nos
resultados também não pontua: favorecia quem publica muito (grandes veículos), não quem é parecido.
"""
import time

PESO_BUSCA = 10        # por busca distinta em que o canal apareceu
PESO_MENCAO = 20       # citado (link) na descrição de 1 vídeo do canal de referência
PESO_MENCAO_EXTRA = 5  # por vídeo adicional que o cita
TETO_MENCAO = 40
BONUS_DESTAQUE = 15    # canal em destaque no canal de referência

# Canais automáticos/agregadores que quase nunca são o que se procura.
SUFIXOS_RUIDO = (" - topic", " - tema", "vevo")


def eh_ruido(nome):
    n = (nome or "").lower()
    return any(n.endswith(s) for s in SUFIXOS_RUIDO)


def atividade(timestamps, dias, agora=None):
    """'ativo' | 'inativo' | 'desconhecido', a partir das datas (aproximadas) de vídeos."""
    ts = [t for t in timestamps if t]
    if not ts:
        return "desconhecido"
    agora = agora or time.time()
    return "ativo" if agora - max(ts) <= dias * 86400 else "inativo"


def sinais(c):
    """Sinais independentes: cada busca distinta conta 1, menção conta 1, destaque conta 1."""
    return len(c.get("consultas", [])) + bool(c.get("mencoes")) + bool(c.get("destaque"))


def pontuar(c, total_buscas, dias):
    pontos, motivos = 0, []
    if m := c.get("mencoes"):
        pontos += min(TETO_MENCAO, PESO_MENCAO + PESO_MENCAO_EXTRA * (m - 1))
        motivos.append(f"citado em {m} vídeo{'s' if m > 1 else ''}")
    n = len(c.get("consultas", []))
    if n:
        pontos += PESO_BUSCA * n
        motivos.append(f"apareceu em {n}/{total_buscas} buscas ({', '.join(repr(q) for q in c['consultas'])})")
    if c.get("destaque"):
        pontos += BONUS_DESTAQUE
        motivos.append("em destaque no canal de referência")
    estado = c.get("atividade", "desconhecido")
    motivos.append(f"publicou nos últimos {dias} dias" if estado == "ativo" else "atividade não verificada")
    c["score"] = pontos
    c["sinais"] = sinais(c)
    c["motivo"] = "; ".join(motivos)
    return c


def ordenar(candidatos):
    return sorted(candidatos, key=lambda c: (-c["score"], -sinais(c), (c.get("nome") or "").lower()))


def _percentil_90(valores):
    v = sorted(valores)
    return v[max(0, -(-9 * len(v) // 10) - 1)] if v else 0


def combinar(candidatos, peso_llm):
    """Ordem final: (1 - peso) * score normalizado (0–10) + peso * nota do LLM (0–10).

    O score determinístico é normalizado pelo percentil 90 da lista (teto 10): um único canal com
    score muito alto (ex.: Manual do Mundo em 9 buscas) não comprime todos os outros perto de zero.
    Candidato sem nota (fora do limite de avaliados ou falha do LLM) recebe a média das notas dadas
    nesta execução: o desconhecido vale o típico, nem o melhor nem o pior. Sem nenhuma nota, usa o
    próprio score normalizado. Ordena a lista no lugar.
    """
    base = _percentil_90([c["score"] for c in candidatos]) or 1
    notas = [c["nota_llm"] for c in candidatos if c.get("nota_llm") is not None]
    media = sum(notas) / len(notas) if notas else None
    for c in candidatos:
        det = min(10.0, 10 * c["score"] / base)
        nota = c.get("nota_llm")
        if nota is None:
            nota = media if media is not None else det
        c["score_final"] = round((1 - peso_llm) * det + peso_llm * nota, 2)
    candidatos.sort(key=lambda c: (-c["score_final"], -c["score"], (c.get("nome") or "").lower()))
    return candidatos
