"""Normalização de identificadores de canal (@handle, ID UC..., URL) e lista de exclusão."""
import re
from pathlib import Path

YT = "https://www.youtube.com"
RE_ID = re.compile(r"^UC[\w-]{22}$")
ABAS = ("videos", "featured", "channels", "shorts", "streams", "playlists", "about", "community", "podcasts")


def url_base(entrada):
    """Converte @handle, ID ou URL de canal na URL base do canal (sem aba)."""
    s = entrada.strip()
    if not s:
        raise ValueError("canal vazio")
    if RE_ID.match(s):
        return f"{YT}/channel/{s}"
    if s.startswith("@"):
        return f"{YT}/{s}"
    if "youtube.com" in s or "youtu.be" in s:
        if not s.startswith("http"):
            s = "https://" + s
        s = s.split("?")[0].split("#")[0].rstrip("/")
        partes = s.split("/")
        if partes[-1] in ABAS:
            partes = partes[:-1]
        s = "/".join(partes)
        return s.replace("://youtube.com", "://www.youtube.com").replace("://m.youtube.com", "://www.youtube.com")
    if re.match(r"^[\w.-]+$", s):
        return f"{YT}/@{s}"
    raise ValueError(f"não reconheço como canal: {entrada!r}")


def chaves(entrada):
    """Formas comparáveis de um identificador: ID UC..., @handle em minúsculas."""
    s = entrada.strip()
    if not s or s.startswith("#"):
        return set()
    try:
        base = url_base(s)
    except ValueError:
        return set()
    ultimo = base.rstrip("/").split("/")[-1]
    if ultimo.startswith("@"):
        return {ultimo.lower()}
    if RE_ID.match(ultimo):
        return {ultimo}
    return {base.lower()}  # /c/nome ou /user/nome: compara pela URL


def chaves_do_canal(channel_id=None, handle=None, url=None):
    k = set()
    if channel_id:
        k.add(channel_id)
    if handle:
        k.add(handle.lower() if handle.startswith("@") else "@" + handle.lower())
    if url:
        k |= chaves(url)
    return k


def ler_exclusoes(caminho):
    p = Path(caminho)
    if not p.exists():
        return set()
    k = set()
    for linha in p.read_text(encoding="utf-8").splitlines():
        k |= chaves(linha.split("#")[0])  # aceita comentários com #
    return k
