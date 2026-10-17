import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from farejador.banco import Banco
from farejador.coleta import BloqueioYouTube
from farejador.config import Config
from farejador.descoberta import ErroCanal
from farejador.servico import Executor, JaRodando
from farejador.web import criar_app


def resultado(*cids):
    return {"candidatos": [{"channel_id": c, "nome": c.upper(), "handle": f"@{c}", "url": f"https://www.youtube.com/@{c}",
                            "score": 10, "score_final": 5.0, "motivo": "teste"} for c in cids],
            "avisos": ["aviso x"], "requisicoes": {"rede": 3, "cache": 1}, "consultas": [1, 2], "llm": None}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(dados=self.tmp.name, exclude=f"{self.tmp.name}/exclude.txt", pausa=0)
        self.banco = Banco(f"{self.tmp.name}/farejador.db")
        self.chamadas = []

    def tearDown(self):
        self.tmp.cleanup()

    def descobrir_falso(self, por_semente):
        def f(semente, cfg, coletor, exclusoes, log, llm):
            self.chamadas.append((semente, set(exclusoes)))
            log(f"busca 1/2 de {semente}")
            r = por_semente[semente]
            if isinstance(r, Exception):
                raise r
            return r
        return f


class TestExecutor(Base):
    def test_roda_grava_e_exclui_decididos(self):
        ex = Executor(self.cfg, self.banco, self.descobrir_falso({"@a": resultado("x", "y"), "@b": resultado("y", "z")}),
                      em_thread=False)
        id_ = ex.iniciar(["@a", "@b"])
        e = self.banco.execucao(id_)
        self.assertEqual(e["estado"], "ok")
        self.assertEqual(e["resumo"]["@a"]["novos"], 2)
        self.assertEqual(e["resumo"]["@b"]["novos"], 1)
        self.assertEqual(self.banco.candidato("y")["sementes"], ["@a", "@b"])
        self.banco.decidir("x", "descartado")
        ex.iniciar(["@a"])
        self.assertIn("x", self.chamadas[-1][1])  # descartado vai para a exclusão
        self.assertIsNone(ex.atual)

    def test_semente_ruim_nao_derruba_as_outras(self):
        ex = Executor(self.cfg, self.banco, self.descobrir_falso({"@a": ErroCanal("não li"), "@b": resultado("z")}),
                      em_thread=False)
        e = self.banco.execucao(ex.iniciar(["@a", "@b"]))
        self.assertEqual(e["estado"], "ok")
        self.assertEqual(e["resumo"]["@a"], {"erro": "não li"})
        ex2 = Executor(self.cfg, self.banco, self.descobrir_falso({"@a": ErroCanal("não li")}), em_thread=False)
        self.assertEqual(self.banco.execucao(ex2.iniciar(["@a"]))["estado"], "erro")

    def test_bloqueio_e_excecao_viram_erro(self):
        for exc in (BloqueioYouTube("Sign in to confirm"), RuntimeError("bug")):
            ex = Executor(self.cfg, self.banco, self.descobrir_falso({"@a": exc}), em_thread=False)
            e = self.banco.execucao(ex.iniciar(["@a"]))
            self.assertEqual(e["estado"], "erro")
            self.assertTrue(e["erro"])
            self.assertIsNone(ex.atual)

    def test_uma_por_vez_em_thread(self):
        liberar, comecou = threading.Event(), threading.Event()

        def lenta(semente, cfg, coletor, exclusoes, log, llm):
            comecou.set()
            liberar.wait(5)
            return resultado("x")
        ex = Executor(self.cfg, self.banco, lenta)
        id_ = ex.iniciar(["@a"])
        comecou.wait(5)
        self.assertEqual(self.banco.execucao(id_)["estado"], "rodando")
        with self.assertRaises(JaRodando):
            ex.iniciar(["@a"])
        liberar.set()
        ex._thread.join(5)
        self.assertEqual(self.banco.execucao(id_)["estado"], "ok")


