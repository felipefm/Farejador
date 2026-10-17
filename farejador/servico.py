"""Descoberta em segundo plano: uma thread por vez, progresso e resultado gravados no SQLite.

Leve de propósito (homelab com pouca RAM): sem fila, sem processo extra. Se o processo reiniciar
no meio (inclusive pelo --reload ao mudar o código), a execução fica marcada como 'interrompida'
no próximo arranque.
"""
import threading
import traceback

from .cache import Cache
from .canais import ler_exclusoes
from .coleta import BloqueioYouTube, Coletor
from .descoberta import ErroCanal, descobrir
from .llm import LLM


class JaRodando(RuntimeError):
    pass


class Executor:
    def __init__(self, cfg, banco, descobrir_fn=descobrir, em_thread=True):
        self.cfg, self.banco, self.descobrir_fn, self.em_thread = cfg, banco, descobrir_fn, em_thread
        self._trava = threading.Lock()
        self._thread = None
        self.atual = None  # id da execução em andamento

    def rodando(self):
        return self.atual is not None

    def iniciar(self, sementes):
        if not sementes:
            raise ValueError("nenhuma semente para rodar")
        with self._trava:
            if self.atual is not None:
                raise JaRodando(f"descoberta {self.atual} ainda em andamento")
            id_ = self.banco.criar_execucao(sementes)
            self.atual = id_
        if self.em_thread:
            self._thread = threading.Thread(target=self._rodar, args=(id_, sementes), daemon=True,
                                            name=f"descoberta-{id_}")
            self._thread.start()
        else:
            self._rodar(id_, sementes)
        return id_

    def _rodar(self, id_, sementes):
        resumo, estado, erro = {}, "ok", None
        try:
            cache = Cache(self.cfg.caminho("dados") / "farejador.db", self.cfg.cache_horas)  # conexão desta thread
            coletor = Coletor(self.cfg, cache)
            for i, semente in enumerate(sementes, 1):
                llm = LLM(self.cfg, cache)  # por semente: um timeout numa não desliga o LLM nas outras
                prefixo = f"[{i}/{len(sementes)}] {semente}: "

                def log(m, detalhe=False):
                    if not detalhe:
                        self.banco.atualizar_execucao(id_, progresso=prefixo + m)

                # aprovados e descartados nunca voltam: entram na exclusão e não gastam busca/LLM
                exclusoes = ler_exclusoes(self.cfg.caminho("exclude")) | self.banco.chaves_decididas()
                try:
                    r = self.descobrir_fn(semente, self.cfg, coletor, exclusoes, log=log, llm=llm)
                except ErroCanal as e:
                    resumo[semente] = {"erro": str(e)}  # uma semente ruim não derruba as outras
                    continue
                novos = self.banco.gravar_candidatos(semente, r["candidatos"])
                resumo[semente] = {"candidatos": len(r["candidatos"]), "novos": novos, "avisos": r["avisos"],
                                   "requisicoes": r["requisicoes"], "consultas": len(r["consultas"]),
                                   "llm": r.get("llm"), "cookies": r.get("cookies")}
            if resumo and all("erro" in v for v in resumo.values()):
                estado, erro = "erro", "nenhuma semente pôde ser lida"
        except BloqueioYouTube as e:
            estado, erro = "erro", f"YouTube bloqueou as requisições (anti-bot/limite); parei. {e}"
        except Exception as e:  # noqa: BLE001 — a thread não pode morrer calada
            estado, erro = "erro", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
        finally:
            self.banco.atualizar_execucao(id_, estado=estado, erro=erro, resumo=resumo,
                                          progresso="concluída" if estado == "ok" else "falhou")
            self.atual = None
