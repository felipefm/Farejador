import io
import json
import unittest
import urllib.error

from farejador import metube
from farejador.cache import Cache
from farejador.config import Config
from tests.fakes import FakeLLMServer


class TestMetube(unittest.TestCase):
    def test_desligado_por_padrao(self):
        self.assertFalse(metube.ligado(Config()))

    def test_assinar_e_o_padrao(self):
        caminho, corpo = metube.montar_pedido(Config(metube_url="http://m:8081"), "https://www.youtube.com/@x")
        self.assertEqual(caminho, "/subscribe")
        self.assertEqual(corpo, {"url": "https://www.youtube.com/@x", "download_type": "video", "format": "any",
                                 "quality": "best"})
        _, corpo = metube.montar_pedido(Config(metube_intervalo=120), "u")
        self.assertEqual(corpo["check_interval_minutes"], 120)

    def test_formato_e_codec_configuraveis(self):
        _, corpo = metube.montar_pedido(Config(metube_formato="mp4", metube_qualidade="1080", metube_codec="h264"), "u")
        self.assertEqual((corpo["format"], corpo["quality"], corpo["codec"]), ("mp4", "1080", "h264"))

    def test_ja_inscrito_conta_como_sucesso(self):
        srv = FakeLLMServer(lambda c, u: json.dumps({"status": "error", "msg": "This URL is already subscribed"}))
        self.assertEqual(metube.enviar(Config(metube_url="http://m"), "u", abrir=srv),
                         (True, "já estava inscrito no MeTube"))

    def test_baixar_sempre_limita(self):
        caminho, corpo = metube.montar_pedido(Config(metube_modo="baixar", metube_limite=0, metube_qualidade="720"), "u")
        self.assertEqual(caminho, "/add")
        self.assertEqual((corpo["playlist_item_limit"], corpo["quality"]), (1, "720"))  # nunca 0 (= canal inteiro)

    def test_modo_invalido(self):
        ok, msg = metube.enviar(Config(metube_url="http://m", metube_modo="tudo"), "u")
        self.assertFalse(ok)
        self.assertIn("assinar", msg)

    def test_envio_ok_e_log(self):
        srv = FakeLLMServer(lambda corpo, url: json.dumps({"status": "ok"}))
        cache = Cache(":memory:")
        ok, msg = metube.enviar(Config(metube_url="http://m:8081/"), "https://www.youtube.com/@x", cache, abrir=srv)
        self.assertTrue(ok)
        self.assertEqual(srv.pedidos[0]["url"], "http://m:8081/subscribe")
        self.assertEqual(srv.pedidos[0]["corpo"]["url"], "https://www.youtube.com/@x")
        self.assertEqual(cache.eventos("info")[0][2], "metube")

    def test_erro_com_http_200(self):
        srv = FakeLLMServer(lambda c, u: json.dumps({"status": "error", "msg": "já existe"}))
        self.assertEqual(metube.enviar(Config(metube_url="http://m"), "u", abrir=srv), (False, "já existe"))

    def test_http_400_e_fora_do_ar(self):
        def recusa(c, u):
            raise urllib.error.HTTPError(u, 400, "Bad Request", {}, io.BytesIO(b"missing 'quality'"))
        ok, msg = metube.enviar(Config(metube_url="http://m"), "u", abrir=FakeLLMServer(recusa))
        self.assertEqual((ok, msg), (False, "HTTP 400: missing 'quality'"))

        def fora(c, u):
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        cache = Cache(":memory:")
        ok, msg = metube.enviar(Config(metube_url="http://m"), "u", cache, abrir=FakeLLMServer(fora))
        self.assertFalse(ok)
        self.assertIn("inacessível", msg)
        self.assertEqual(cache.eventos("erro")[0][2], "metube_erro")
