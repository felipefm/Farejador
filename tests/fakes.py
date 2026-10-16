"""yt-dlp falso: responde a URLs a partir de um dicionário, sem rede."""
from yt_dlp.utils import DownloadError


class FakeYDL:
    def __init__(self, respostas, chamadas, opcoes):
        self.respostas, self.chamadas, self.opcoes = respostas, chamadas, opcoes

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        self.chamadas.append(url)
        r = self.respostas.get(url)
        if r is None:
            raise DownloadError(f"ERROR: [youtube] {url}: This video is unavailable")
        if isinstance(r, list):  # sequência de respostas (para testar retry)
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        for aviso in r.get("_avisos", []):  # simula warnings que o yt-dlp emite durante a extração
            self.opcoes["logger"].warning(aviso)
        return {k: v for k, v in r.items() if k != "_avisos"}


def fabrica(respostas):
    chamadas = []
    return (lambda opcoes: FakeYDL(respostas, chamadas, opcoes)), chamadas


class _Resp:
    def __init__(self, texto):
        self.texto = texto

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.texto.encode()


def chat(conteudo):
    """Corpo de resposta no formato /v1/chat/completions."""
    import json
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": conteudo}}]})


class FakeLLMServer:
    """Substitui urllib.request.urlopen. `responder(pedido_json, url)` devolve texto ou levanta exceção."""

    def __init__(self, responder):
        self.responder = responder
        self.pedidos = []

    def __call__(self, req, timeout=None):
        import json
        corpo = json.loads(req.data) if req.data else None
        self.pedidos.append({"url": req.full_url, "corpo": corpo, "timeout": timeout})
        return _Resp(self.responder(corpo, req.full_url))
