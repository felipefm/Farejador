import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from farejador.cache import Cache
from farejador.config import Config
from farejador.llm import (LLM, SCHEMA_CONSULTAS, SCHEMA_NOTA, extrair_json, normalizar_url, validar_consultas,
                           validar_nota)
from farejador.palavras import Ignorados, tokens
from tests.fakes import FakeLLMServer, chat

IGN = Ignorados("Café Brasil", "@LucianoPiresCafeBrasil", ["cafezinho"])


def proibido(q):
    return any(c in IGN for c, _ in tokens(q))


def novo(responder, **cfg):
    srv = FakeLLMServer(responder)
    cfg = Config(**{"llm_url": "http://192.168.0.6:1234", "llm_model": "google/gemma-4-e4b", **cfg})
    return LLM(cfg, Cache(":memory:"), abrir=srv), srv


def consultas_ok(corpo, url):
    return chat(json.dumps({"consultas": ["liderança servidora", "filosofia estoica no trabalho",
                                          "café brasil podcast", "carreira e propósito"]}))


class TestBasico(unittest.TestCase):
    def test_url(self):
        self.assertEqual(normalizar_url("http://192.168.0.6:1234"), "http://192.168.0.6:1234/v1")
        self.assertEqual(normalizar_url("http://h:1234/v1/"), "http://h:1234/v1")
        self.assertEqual(normalizar_url(""), "")

    def test_desligado_por_padrao_e_com_sem_llm(self):
        self.assertFalse(LLM(Config(), Cache(":memory:")).ligado)
        self.assertFalse(LLM(Config(llm_url="http://h:1", sem_llm=True), Cache(":memory:")).ligado)
        self.assertTrue(LLM(Config(llm_url="http://h:1"), Cache(":memory:")).ligado)

    def test_env(self):
        cfg = Config.from_env({"FAREJADOR_LLM_URL": "http://192.168.0.6:1234", "FAREJADOR_LLM_TIMEOUT": "30",
                               "FAREJADOR_LLM_MODEL": "google/gemma-4-e4b", "FAREJADOR_SEM_LLM": "1"})
        self.assertEqual((cfg.llm_url, cfg.llm_timeout, cfg.llm_model, cfg.sem_llm),
                         ("http://192.168.0.6:1234", 30.0, "google/gemma-4-e4b", True))

    def test_extrair_json_tolerante(self):
        self.assertEqual(extrair_json('{"a": 1}'), {"a": 1})
        self.assertEqual(extrair_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(extrair_json('<think>hmm {x}</think>Claro! {"a": 1} espero ter ajudado'), {"a": 1})
        self.assertIsNone(extrair_json("não sei"))
        self.assertIsNone(extrair_json(None))


class TestValidacao(unittest.TestCase):
    def test_consultas(self):
        v = validar_consultas(proibido, 3)
        r = v({"consultas": ["liderança servidora", "Café Brasil episódios", "liderança servidora", "x",
                             42, "filosofia estoica", "cafezinho do dia", "carreira e propósito", "mais uma boa"]})
        self.assertEqual(r, ["liderança servidora", "filosofia estoica", "carreira e propósito"])
        self.assertIsNone(v({"consultas": ["Café Brasil"]}))   # só sobrou proibido
        self.assertIsNone(v({"queries": ["a b"]}))
        self.assertIsNone(v(["a b"]))

    def test_nota(self):
        self.assertEqual(validar_nota({"nota": 7, "justificativa": " Fala de  liderança. "}),
                         {"nota": 7.0, "justificativa": "Fala de liderança."})
        for ruim in ({"nota": 11, "justificativa": "x"}, {"nota": "7", "justificativa": "x"},
                     {"nota": True, "justificativa": "x"}, {"nota": 5, "justificativa": ""}, {"nota": 5}, None):
            self.assertIsNone(validar_nota(ruim), ruim)


class TestChamadas(unittest.TestCase):
    def test_pedido_e_cache(self):
        llm, srv = novo(consultas_ok)
        v = validar_consultas(proibido, 8)
        r1 = llm.perguntar("consultas", "prompt X", SCHEMA_CONSULTAS, v)
        r2 = llm.perguntar("consultas", "prompt X", SCHEMA_CONSULTAS, v)
        self.assertEqual(r1, ["liderança servidora", "filosofia estoica no trabalho", "carreira e propósito"])
        self.assertEqual(r1, r2)
        self.assertEqual(len(srv.pedidos), 1)  # segunda veio do cache
        p = srv.pedidos[0]
        self.assertEqual(p["url"], "http://192.168.0.6:1234/v1/chat/completions")
        self.assertEqual(p["corpo"]["model"], "google/gemma-4-e4b")
        self.assertEqual([m["role"] for m in p["corpo"]["messages"]], ["user"])
        self.assertEqual(p["corpo"]["response_format"]["type"], "json_schema")
        self.assertEqual(p["timeout"], 60.0)
        info = [e for e in llm.cache.eventos("info") if e[2] == "llm"]
        self.assertIn("ms", info[0][5])  # latência registrada

    def test_cache_depende_do_modelo(self):
        llm, srv = novo(consultas_ok)
        v = validar_consultas(proibido, 8)
        llm.perguntar("consultas", "p", SCHEMA_CONSULTAS, v)
        llm.modelo = "outro"
        llm.perguntar("consultas", "p", SCHEMA_CONSULTAS, v)
        self.assertEqual(len(srv.pedidos), 2)

    def test_timeout_desliga_e_nao_insiste(self):
        def lento(corpo, url):
            raise TimeoutError("timed out")
        llm, srv = novo(lento)
        self.assertIsNone(llm.perguntar("nota", "p1", SCHEMA_NOTA, validar_nota))
        self.assertIsNone(llm.perguntar("nota", "p2", SCHEMA_NOTA, validar_nota))
        self.assertEqual(len(srv.pedidos), 1)
        self.assertFalse(llm.ligado)
        self.assertIn("modo determinístico", llm.avisos[0])
        self.assertEqual(llm.cache.eventos("erro")[0][2], "llm_indisponivel")

    def test_fora_do_ar(self):
        def recusa(corpo, url):
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        llm, _ = novo(recusa)
        self.assertIsNone(llm.perguntar("nota", "p", SCHEMA_NOTA, validar_nota))
        self.assertIn("Connection refused", llm.avisos[0])

    def test_lixo_nao_cacheia_e_desliga_apos_3(self):
        llm, srv = novo(lambda c, u: chat("Desculpe, não entendi."))
        for i in range(4):
            self.assertIsNone(llm.perguntar("nota", f"p{i}", SCHEMA_NOTA, validar_nota))
        self.assertEqual(len(srv.pedidos), 3)
        self.assertEqual([e[2] for e in llm.cache.eventos("erro")], ["llm_invalido"] * 3)
        self.assertIn("inválidas", llm.avisos[0])
        self.assertIsNone(llm.cache.get("llm:x"))

    def test_resposta_que_nao_e_json_de_chat(self):
        llm, _ = novo(lambda c, u: "<html>502 Bad Gateway</html>")
        self.assertIsNone(llm.perguntar("nota", "p", SCHEMA_NOTA, validar_nota))
        self.assertTrue(llm.ligado)  # 1 falha só não desliga

    def test_400_repete_sem_response_format(self):
        def exigente(corpo, url):
            if "response_format" in corpo:
                raise urllib.error.HTTPError(url, 400, "response_format not supported", {}, io.BytesIO(b""))
            return chat('{"nota": 8, "justificativa": "Mesmo nicho."}')
        llm, srv = novo(exigente)
        self.assertEqual(llm.perguntar("nota", "p", SCHEMA_NOTA, validar_nota)["nota"], 8.0)
        self.assertEqual(len(srv.pedidos), 2)

    def test_modelo_vazio_usa_o_primeiro_do_servidor(self):
        def servidor(corpo, url):
            if url.endswith("/models"):
                return json.dumps({"data": [{"id": "google/gemma-4-e4b"}, {"id": "outro"}]})
            return chat('{"nota": 3, "justificativa": "Pouco a ver."}')
        llm, srv = novo(servidor, llm_model="")
        self.assertEqual(llm.perguntar("nota", "p", SCHEMA_NOTA, validar_nota)["nota"], 3.0)
        self.assertEqual(srv.pedidos[1]["corpo"]["model"], "google/gemma-4-e4b")
        self.assertIn("primeiro modelo", llm.avisos[0])

    def test_salvar_bruto(self):
        with tempfile.TemporaryDirectory() as d:
            llm, _ = novo(lambda c, u: chat("lixo"), dados=d, salvar_bruto=True)
            llm.perguntar("nota", "meu prompt", SCHEMA_NOTA, validar_nota)
            arquivos = list((Path(d) / "bruto").glob("llm-nota-*.json"))
            self.assertEqual(len(arquivos), 1)
            reg = json.loads(arquivos[0].read_text())
            self.assertEqual(reg["pedido"]["messages"][0]["content"], "meu prompt")
            self.assertIn("lixo", reg["resposta_crua"])
            self.assertFalse(reg["valido"])
            self.assertIn("latencia_ms", reg)
