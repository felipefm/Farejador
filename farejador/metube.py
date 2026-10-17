"""Adaptador de saída OPCIONAL para o MeTube (desligado com FAREJADOR_METUBE_URL vazio).

Formato lido do código do MeTube (app/main.py e app/format_catalog.py, out/2026):
- POST {base}/add       : url, download_type, quality obrigatórios; format, playlist_item_limit opcionais.
- POST {base}/subscribe : os mesmos campos + check_interval_minutes (opcional).
- download_type "video" com format "any" e quality "best" são os padrões do próprio MeTube.
- Erro de validação vem como HTTP 400; erro de fila pode vir como HTTP 200 com {"status": "error", "msg": ...}.

Mandar um canal para /add baixa o canal inteiro (o limite padrão do MeTube é 0 = tudo); por isso
o modo padrão é "assinar" (só vídeos novos) e o modo "baixar" sempre envia playlist_item_limit.
"""
import json
import time
import urllib.error
import urllib.request

MODOS = ("assinar", "baixar")


def ligado(cfg):
    return bool(cfg.metube_url.strip())


def montar_pedido(cfg, url_canal):
    """(endpoint, corpo) do pedido ao MeTube para um canal aprovado."""
    if cfg.metube_modo not in MODOS:
        raise ValueError(f"FAREJADOR_METUBE_MODO deve ser {' ou '.join(MODOS)}, não {cfg.metube_modo!r}")
    corpo = {"url": url_canal, "download_type": "video", "format": "any", "quality": cfg.metube_qualidade}
    if cfg.metube_modo == "baixar":
        corpo["playlist_item_limit"] = max(1, cfg.metube_limite)
        return "/add", corpo
    if cfg.metube_intervalo > 0:
        corpo["check_interval_minutes"] = cfg.metube_intervalo
    return "/subscribe", corpo


def enviar(cfg, url_canal, cache=None, abrir=urllib.request.urlopen, relogio=time.monotonic):
    """Envia o canal ao MeTube. Retorna (ok, mensagem). Nunca levanta exceção."""
    try:
        caminho, corpo = montar_pedido(cfg, url_canal)
    except ValueError as e:
        return False, str(e)
    url = cfg.metube_url.strip().rstrip("/") + caminho
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = relogio()
    try:
        with abrir(req, timeout=cfg.metube_timeout) as r:
            texto = r.read().decode("utf-8", "replace")
        ok, msg = _interpretar(texto)
    except urllib.error.HTTPError as e:
        corpo_erro = e.read().decode("utf-8", "replace")[:300] if hasattr(e, "read") else ""
        ok, msg = False, f"HTTP {e.code}: {corpo_erro or e.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        ok, msg = False, f"MeTube inacessível em {url}: {getattr(e, 'reason', e)}"
    ms = round((relogio() - t0) * 1000)
    if cache is not None:
        cache.evento("info" if ok else "erro", "metube" if ok else "metube_erro", url_canal, f"{msg} ({ms} ms)")
    return ok, msg


def _interpretar(texto):
    try:
        dados = json.loads(texto)
    except ValueError:
        return True, texto[:200] or "ok"
    if isinstance(dados, dict) and str(dados.get("status", "")).lower() == "error":
        return False, str(dados.get("msg") or dados)[:300]
    return True, "ok"
