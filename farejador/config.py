"""Configuração: variáveis de ambiente FAREJADOR_* com override pela CLI."""
import os
from dataclasses import dataclass, fields
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    pausa: float = 2.5                # segundos entre requisições ao YouTube
    max_buscas: int = 8               # quantas buscas ytsearch fazer
    resultados_por_busca: int = 20    # vídeos por busca
    videos_referencia: int = 30       # últimos vídeos lidos do canal de referência
    detalhes_videos: int = 5          # vídeos do canal de referência abertos por completo (tags/descrição)
    verificar_atividade: int = 10     # top N candidatos com atividade checada no canal
    dias_ativo: int = 60              # janela de "atividade recente"
    cache_horas: float = 168          # validade do cache (0 = nunca expira)
    tentativas: int = 3               # tentativas por requisição em erro transitório
    backoff: float = 5.0              # base do backoff exponencial (s)
    top: int = 20                     # linhas exibidas na tabela
    dados: str = "data"               # pasta do SQLite e cache do yt-dlp
    exclude: str = "exclude.txt"
    saida: str = "resultado.json"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        cfg = cls()
        for f in fields(cls):
            valor = env.get(f"FAREJADOR_{f.name.upper()}")
            if valor not in (None, ""):
                setattr(cfg, f.name, type(getattr(cfg, f.name))(valor))
        return cfg

    def caminho(self, nome):
        """Resolve caminhos relativos dentro da pasta do projeto, nunca fora dela por acaso."""
        p = Path(getattr(self, nome))
        return p if p.is_absolute() else RAIZ / p
