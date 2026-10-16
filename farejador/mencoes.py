"""Canais do YouTube citados (por link) nas descrições dos vídeos do canal de referência.

Só links contam: youtube.com/@handle, /channel/UC..., /c/nome, /user/nome. Um "@fulano" solto
no texto é ambíguo (pode ser Instagram, X...), então fica de fora.
"""
import re
from collections import defaultdict

from .palavras import sem_acento

RE_LINK = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?youtube\.com/(@[\w.\-]+|channel/UC[\w-]{22}|c/[\w.\-%]+|user/[\w.\-]+)",
    re.IGNORECASE,
)

# canal citado em quase todos os vídeos = rodapé fixo (canal secundário do próprio criador)
FRACAO_RODAPE = 0.8
MIN_VIDEOS_RODAPE = 5


def _normalizar(caminho):
    caminho = caminho.rstrip(".-_")
    if caminho.startswith("@"):
        return caminho.lower(), f"https://www.youtube.com/{caminho}"
    tipo, valor = caminho.split("/", 1)
    if tipo.lower() == "channel":
        return valor, f"https://www.youtube.com/channel/{valor}"
    return f"{tipo.lower()}/{valor.lower()}", f"https://www.youtube.com/{tipo.lower()}/{valor}"


def extrair(videos):
    """{chave: {"url", "videos": set(ids)}} — conta vídeos distintos, não repetições."""
    achados = defaultdict(lambda: {"url": None, "videos": set()})
    for v in videos:
        for caminho in RE_LINK.findall(v.get("descricao") or ""):
            chave, url = _normalizar(caminho)
            achados[chave]["url"] = achados[chave]["url"] or url
            achados[chave]["videos"].add(v.get("id"))
    return dict(achados)


def _compacto(t):
    return re.sub(r"\W", "", sem_acento((t or "").lower()))


def parece_do_criador(texto, nome_ref, handle_ref):
    """Handle/nome do citado contém o nome ou o @handle do canal de referência ("@cafebrasilcortes")."""
    alvo = _compacto(texto.lstrip("@"))
    refs = [r for r in (_compacto(nome_ref), _compacto((handle_ref or "").lstrip("@"))) if len(r) >= 6]
    return any(r in alvo for r in refs)


def filtrar(achados, total_videos, chaves_ref, nome_ref, handle_ref):
    """Separa (validos, ignorados). ignorados: [(chave, motivo)]."""
    validos, ignorados = {}, []
    for chave, m in achados.items():
        n = len(m["videos"])
        if chave in chaves_ref:
            ignorados.append((chave, "é o próprio canal"))
        elif parece_do_criador(chave.split("/")[-1], nome_ref, handle_ref):
            ignorados.append((chave, "parece canal do próprio criador"))
        elif total_videos >= MIN_VIDEOS_RODAPE and n >= FRACAO_RODAPE * total_videos:
            ignorados.append((chave, f"rodapé fixo (em {n}/{total_videos} descrições)"))
        else:
            validos[chave] = m
    return validos, ignorados
