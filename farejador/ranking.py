"""Pontuação dos candidatos, com o motivo de cada ponto à vista."""
import time

PESO_BUSCA = 10       # por busca distinta em que o canal apareceu (sinal principal)
PESO_VIDEO_EXTRA = 1  # por vídeo extra nos resultados, até o teto abaixo
TETO_VIDEO_EXTRA = 5
BONUS_DESTAQUE = 15   # canal em destaque no canal de referência
BONUS_ATIVO = 5
PENALIDADE_INATIVO = -10

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


def pontuar(c, total_buscas, dias):
    pontos, motivos = 0, []
    n = len(c.get("consultas", []))
    if n:
        pontos += PESO_BUSCA * n
        motivos.append(f"apareceu em {n}/{total_buscas} buscas ({', '.join(repr(q) for q in c['consultas'])})")
    extra = min(TETO_VIDEO_EXTRA, max(0, len(c.get("videos", [])) - 1))
    if extra:
        pontos += PESO_VIDEO_EXTRA * extra
        motivos.append(f"+{extra} por ter {len(c['videos'])} vídeos nos resultados")
    if c.get("destaque"):
        pontos += BONUS_DESTAQUE
        motivos.append("em destaque no canal de referência")
    estado = c.get("atividade", "desconhecido")
    if estado == "ativo":
        pontos += BONUS_ATIVO
        motivos.append(f"publicou nos últimos {dias} dias")
    elif estado == "inativo":
        pontos += PENALIDADE_INATIVO
        motivos.append(f"sem vídeo nos últimos {dias} dias")
    else:
        motivos.append("atividade não verificada")
    c["score"] = pontos
    c["motivo"] = "; ".join(motivos)
    return c


def ordenar(candidatos):
    return sorted(candidatos, key=lambda c: (-c["score"], -len(c.get("consultas", [])), (c.get("nome") or "").lower()))
