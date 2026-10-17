"""Cookies do YouTube para o yt-dlp (opcional), no mesmo esquema do MeTube.

- Enviado pela tela/API: fica em <dados>/cookies.txt, permissão 600, gravado de forma atômica.
- Configurado: FAREJADOR_COOKIES aponta um arquivo no formato Netscape (cookies.txt).
- O enviado tem prioridade sobre o configurado (como no MeTube); apagar só remove o enviado.

O yt-dlp regrava o arquivo ao fim de cada extração (cookies renovados pelo YouTube), por isso ele
precisa ser gravável pelo usuário do container. O conteúdo nunca é devolvido pela API.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

LIMITE_BYTES = 1024 * 1024  # mesmo teto do MeTube
NOME = "cookies.txt"


class CookiesInvalidos(ValueError):
    pass


def enviado(cfg):
    return cfg.caminho("dados") / NOME


def configurado(cfg):
    return cfg.caminho("cookies") if cfg.cookies.strip() else None


def ativo(cfg):
    """(caminho, origem) do arquivo que o yt-dlp vai usar, ou (None, None)."""
    if enviado(cfg).is_file():
        return enviado(cfg), "enviado"
    c = configurado(cfg)
    if c is not None and c.is_file():
        return c, "configurado"
    return None, None


def validar(conteudo):
    """Aceita só o formato Netscape com ao menos um cookie do YouTube/Google."""
    if not conteudo:
        raise CookiesInvalidos("arquivo vazio")
    if len(conteudo) > LIMITE_BYTES:
        raise CookiesInvalidos("arquivo maior que 1 MB")
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        raise CookiesInvalidos("o arquivo não é texto (esperado cookies.txt no formato Netscape)")
    linhas = []
    for linha in texto.splitlines():
        if linha.startswith("#HttpOnly_"):
            linha = linha[len("#HttpOnly_"):]
        elif not linha.strip() or linha.startswith("#"):
            continue
        partes = linha.split("\t")
        if len(partes) != 7:
            raise CookiesInvalidos("formato inválido: cada cookie deve ter 7 campos separados por TAB (Netscape)")
        linhas.append(partes)
    if not any(p[0].lstrip(".").endswith(("youtube.com", "google.com")) for p in linhas):
        raise CookiesInvalidos("nenhum cookie de youtube.com no arquivo")
    return len(linhas)


def salvar(cfg, conteudo):
    """Valida e grava em <dados>/cookies.txt (600). Retorna quantos cookies o arquivo tem."""
    n = validar(conteudo)
    destino = enviado(cfg)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(NOME + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(conteudo)
    os.chmod(tmp, 0o600)
    os.replace(tmp, destino)
    return n


def apagar(cfg):
    """Remove o enviado. Retorna False se não havia enviado (o configurado não é tocado)."""
    p = enviado(cfg)
    if not p.is_file():
        return False
    p.unlink()
    return True


def estado(cfg):
    caminho, origem = ativo(cfg)
    d = {"ativo": caminho is not None, "origem": origem,
         "configurado": str(configurado(cfg)) if configurado(cfg) else None}
    if caminho is not None:
        st = Path(caminho).stat()
        d["bytes"] = st.st_size
        d["modificado"] = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")
    if origem == "enviado" and configurado(cfg) and configurado(cfg).is_file():
        d["aviso"] = "o arquivo enviado tem prioridade sobre FAREJADOR_COOKIES, que não está sendo usado"
    return d
