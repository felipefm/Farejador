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
    max_playlists: int = 6            # playlists da aba Início lidas (1 requisição cada)
    videos_playlist: int = 15         # títulos lidos por playlist
    idioma: str = "pt"                # idioma pedido ao YouTube nas playlists (títulos flat vêm traduzidos)
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
    llm_url: str = ""                 # ex.: http://192.168.0.6:1234/v1 (vazio = LLM desligado)
    llm_model: str = ""               # vazio = primeiro modelo carregado no servidor
    llm_timeout: float = 60.0         # segundos por chamada ao LLM
    llm_max_buscas: int = 8           # consultas do LLM somadas às determinísticas
    llm_avaliar: int = 15             # candidatos da lista principal reavaliados pelo LLM
    llm_peso: float = 0.5             # peso da nota do LLM na ordem final (0 = ignora, 1 = só LLM)
    llm_nota_min: float = 0           # nota abaixo disso tira o candidato da lista principal (0 = sem corte)
    sem_llm: bool = False             # força o modo determinístico mesmo com LLM configurado
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
