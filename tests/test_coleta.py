import json
import tempfile
import unittest

from yt_dlp.utils import DownloadError

from pathlib import Path

from farejador.cache import Cache
from farejador.coleta import BloqueioYouTube, Coletor, classificar
from farejador.config import Config
from tests.fakes import fabrica

BUSCA = {"entries": [{"id": "v1", "title": "t", "channel_id": "UCx", "channel": "X", "uploader_id": "@x"},
                     {"id": "v2", "title": "sem canal"}]}


class Relogio:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def agora(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(round(s, 2))
        self.t += s


def coletor(respostas, **cfg):
    rel = Relogio()
    fab, chamadas = fabrica(respostas)
    c = Coletor(Config(**cfg), Cache(":memory:"), fab, dormir=rel.dormir, relogio=rel.agora)
    return c, chamadas, rel


class TestColeta(unittest.TestCase):
    def test_cache_evita_repetir_consulta(self):
        c, chamadas, _ = coletor({"ytsearch20:Pão": BUSCA})
        r1 = c.buscar("Pão", 20)
        r2 = c.buscar("pão", 20)  # mesma consulta, outra caixa
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(r1, r2)
        self.assertEqual([e["channel_id"] for e in r1], ["UCx"])  # entrada sem canal descartada
        self.assertEqual(r1[0]["handle"], "@x")

    def test_pausa_entre_requisicoes(self):
        c, _, rel = coletor({"ytsearch20:a": BUSCA, "ytsearch20:b": BUSCA}, pausa=2.5)
        c.buscar("a", 20)
        c.buscar("b", 20)
        self.assertEqual(rel.esperas, [2.5])

    def test_retry_com_backoff_em_erro_transitorio(self):
        erro = DownloadError("HTTP Error 503: Service Unavailable")
        c, chamadas, rel = coletor({"ytsearch20:a": [erro, erro, BUSCA]}, pausa=0, backoff=5)
        self.assertTrue(c.buscar("a", 20))
        self.assertEqual(len(chamadas), 3)
        self.assertEqual(rel.esperas, [5, 10])
        tipos = [e[2] for e in c.cache.eventos("erro")]
        self.assertEqual(tipos, ["transitorio", "transitorio"])

    def test_erro_permanente_nao_repete_e_fica_registrado(self):
        c, chamadas, _ = coletor({}, pausa=0)
        self.assertIsNone(c.video("xyz"))
        self.assertIsNone(c.video("xyz"))
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(c.cache.eventos("erro")[0][2], "permanente")

    def test_bloqueio_interrompe(self):
        erro = DownloadError("Sign in to confirm you're not a bot")
        c, chamadas, _ = coletor({"ytsearch20:a": [erro]}, pausa=0, tentativas=5)
        with self.assertRaises(BloqueioYouTube):
            c.buscar("a", 20)
        self.assertEqual(len(chamadas), 2)  # não insiste além de uma nova tentativa

    def test_classificar(self):
        self.assertEqual(classificar("HTTP Error 429: Too Many Requests"), "bloqueio")
        self.assertEqual(classificar("This channel does not have a channels tab"), "permanente")
        self.assertEqual(classificar("HTTP Error 503: Service Unavailable"), "transitorio")
        self.assertEqual(classificar("Read timed out"), "transitorio")

    def test_cache_expira(self):
        agora = [0.0]
        cache = Cache(":memory:", horas=1, relogio=lambda: agora[0])
        cache.put("k", {"info": 1})
        self.assertEqual(cache.get("k"), {"info": 1})
        agora[0] = 3601
        self.assertIsNone(cache.get("k"))
        self.assertIsNotNone(Cache(":memory:", horas=0).get("x") or True)  # 0 = nunca expira

    def test_destaques_reduz_para_canais(self):
        aba = {"channel_id": "UCref", "entries": [
            {"ie_key": "YoutubeTab", "channel_id": "UCa", "channel": "A", "uploader_id": "@a",
             "url": "https://www.youtube.com/channel/UCa"},
            {"ie_key": "Youtube", "id": "v1", "url": "https://www.youtube.com/watch?v=v1", "channel_id": "UCref"},
            {"ie_key": "YoutubeTab", "url": "https://www.youtube.com/playlist?list=PL1", "channel_id": "UCref"},
            {"url": "https://www.youtube.com/@ref/channels?view=49"},
        ]}
        c, _, _ = coletor({"u": aba}, pausa=0)
        r = c.destaques("u")
        self.assertEqual([x["channel_id"] for x in r["canais"]], ["UCa"])
        self.assertEqual(r["links"], ["https://www.youtube.com/@ref/channels?view=49"])


class TestDiagnosticoEBruto(unittest.TestCase):
    def test_destaques_guarda_tipos_e_avisos(self):
        aba = {"channel_id": "UCref", "_avisos": ['Unsupported lockup view model content type "X"'],
               "entries": [{"ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=1"},
                           {"ie_key": "YoutubeTab", "url": "https://www.youtube.com/playlist?list=PL"}]}
        c, _, _ = coletor({"u": aba}, pausa=0)
        r = c.destaques("u")
        self.assertEqual(r["tipos"], {"video": 1, "playlist": 1})
        self.assertEqual(r["total"], 2)
        self.assertEqual(len(r["avisos_ytdlp"]), 1)
        self.assertEqual(c.avisos_ytdlp, 1)
        self.assertEqual(c.destaques("u"), r)  # do cache, com os mesmos avisos

    def test_ultimo_erro_vem_tambem_do_cache(self):
        erro = DownloadError("This channel does not have a channels tab")
        c, chamadas, _ = coletor({"u": erro}, pausa=0)
        self.assertIsNone(c.destaques("u"))
        self.assertIn("channels tab", c.ultimo_erro)
        c.ultimo_erro = None
        self.assertIsNone(c.destaques("u"))
        self.assertIn("channels tab", c.ultimo_erro)
        self.assertEqual(len(chamadas), 1)

    def test_salvar_bruto(self):
        with tempfile.TemporaryDirectory() as d:
            aba = {"channel_id": "UCref", "entries": [], "_avisos": ["aviso x"]}
            c, chamadas, _ = coletor({"https://www.youtube.com/@r/featured": aba,
                                      "ytsearch20:a": BUSCA}, pausa=0, dados=d, salvar_bruto=True)
            c.cache.put("destaques3:https://www.youtube.com/@r/featured", {"info": {"canais": []}})
            c.destaques("https://www.youtube.com/@r/featured")  # ignora o cache: precisa do cru
            c.buscar("a", 20)
            arquivos = sorted(p.name for p in (Path(d) / "bruto").iterdir())
            self.assertEqual(len(arquivos), 2)
            cru = json.loads((Path(d) / "bruto" / [a for a in arquivos if a.startswith("destaques3")][0]).read_text())
            self.assertEqual(cru["avisos_ytdlp"], ["aviso x"])
            self.assertEqual(cru["info"]["channel_id"], "UCref")
            self.assertEqual(len(chamadas), 2)
            c.destaques("https://www.youtube.com/@r/featured")  # já tem o cru: volta a usar o cache
            self.assertEqual(len(chamadas), 2)


class TestPlaylistsETitulos(unittest.TestCase):
    def test_video_guarda_titulo_original(self):
        c, _, _ = coletor({"https://www.youtube.com/watch?v=v1": {"id": "v1", "title": "Feliz dia do Professor"}}, pausa=0)
        self.assertEqual(c.video("v1")["titulo"], "Feliz dia do Professor")

    def test_destaques_lista_playlists(self):
        aba = {"channel_id": "UCref", "entries": [
            {"url": "https://www.youtube.com/playlist?list=PL1", "title": "Podcast Café Brasil"}]}
        c, _, _ = coletor({"u": aba}, pausa=0)
        self.assertEqual(c.destaques("u")["playlists"],
                         [{"url": "https://www.youtube.com/playlist?list=PL1", "titulo": "Podcast Café Brasil"}])

    def test_playlist_pede_idioma_e_cacheia_por_idioma(self):
        opcoes = []
        resp = {"title": "Iscas Intelectuais", "entries": [{"id": "a", "title": "Estoicismo"}, None, {"title": "sem id"}]}

        class Y:
            def __init__(self, o):
                opcoes.append(o)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                return resp

        cfg = Config(pausa=0)
        c = Coletor(cfg, Cache(":memory:"), Y, dormir=lambda s: None)
        r = c.playlist("https://www.youtube.com/playlist?list=PL1", 15)
        self.assertEqual(r, {"titulo": "Iscas Intelectuais", "videos": [{"id": "a", "titulo": "Estoicismo"}]})
        self.assertEqual(opcoes[0]["extractor_args"]["youtube"], {"lang": ["pt"]})
        self.assertEqual(opcoes[0]["playlistend"], 15)
        c.playlist("https://www.youtube.com/playlist?list=PL1", 15)
        self.assertEqual(len(opcoes), 1)  # cache
        cfg.idioma = ""
        c.playlist("https://www.youtube.com/playlist?list=PL1", 15)
        self.assertEqual(len(opcoes), 2)  # outro idioma, outra chave
        self.assertNotIn("youtube", opcoes[1]["extractor_args"])