class TestAPI(Base):
    def cliente(self, por_semente=None, enviar_metube=None, **cfg):
        for k, v in cfg.items():
            setattr(self.cfg, k, v)
        ex = Executor(self.cfg, self.banco, self.descobrir_falso(por_semente or {}), em_thread=False)
        kw = {"enviar_metube": enviar_metube} if enviar_metube else {}
        return TestClient(criar_app(self.cfg, self.banco, ex, **kw))

    def test_pagina(self):
        r = self.cliente().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<title>Farejador</title>", r.text)

    def test_fluxo_completo(self):
        c = self.cliente({"@a": resultado("x", "y")})
        self.assertEqual(c.post("/api/sementes", json={"canal": "@a"}).status_code, 201)
        self.assertEqual(c.post("/api/sementes", json={"canal": "   "}).status_code, 400)
        self.assertEqual([s["entrada"] for s in c.get("/api/sementes").json()], ["@a"])
        r = c.post("/api/descobertas", json={})
        self.assertEqual(r.status_code, 202)
        e = c.get(f"/api/descobertas/{r.json()['id']}").json()
        self.assertEqual(e["estado"], "ok")
        self.assertEqual({x["channel_id"] for x in c.get("/api/candidatos").json()}, {"x", "y"})
        self.assertEqual(c.post("/api/candidatos/x/aprovar").json(), {"estado": "aprovado", "metube": None})
        self.assertEqual(c.post("/api/candidatos/y/descartar").status_code, 200)
        self.assertEqual(c.post("/api/candidatos/y/aprovar").status_code, 409)  # descartado é definitivo
        self.assertEqual(c.post("/api/candidatos/nada/aprovar").status_code, 404)
        self.assertEqual([x["channel_id"] for x in c.get("/api/candidatos?estado=aprovado").json()], ["x"])
        self.assertEqual(c.get("/api/candidatos?estado=xyz").status_code, 400)
        exp = c.get("/api/exportar")
        self.assertEqual(exp.text, "https://www.youtube.com/@x\n")
        self.assertTrue(exp.headers["content-type"].startswith("text/plain"))
        self.assertEqual(c.delete("/api/candidatos/x").status_code, 409)  # só arquivados saem
        self.assertEqual(c.post("/api/arquivar").json(), {"arquivados": 2})
        self.assertEqual(c.get("/api/candidatos?estado=aprovado").json(), [])
        self.assertEqual({x["channel_id"] for x in c.get("/api/candidatos?estado=arquivado").json()}, {"x", "y"})
        self.assertEqual(c.get("/api/exportar").text, "")
        self.assertEqual(c.get("/api/exportar?arquivados=true").text, "https://www.youtube.com/@x\n")
        self.assertEqual(c.delete("/api/candidatos/y").status_code, 204)
        self.assertEqual(c.delete("/api/candidatos/y").status_code, 404)

    def test_sem_sementes_e_saude(self):
        c = self.cliente()
        self.assertEqual(c.post("/api/descobertas", json={}).status_code, 400)
        s = c.get("/api/saude").json()
        self.assertEqual((s["llm"], s["metube"], s["rodando"]), (False, False, None))

    def test_metube_ao_aprovar(self):
        enviados = []

        def falso(cfg, url, cache=None):
            enviados.append(url)
            return (len(enviados) > 1, "ok" if len(enviados) > 1 else "fora do ar")
        c = self.cliente({"@a": resultado("x")}, enviar_metube=falso, metube_url="http://m:8081", metube_ao_aprovar=True)
        c.post("/api/descobertas", json={"sementes": ["@a"]})
        r = c.post("/api/candidatos/x/aprovar").json()
        self.assertEqual(r["metube"], {"ok": False, "msg": "fora do ar"})
        self.assertEqual(self.banco.candidato("x")["metube_estado"], "erro")
        self.assertEqual(c.post("/api/candidatos/x/metube").json(), {"ok": True, "msg": "ok"})
        self.assertEqual(self.banco.candidato("x")["metube_estado"], "enviado")
        self.assertEqual(enviados, ["https://www.youtube.com/@x"] * 2)

    def test_metube_sem_envio_ao_aprovar(self):
        enviados = []
        c = self.cliente({"@a": resultado("x")}, enviar_metube=lambda cfg, url, cache=None: (enviados.append(url), (True, "ok"))[1],
                         metube_url="http://m:8081")
        c.post("/api/descobertas", json={"sementes": ["@a"]})
        self.assertEqual(c.post("/api/candidatos/x/aprovar").json()["metube"], None)
        self.assertEqual(enviados, [])  # só pelo botão
        self.assertTrue(c.post("/api/candidatos/x/metube").json()["ok"])
        self.assertEqual(enviados, ["https://www.youtube.com/@x"])

    def test_metube_desligado_nao_reenvia(self):
        c = self.cliente({"@a": resultado("x")})
        c.post("/api/descobertas", json={"sementes": ["@a"]})
        c.post("/api/candidatos/x/aprovar")
        self.assertEqual(c.post("/api/candidatos/x/metube").status_code, 409)

    def test_arranque_marca_interrompidas(self):
        e = self.banco.criar_execucao(["@a"])
        self.cliente()
        self.assertEqual(self.banco.execucao(e)["estado"], "interrompida")
