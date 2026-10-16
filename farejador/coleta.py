"""Acesso ao YouTube via yt-dlp: pausa entre requisições, cache, retry com backoff e log de erros."""
import time

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError

# Trechos de mensagens do yt-dlp e o que significam para nós.
SINAIS_BLOQUEIO = ("sign in to confirm", "not a bot", "http error 429", "too many requests", "rate-limit", "rate limit")
SINAIS_TRANSITORIO = ("http error 5", "timed out", "timeout", "connection", "temporarily")
SINAIS_PERMANENTE = (
    "does not exist", "not available", "unavailable", "does not have a", "http error 404", "private video",
    "has been terminated", "members-only", "join this channel", "age-restricted", "unsupported url",
)


class BloqueioYouTube(RuntimeError):
    """O YouTube recusou (anti-bot / 429). Insistir só piora; o usuário precisa intervir."""


def classificar(mensagem):
    m = mensagem.lower()
    if any(s in m for s in SINAIS_BLOQUEIO):
        return "bloqueio"
    if any(s in m for s in SINAIS_TRANSITORIO):
        return "transitorio"
    if any(s in m for s in SINAIS_PERMANENTE):
        return "permanente"
    return "transitorio"


class _Logger:
    """Encaminha avisos do yt-dlp para a tabela de eventos (útil para entender mudanças do YouTube)."""

    def __init__(self, cache, alvo):
        self.cache, self.alvo = cache, alvo

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.cache.evento("aviso", "ytdlp", self.alvo, msg)

    def error(self, msg):
        pass  # o erro chega como exceção e é registrado em _extrair


def _ydl_padrao(opcoes):
    return YoutubeDL(opcoes)


class Coletor:
    def __init__(self, cfg, cache, fabrica_ydl=_ydl_padrao, dormir=time.sleep, relogio=time.monotonic):
        self.cfg = cfg
        self.cache = cache
        self.fabrica_ydl = fabrica_ydl
        self.dormir = dormir
        self.relogio = relogio
        self._ultima = None
        self.requisicoes = 0
        self.acertos_cache = 0

    # ---------------------------------------------------------------- núcleo
    def _opcoes(self, alvo, extras):
        opcoes = {
            "quiet": True,
            "no_warnings": False,
            "skip_download": True,
            "noprogress": True,
            "extract_flat": "in_playlist",
            "socket_timeout": 20,
            "retries": 1,
            "cachedir": str(self.cfg.caminho("dados") / "yt-dlp-cache"),
            # datas relativas ("3 weeks ago") viram timestamp aproximado nos resultados flat
            "extractor_args": {"youtubetab": {"approximate_date": [""]}},
            "logger": _Logger(self.cache, alvo),
        }
        opcoes.update(extras or {})
        return opcoes

    def _esperar_vez(self):
        if self._ultima is not None:
            falta = self.cfg.pausa - (self.relogio() - self._ultima)
            if falta > 0:
                self.dormir(falta)
        self._ultima = self.relogio()

    def _extrair(self, chave, url, extras=None):
        """Retorna o info dict bruto, ou None em erro permanente/esgotado (fica registrado em eventos)."""
        ultimo_erro = None
        for tentativa in range(1, self.cfg.tentativas + 1):
            self._esperar_vez()
            self.requisicoes += 1
            try:
                with self.fabrica_ydl(self._opcoes(url, extras)) as ydl:
                    info = ydl.extract_info(url, download=False)
                info = ydl.sanitize_info(info) if hasattr(ydl, "sanitize_info") else info
                self.cache.evento("info", "rede", url, "ok", tentativa)
                return info
            except (DownloadError, ExtractorError) as e:
                ultimo_erro = str(e)
                tipo = classificar(ultimo_erro)
                self.cache.evento("erro", tipo, url, ultimo_erro, tentativa)
                if tipo == "permanente":
                    self.cache.put(chave, {"info": None, "erro": ultimo_erro})  # não repetir
                    return None
                if tipo == "bloqueio" and tentativa >= 2:
                    raise BloqueioYouTube(ultimo_erro) from e
                if tentativa < self.cfg.tentativas:
                    espera = self.cfg.backoff * (2 ** (tentativa - 1)) * (3 if tipo == "bloqueio" else 1)
                    self.dormir(espera)
        if classificar(ultimo_erro or "") == "bloqueio":
            raise BloqueioYouTube(ultimo_erro)
        return None

    def _com_cache(self, chave, url, reduzir, extras=None):
        """Busca na rede (se preciso), reduz o resultado aos campos úteis e guarda já reduzido."""
        guardado = self.cache.get(chave)
        if guardado is not None:
            self.acertos_cache += 1
            return guardado.get("info")
        bruto = self._extrair(chave, url, extras)
        if bruto is None:
            return None
        info = reduzir(bruto)
        self.cache.put(chave, {"info": info})
        return info

    # ---------------------------------------------------------------- consultas
    def canal(self, base, n):
        """Últimos n vídeos (flat) + metadados do canal: nome, ID, @handle, descrição, tags."""
        return self._com_cache(f"canal:{base}:{n}", f"{base}/videos", _reduzir_canal, {"playlistend": n})

    def destaques(self, url):
        """Entradas de canal encontradas numa aba (canais/início). Lista vazia se nada."""
        return self._com_cache(f"destaques:{url}", url, _reduzir_destaques, {"playlistend": 100})

    def buscar(self, consulta, n):
        return self._com_cache(f"busca:{n}:{consulta.lower()}", f"ytsearch{n}:{consulta}", _reduzir_busca)

    def video(self, video_id):
        """Extração completa de um vídeo (tags, descrição, data). Mais pesada; usar com parcimônia."""
        extras = {"extract_flat": False, "ignore_no_formats_error": True}
        return self._com_cache(f"video:{video_id}", f"https://www.youtube.com/watch?v={video_id}",
                               _reduzir_video, extras)


