"""Configuração: variáveis de ambiente FAREJADOR_* com override pela CLI."""
import os
from dataclasses import dataclass, fields
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VERDADEIRO = ("1", "true", "sim", "yes", "on")


@dataclass
class Config:
    pausa: float = 2.5                # segundos entre requisições ao YouTube
    max_buscas: int = 8               # total de buscas ytsearch (títulos + frases + pares)
    buscas_titulos: int = 3           # quantas dessas buscas usam títulos de vídeos recentes
    resultados_por_busca: int = 20    # vídeos por busca
    videos_referencia: int = 30       # últimos vídeos lidos do canal de referência
    detalhes_videos: int = 30         # vídeos abertos por completo (descrição/tags): 1 requisição cada
    min_videos_termo: int = 3         # termo precisa aparecer em N vídeos distintos
    ignorar_termos: str = ""          # termos extras a ignorar, separados por vírgula
    max_mencoes: int = 15             # canais citados nas descrições validados via yt-dlp (1 req. cada)
    min_sinais: int = 2               # sinais independentes para entrar na lista principal
    verificar_atividade: int = 25     # máx. de candidatos com atividade checada na aba Vídeos
    dias_ativo: int = 60              # sem vídeo nesta janela = inativo (excluído)
    cache_horas: float = 168          # validade do cache (0 = nunca expira)
    tentativas: int = 3               # tentativas por requisição em erro transitório
    backoff: float = 5.0              # base do backoff exponencial (s)
    top: int = 20                     # linhas exibidas na tabela
    mostrar_fracos: bool = False      # mostra também candidatos com 1 sinal só
    verbose: bool = False             # custo em requisições por etapa e avisos do yt-dlp
    salvar_bruto: bool = False        # grava o retorno cru do yt-dlp em <dados>/bruto/
    dados: str = "data"               # pasta do SQLite e cache do yt-dlp
    exclude: str = "exclude.txt"
    saida: str = "resultado.json"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        cfg = cls()
        for f in fields(cls):
            valor = env.get(f"FAREJADOR_{f.name.upper()}")
            if valor in (None, ""):
                continue
            tipo = type(getattr(cfg, f.name))
            setattr(cfg, f.name, valor.strip().lower() in VERDADEIRO if tipo is bool else tipo(valor))
        return cfg

    def caminho(self, nome):
        """Resolve caminhos relativos dentro da pasta do projeto, nunca fora dela por acaso."""
        p = Path(getattr(self, nome))
        return p if p.is_absolute() else RAIZ / p

    def termos_ignorados(self):
        return [t.strip() for t in self.ignorar_termos.split(",") if t.strip()]
