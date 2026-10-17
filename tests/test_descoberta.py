import tempfile
import unittest

from yt_dlp.utils import DownloadError

from farejador.cache import Cache
from farejador.coleta import Coletor
from farejador.config import Config
from farejador.descoberta import ErroCanal, descobrir
from tests.fakes import fabrica

AGORA = 1_800_000_000
DIA = 86400
REF = "https://www.youtube.com/@LucianoPiresCafeBrasil"
UCCONV = "UC" + "c" * 22


def v(i, titulo, cid="UCref", canal="Café Brasil", handle="@LucianoPiresCafeBrasil", dias=5):
    return {"id": i, "title": titulo, "channel_id": cid, "channel": canal, "uploader_id": handle,
            "timestamp": AGORA - dias * DIA}


def canal(cid, nome, handle, dias):
    return {"channel_id": cid, "channel": nome, "uploader_id": handle, "channel_follower_count": 1000,
            "entries": [v("x" + cid, "ultimo", cid, nome, handle, dias)]}


TITULOS = [
    "Café Brasil 950 – Liderança em tempos de crise",
    "Café Brasil 951 – Liderança e propósito",
    "Cafezinho 600 – Liderança servidora",
    "LíderCast 312 – Empreendedorismo e liderança",
    "Café Brasil 952 – Filosofia estoica no trabalho",
    "Cafezinho 601 – Filosofia estoica para iniciantes",
]
RODAPE = "\nApoie: https://www.youtube.com/@cafebrasilcortes e https://youtube.com/@rodape"
DESCRICOES = [
    "Com https://youtube.com/@convidado",
    "Volta o https://www.youtube.com/@Convidado.",
    "De novo youtube.com/@convidado",
    f"Agora pelo ID youtube.com/channel/{UCCONV}",
    "Link quebrado youtube.com/c/Invalido",
    "Citação única https://www.youtube.com/@solo",
]


class Respostas(dict):
    """URLs fixas + buscas geradas: UCbom e UCvelho em todas, UCraro só na primeira."""

    def __init__(self, *a):
        super().__init__(*a)
        self.buscas = 0

    def get(self, url, default=None):
        if url.startswith("ytsearch"):
            self.buscas += 1
            q = url.split(":", 1)[1]
            r = [v("b1", f"{q} 1", "UCbom", "Bom", "@bom", 3), v("b2", f"{q} 2"),
                 v("b3", q, "UCtopic", "Coisa - Topic", None, 3), v("b4", "velho", "UCvelho", "Velho", "@velho", 400)]
            if self.buscas == 1:
                r.append(v("b5", "raro", "UCraro", "Raro", "@raro", 2))
            if self.buscas == 2:
                r.append(v("b6", "conv", UCCONV, "Convidado", "@convidado", 2))
            return {"entries": r}
        return dict.get(self, url, default)


def cenario():
    resp = {
        f"{REF}/videos": {"channel_id": "UCref", "channel": "Café Brasil", "uploader_id": "@LucianoPiresCafeBrasil",
                          "description": "Liderança e filosofia", "tags": ["liderança"],
                          "entries": [v(f"r{i}", t) for i, t in enumerate(TITULOS)]},
        f"{REF}/channels": DownloadError("This channel does not have a channels tab"),
        f"{REF}/featured": {"channel_id": "UCref", "_avisos": ['Unsupported lockup view model content type "CHANNEL"'],
                            "entries": [{"ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=r0"},
                                        {"ie_key": "YoutubeTab", "url": "https://www.youtube.com/playlist?list=PL1",
                                         "title": "Videocast Iscas Intelectuais"}]},
        "https://www.youtube.com/playlist?list=PL1": {"title": "Videocast Iscas Intelectuais", "entries": [
            {"id": "p1", "title": "Virtude e caráter na vida adulta"}, {"id": "p2", "title": "A virtude esquecida"},
            {"id": "p3", "title": "Virtude, coragem e medo"}, {"id": "r1", "title": "repetido da aba Vídeos"}]},
        "https://www.youtube.com/@convidado/videos": canal(UCCONV, "Convidado", "@convidado", 10),
        "https://www.youtube.com/@Convidado/videos": canal(UCCONV, "Convidado", "@convidado", 10),
        f"https://www.youtube.com/channel/{UCCONV}/videos": canal(UCCONV, "Convidado", "@convidado", 10),
        "https://www.youtube.com/@solo/videos": canal("UCsolo", "Solo", "@solo", 10),
        "https://www.youtube.com/channel/UCvelho/videos": canal("UCvelho", "Velho", "@velho", 300),
        "https://www.youtube.com/channel/UCraro/videos": canal("UCraro", "Raro", "@raro", 1),
    }
    for i, d in enumerate(DESCRICOES):
        resp[f"https://www.youtube.com/watch?v=r{i}"] = {
            "id": f"r{i}", "title": TITULOS[i], "description": d + RODAPE,
            "tags": ["filosofia estoica"] if i == 0 else []}
    # o modo flat devolve o último título traduzido para o inglês; a extração completa traz o original
    resp[f"{REF}/videos"]["entries"][5]["title"] = "Cafezinho 601 – Stoic philosophy for beginners"
    return Respostas(resp)