# -------------------------------------------------------------------- redução dos info dicts
def _entrada_video(e):
    return {
        "id": e.get("id"),
        "titulo": e.get("title") or "",
        "descricao": e.get("description") or "",
        "timestamp": e.get("timestamp"),
        "views": e.get("view_count"),
        "duracao": e.get("duration"),
        "channel_id": e.get("channel_id"),
        "canal": e.get("channel") or e.get("uploader"),
        "handle": e.get("uploader_id") if str(e.get("uploader_id") or "").startswith("@") else None,
    }


def _reduzir_canal(info):
    entradas = [e for e in (info.get("entries") or []) if e]
    return {
        "channel_id": info.get("channel_id"),
        "nome": info.get("channel") or info.get("uploader") or info.get("title"),
        "handle": info.get("uploader_id") if str(info.get("uploader_id") or "").startswith("@") else None,
        "url": info.get("channel_url"),
        "descricao": info.get("description") or "",
        "tags": info.get("tags") or [],
        "seguidores": info.get("channel_follower_count"),
        "videos": [_entrada_video(e) for e in entradas],
    }


def _reduzir_busca(info):
    return [_entrada_video(e) for e in (info.get("entries") or []) if e and e.get("channel_id")]


def _reduzir_destaques(info):
    canais, links = [], []
    for e in info.get("entries") or []:
        if not e:
            continue
        url = e.get("url") or ""
        # entrada de canal: tem channel_id e não é vídeo/playlist
        if e.get("ie_key") == "YoutubeTab" and e.get("channel_id") and "/playlist" not in url:
            canais.append({
                "channel_id": e.get("channel_id"),
                "nome": e.get("channel") or e.get("title"),
                "handle": e.get("uploader_id"),
                "url": e.get("channel_url") or url,
            })
        elif "/channels" in url:
            links.append(url)  # prateleira "Canais em destaque" que aponta para outra página
    return {"canais": canais, "links": links, "dono": info.get("channel_id")}


def _reduzir_video(info):
    return {
        "id": info.get("id"),
        "tags": info.get("tags") or [],
        "descricao": info.get("description") or "",
        "upload_date": info.get("upload_date"),
        "timestamp": info.get("timestamp"),
    }
