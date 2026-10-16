import unittest

from yt_dlp.utils import DownloadError

from farejador.cache import Cache
from farejador.coleta import Coletor
from farejador.config import Config
from farejador.descoberta import ErroCanal, descobrir
from tests.fakes import fabrica

AGORA = 1_800_000_000
DIA = 86400
REF = "https://www.youtube.com/@ref"


def v(i, titulo, cid="UCref", canal="Ref", handle="@ref", dias=5):
    return {"id": i, "title": titulo, "channel_id": cid, "channel": canal, "uploader_id": handle,
            "timestamp": AGORA - dias * DIA}


def cenario():
    titulos = ["Pão de queijo mineiro", "Pão de queijo de frigideira", "Queijo minas caseiro",
               "Doce de leite mineiro", "Pão de queijo sem glúten"]
    resp = {
        f"{REF}/videos": {"channel_id": "UCref", "channel": "Ref", "uploader_id": "@ref",
                          "description": "Receitas mineiras", "tags": ["culinária mineira"],
                          "entries": [v(f"r{i}", t) for i, t in enumerate(titulos)]},
        "https://www.youtube.com/watch?v=r0": {"id": "r0", "tags": ["pão de queijo", "receita mineira"]},
        f"{REF}/channels": DownloadError("This channel does not have a channels tab"),
        f"{REF}/featured": {"channel_id": "UCref", "entries": [
            {"ie_key": "YoutubeTab", "channel_id": "UCamiga", "channel": "Amiga", "uploader_id": "@amiga",
             "url": "https://www.youtube.com/channel/UCamiga"}]},
    }
    # buscas: UCbom e UCvelho (inativo) aparecem em todas, junto com o próprio canal e um canal automático
    def busca(q):
        return {"entries": [v("b1", f"{q} 1", "UCbom", "Bom", "@bom", 3),
                            v("b2", f"{q} 2", "UCref"),
                            v("b3", f"{q} 3", "UCtopic", "Coisa - Topic", None, 3)]
                + [v("b4", "velho", "UCvelho", "Velho", "@velho", 400)]}
    return resp, busca


class TestDescoberta(unittest.TestCase):
    def rodar(self, exclusoes=frozenset(), **cfg):
        resp, busca = cenario()

        class Respostas(dict):
            def get(self, url, default=None):
                if url.startswith("ytsearch"):
                    return busca(url.split(":", 1)[1])
                if url == "https://www.youtube.com/channel/UCvelho/videos":
                    return {"channel_id": "UCvelho", "entries": [v("x", "x", "UCvelho", dias=300)]}
                return dict.get(self, url, default)

        fab, chamadas = fabrica(Respostas(resp))
        cfg = Config(pausa=0, detalhes_videos=1, **cfg)
        coletor = Coletor(cfg, Cache(":memory:"), fab, dormir=lambda s: None)
        return descobrir("@ref", cfg, coletor, exclusoes, agora=AGORA), chamadas

    def test_pipeline(self):
        r, chamadas = self.rodar(max_buscas=4)
        self.assertEqual(len(r["consultas"]), 4)
        self.assertIn("queijo", r["palavras_chave"])
        self.assertNotIn("ref", r["palavras_chave"])
        nomes = [c["nome"] for c in r["candidatos"]]
        self.assertEqual(nomes[0], "Bom")
        self.assertNotIn("Ref", nomes)                 # o próprio canal sai
        self.assertNotIn("Coisa - Topic", nomes)       # canal automático sai
        self.assertEqual(r["removidos"]["ruido"], 1)
        self.assertEqual(r["destaques"]["fonte"], "aba Início")  # fallback registrado
        self.assertTrue(any("aba Canais" in a for a in r["avisos"]))
        amiga = next(c for c in r["candidatos"] if c["nome"] == "Amiga")
        self.assertTrue(amiga["destaque"])
        self.assertIn("em destaque", amiga["motivo"])
        bom = r["candidatos"][0]
        self.assertEqual(bom["atividade"], "ativo")
        self.assertEqual(bom["url"], "https://www.youtube.com/@bom")
        self.assertIn("4/4 buscas", bom["motivo"])
        velho = next(c for c in r["candidatos"] if c["nome"] == "Velho")
        self.assertEqual(velho["atividade"], "inativo")  # checado na aba Vídeos do candidato
        self.assertIn("https://www.youtube.com/channel/UCvelho/videos", chamadas)
        self.assertLess(velho["score"], bom["score"])
        self.assertEqual(r["referencia"]["videos_com_tags"], 1)

    def test_exclusao(self):
        r, _ = self.rodar(exclusoes={"@bom"})
        self.assertNotIn("Bom", [c["nome"] for c in r["candidatos"]])
        self.assertEqual(r["removidos"]["exclusao"], 1)

    def test_canal_inexistente(self):
        fab, _ = fabrica({})
        cfg = Config(pausa=0)
        with self.assertRaises(ErroCanal):
            descobrir("@nada", cfg, Coletor(cfg, Cache(":memory:"), fab, dormir=lambda s: None))
