import os
import stat
import tempfile
import unittest

from fastapi.testclient import TestClient

from farejador import cookies
from farejador.banco import Banco
from farejador.cache import Cache
from farejador.coleta import Coletor
from farejador.config import Config
from farejador.servico import Executor
from farejador.web import criar_app
from tests.fakes import fabrica

VALIDO = (b"# Netscape HTTP Cookie File\n\n"
          b".youtube.com\tTRUE\t/\tTRUE\t1999999999\tPREF\tf6=40000000\n"
          b"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc\n")
BUSCA = {"entries": [{"id": "v1", "title": "t", "channel_id": "UCx", "channel": "X"}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(dados=self.tmp.name, pausa=0)

    def tearDown(self):
        self.tmp.cleanup()


class TestArquivo(Base):
    def test_valida_formato_netscape(self):
        self.assertEqual(cookies.validar(VALIDO), 2)
        for ruim, trecho in [(b"", "vazio"), (b"\xff\xfe", "texto"), (b"a=b; c=d\n", "7 campos"),
                             (b".example.com\tTRUE\t/\tTRUE\t0\tx\ty\n", "youtube"),
                             (b"#" * (cookies.LIMITE_BYTES + 1), "1 MB")]:
            with self.assertRaises(cookies.CookiesInvalidos) as e:
                cookies.validar(ruim)
            self.assertIn(trecho, str(e.exception))

    def test_salva_com_permissao_600(self):
        cookies.salvar(self.cfg, VALIDO)
        p = cookies.enviado(self.cfg)
        self.assertEqual(p.read_bytes(), VALIDO)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertFalse(p.with_name("cookies.txt.tmp").exists())

    def test_enviado_tem_prioridade_e_apagar_nao_toca_no_configurado(self):
        conf = os.path.join(self.tmp.name, "meus.txt")
        with open(conf, "wb") as f:
            f.write(VALIDO)
        self.cfg.cookies = conf
        self.assertEqual(cookies.ativo(self.cfg)[1], "configurado")
        cookies.salvar(self.cfg, VALIDO)
        self.assertEqual(cookies.ativo(self.cfg)[1], "enviado")
        self.assertIn("aviso", cookies.estado(self.cfg))
        self.assertTrue(cookies.apagar(self.cfg))
        self.assertFalse(cookies.apagar(self.cfg))
        self.assertEqual(cookies.ativo(self.cfg)[1], "configurado")
        self.assertTrue(os.path.exists(conf))

    def test_sem_cookies(self):
        self.assertEqual(cookies.ativo(self.cfg), (None, None))
        self.assertFalse(cookies.estado(self.cfg)["ativo"])


class TestColetor(Base):
    def coletor(self, respostas):
        fab, chamadas = fabrica(respostas)
        self.opcoes = []
        return Coletor(self.cfg, Cache(":memory:"), lambda o: (self.opcoes.append(o), fab(o))[1],
                       dormir=lambda s: None)

    def test_passa_cookiefile_ao_ytdlp(self):
        cookies.salvar(self.cfg, VALIDO)
        c = self.coletor({"ytsearch20:a": BUSCA})
        c.buscar("a", 20)
        self.assertEqual(self.opcoes[0]["cookiefile"], str(cookies.enviado(self.cfg)))
        self.assertEqual(c.cookies_origem, "enviado")

    def test_sem_cookies_nao_passa_cookiefile(self):
        c = self.coletor({"ytsearch20:a": BUSCA})
        c.buscar("a", 20)
        self.assertNotIn("cookiefile", self.opcoes[0])

    def test_conta_429_mesmo_quando_o_ytdlp_contorna(self):
        aviso = "[youtube] x: Unable to download webpage: HTTP Error 429: Too Many Requests"
        c = self.coletor({"ytsearch20:a": dict(BUSCA, _avisos=[aviso, aviso]), "ytsearch20:b": BUSCA})
        c.buscar("a", 20)
        c.buscar("b", 20)
        self.assertEqual(c.limitadas, 1)  # conta requisições, não avisos
        self.assertEqual(c.requisicoes, 2)


class TestApi(Base):
    def setUp(self):
        super().setUp()
        banco = Banco(f"{self.tmp.name}/farejador.db")
        self.api = TestClient(criar_app(self.cfg, banco, Executor(self.cfg, banco, em_thread=False)))

    def test_envia_consulta_e_remove(self):
        self.assertFalse(self.api.get("/api/cookies").json()["ativo"])
        r = self.api.put("/api/cookies", content=VALIDO, headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cookies"], 2)
        self.assertNotIn("SID", r.text)  # o conteúdo nunca volta pela API
        self.assertEqual(self.api.get("/api/saude").json()["cookies"], "enviado")
        self.assertEqual(self.api.delete("/api/cookies").status_code, 200)
        self.assertEqual(self.api.delete("/api/cookies").status_code, 404)
        self.assertIsNone(self.api.get("/api/saude").json()["cookies"])

    def test_rejeita_arquivo_invalido(self):
        r = self.api.put("/api/cookies", content=b"nada aqui", headers={"Content-Type": "text/plain"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(cookies.enviado(self.cfg).exists())


if __name__ == "__main__":
    unittest.main()