class TestDescoberta(unittest.TestCase):
    def rodar(self, exclusoes=frozenset(), **cfg):
        fab, chamadas = fabrica(cenario())
        cfg = Config(pausa=0, ignorar_termos="lidercast,cafezinho", **cfg)
        coletor = Coletor(cfg, Cache(":memory:"), fab, dormir=lambda s: None)
        return descobrir("@LucianoPiresCafeBrasil", cfg, coletor, exclusoes, agora=AGORA), chamadas

    def test_palavras_e_buscas(self):
        r, chamadas = self.rodar()
        self.assertEqual(r["referencia"]["videos_com_detalhes"], 6)  # todos, não só 5
        termos = [p["termo"] for p in r["palavras_chave"]]
        self.assertIn("liderança", termos)
        for proibido in ("café", "cafe", "brasil", "cafezinho", "lídercast", "pires"):
            self.assertNotIn(proibido, termos)
        self.assertTrue(all(p["videos"] >= 3 for p in r["palavras_chave"] + r["frases"]))
        self.assertIn("filosofia estoica", [f["termo"] for f in r["frases"]])
        origens = [c["origem"] for c in r["consultas"]]
        self.assertEqual(origens[:3], ["título"] * 3)
        self.assertIn("frase", origens)
        self.assertLessEqual(len(r["consultas"]), 8)
        self.assertTrue(all("Café" not in c["consulta"] for c in r["consultas"]))

    def test_mencoes(self):
        r, _ = self.rodar()
        m = r["mencoes"]
        self.assertEqual(m["descricoes_lidas"], 6)
        self.assertEqual(m["invalidos"], ["c/invalido"])
        motivos = {i["canal"]: i["motivo"] for i in m["ignorados"]}
        self.assertIn("criador", motivos["@cafebrasilcortes"])
        self.assertIn("rodapé", motivos["@rodape"])
        conv = next(c for c in r["candidatos"] if c["channel_id"] == UCCONV)
        self.assertEqual(conv["mencoes"], 4)  # @convidado em 3 vídeos + link por ID em outro
        self.assertIn("citado em 4 vídeos", conv["motivo"])
        self.assertEqual(conv["seguidores"], 1000)

    def test_ranking_filtros_e_fracos(self):
        r, chamadas = self.rodar()
        nomes = [c["nome"] for c in r["candidatos"]]
        self.assertEqual(nomes[0], "Bom")
        self.assertNotIn("Café Brasil", nomes)
        self.assertNotIn("Coisa - Topic", nomes)
        self.assertNotIn("Velho", nomes)                   # inativo vira filtro
        self.assertEqual(r["inativos"], ["Velho"])
        self.assertIn("https://www.youtube.com/channel/UCvelho/videos", chamadas)
        self.assertNotIn("Raro", nomes)                    # 1 busca só
        self.assertNotIn("Solo", nomes)                    # 1 menção só
        self.assertEqual(r["fracos"], {"total": 2, "por_sinal": {"1 busca": 1, "menção": 1, "destaque": 0}})
        self.assertEqual(r["candidatos_fracos"], [])
        self.assertTrue(all(c["atividade"] == "ativo" for c in r["fracos_ativos"]))  # para o cruzamento de sementes
        self.assertIsInstance(r["variantes"], dict)
        self.assertTrue(all(c["sinais"] >= 2 for c in r["candidatos"]))
        self.assertNotIn("https://www.youtube.com/channel/UCraro/videos", chamadas)  # fraco oculto: não checa

    def test_mostrar_fracos(self):
        r, _ = self.rodar(mostrar_fracos=True)
        self.assertEqual({c["nome"] for c in r["candidatos_fracos"]}, {"Raro", "Solo"})

    def test_diagnostico_abas(self):
        r, _ = self.rodar()
        estados = [(a["fonte"], a["estado"]) for a in r["destaques"]["abas"]]
        self.assertEqual(estados, [("aba Canais", "inexistente"), ("aba Início", "sem_canais")])
        avisos = " ".join(r["avisos"])
        self.assertIn("aba Canais: o canal não tem", avisos)
        self.assertIn("NENHUM canal", avisos)
        self.assertIn("1 playlist, 1 video", avisos)
        self.assertIn("não sabe ler", avisos)

    def test_aviso_de_429(self):
        aviso = "[youtube] r0: Unable to download webpage: HTTP Error 429: Too Many Requests"
        resp = cenario()
        resp["https://www.youtube.com/watch?v=r0"]["_avisos"] = [aviso]
        fab, _ = fabrica(resp)
        with tempfile.TemporaryDirectory() as tmp:  # sem cookies de verdade de data/
            cfg = Config(pausa=0, dados=tmp)
            r = descobrir("@LucianoPiresCafeBrasil", cfg, Coletor(cfg, Cache(":memory:"), fab, dormir=lambda s: None),
                          agora=AGORA)
        self.assertEqual(r["requisicoes"]["limitadas"], 1)
        self.assertIsNone(r["cookies"])
        texto = " ".join(r["avisos"])
        self.assertIn("429", texto)
        self.assertIn("cookies.txt", texto)

    def test_aviso_de_cookies_expirados(self):
        from farejador import cookies
        from tests.test_cookies import VALIDO
        resp = cenario()
        resp["https://www.youtube.com/watch?v=r0"]["_avisos"] = ["The provided YouTube account cookies are no longer valid."]
        fab, _ = fabrica(resp)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(pausa=0, dados=tmp)
            cookies.salvar(cfg, VALIDO)
            r = descobrir("@LucianoPiresCafeBrasil", cfg, Coletor(cfg, Cache(":memory:"), fab, dormir=lambda s: None),
                          agora=AGORA)
        self.assertTrue(r["cookies_expirados"])
        self.assertIn("expiraram", " ".join(r["avisos"]))

    def test_etapas(self):
        r, chamadas = self.rodar()
        etapas = {e["etapa"]: e for e in r["etapas"]}
        self.assertEqual(etapas["detalhes de 6 vídeos"]["rede"], 6)
        self.assertEqual(sum(e["rede"] for e in r["etapas"]), r["requisicoes"]["rede"])
        self.assertEqual(r["requisicoes"]["rede"], len(chamadas))

    def test_exclusao(self):
        r, _ = self.rodar(exclusoes={"@bom"})
        self.assertNotIn("Bom", [c["nome"] for c in r["candidatos"]])
        self.assertEqual(r["removidos"]["exclusao"], 1)

    def test_canal_inexistente(self):
        fab, _ = fabrica({})
        cfg = Config(pausa=0)
        with self.assertRaises(ErroCanal):
            descobrir("@nada", cfg, Coletor(cfg, Cache(":memory:"), fab, dormir=lambda s: None))


class TestTitulosEPlaylists(unittest.TestCase):
    def test_titulo_original_e_playlists_na_amostra(self):
        r, chamadas = TestDescoberta().rodar()
        ref = r["referencia"]
        self.assertEqual(ref["titulos_corrigidos"], 1)
        frases = {f["termo"]: f["videos"] for f in r["frases"]}
        self.assertEqual(frases["filosofia estoica"], 3)  # só fecha 3 com o título original em português
        self.assertTrue(all("Stoic" not in c["consulta"] for c in r["consultas"]))
        self.assertEqual(r["playlists"], [{"titulo": "Videocast Iscas Intelectuais",
                                           "url": "https://www.youtube.com/playlist?list=PL1", "videos": 3}])
        self.assertEqual(ref["videos_de_playlists"], 3)  # r1 já estava na amostra
        termos = {p["termo"]: p["videos"] for p in r["palavras_chave"]}
        self.assertEqual(termos["virtude"], 3)  # palavra que só existe nas playlists
        self.assertIn("https://www.youtube.com/playlist?list=PL1", chamadas)
