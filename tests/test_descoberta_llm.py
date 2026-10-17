import json
import unittest

from farejador import ranking
from farejador.cache import Cache
from farejador.coleta import Coletor
from farejador.config import Config
from farejador.descoberta import descobrir
from farejador.llm import LLM
from tests.fakes import FakeLLMServer, chat, fabrica
from tests.test_descoberta import AGORA, UCCONV, cenario

NOTAS = {"Bom": 2, "Convidado": 9}


def responder(corpo, url):
    prompt = corpo["messages"][0]["content"]
    if "consultas de busca" in prompt:
        return chat(json.dumps({"consultas": ["liderança servidora na prática", "Café Brasil episódios",
                                              "estoicismo para iniciantes"]}))
    nome = prompt.split("CANDIDATO: ", 1)[1].split("\n", 1)[0]
    return chat(json.dumps({"nota": NOTAS.get(nome, 5), "justificativa": f"Sobre {nome}."}))


def rodar(responder=responder, **cfg):
    fab, chamadas = fabrica(cenario())
    cfg = Config(pausa=0, ignorar_termos="lidercast,cafezinho", llm_url="http://192.168.0.6:1234",
                 llm_model="google/gemma-4-e4b", **cfg)
    cache = Cache(":memory:")
    srv = FakeLLMServer(responder)
    llm = LLM(cfg, cache, abrir=srv)
    r = descobrir("@LucianoPiresCafeBrasil", cfg, Coletor(cfg, cache, fab, dormir=lambda s: None),
                  agora=AGORA, llm=llm)
    return r, chamadas, srv


class TestCombinar(unittest.TestCase):
    def test_peso(self):
        cs = [{"nome": "A", "score": 100, "nota_llm": 1.0}, {"nome": "B", "score": 50, "nota_llm": 10.0},
              {"nome": "C", "score": 80}]
        self.assertEqual([c["nome"] for c in ranking.combinar([dict(c) for c in cs], 0)], ["A", "C", "B"])
        r = ranking.combinar([dict(c) for c in cs], 0.5)
        # C não foi avaliado: recebe a média das notas dadas (5,5) no lugar da nota
        self.assertEqual([(c["nome"], c["score_final"]) for c in r], [("B", 7.5), ("C", 6.75), ("A", 5.5)])
        self.assertEqual([c["nome"] for c in ranking.combinar([dict(c) for c in cs], 1)], ["B", "C", "A"])


    def test_valor_discrepante_nao_comprime_os_outros(self):
        cs = [{"nome": "Gigante", "score": 90}] + [{"nome": f"n{i}", "score": 20 + 10 * (i % 3)} for i in range(10)]
        r = ranking.combinar(cs, 0)
        self.assertEqual(r[0]["nome"], "Gigante")
        self.assertEqual(r[0]["score_final"], 10.0)
        self.assertEqual(next(c for c in r if c["score"] == 40)["score_final"], 10.0)  # p90 = 40
        self.assertEqual(next(c for c in r if c["score"] == 20)["score_final"], 5.0)

    def test_sem_nota_nenhuma_usa_o_score(self):
        r = ranking.combinar([{"nome": "A", "score": 30}, {"nome": "B", "score": 15}], 0.5)
        self.assertEqual([c["score_final"] for c in r], [10.0, 5.0])


class TestPipelineComLLM(unittest.TestCase):
    def test_consultas_somadas_e_filtradas(self):
        r, chamadas, _ = rodar()
        llm_q = [c["consulta"] for c in r["consultas"] if c["origem"] == "llm"]
        self.assertEqual(llm_q, ["liderança servidora na prática", "estoicismo para iniciantes"])  # sem "Café Brasil"
        base, _, _ = rodar(sem_llm=True)
        self.assertEqual([c for c in r["consultas"] if c["origem"] != "llm"], base["consultas"])  # intactas
        self.assertIn("ytsearch20:estoicismo para iniciantes", chamadas)
        self.assertEqual(r["llm"]["consultas"], 2)

    def test_reavaliacao_reordena_e_aparece_no_resultado(self):
        r, chamadas, srv = rodar()
        nomes = [c["nome"] for c in r["candidatos"]]
        self.assertEqual(nomes, ["Convidado", "Bom"])  # Bom tem mais score, mas nota 2
        bom = next(c for c in r["candidatos"] if c["nome"] == "Bom")
        self.assertEqual((bom["nota_llm"], bom["justificativa_llm"]), (2.0, "Sobre Bom."))
        self.assertIsNotNone(bom["score_final"])
        self.assertEqual(r["llm"]["avaliados"], 2)
        # Bom não tinha títulos recentes: o pipeline tentou ler a aba Vídeos dele
        self.assertIn("https://www.youtube.com/channel/UCbom/videos", chamadas)
        conv_prompt = next(p["corpo"]["messages"][0]["content"] for p in srv.pedidos
                           if "CANDIDATO: Convidado" in p["corpo"]["messages"][0]["content"])
        self.assertIn("REFERÊNCIA", conv_prompt)
        self.assertIn("- ultimo", conv_prompt)  # títulos da aba Vídeos, lidos na validação da menção
        etapas = {e["etapa"]: e for e in r["etapas"]}
        self.assertEqual(etapas["LLM: reavaliação"]["llm"], 2)

    def test_limite_de_avaliados(self):
        r, _, _ = rodar(llm_avaliar=1)
        self.assertEqual(r["llm"]["avaliados"], 1)
        self.assertEqual(sum(c["nota_llm"] is not None for c in r["candidatos"]), 1)

    def test_llm_fora_do_ar_cai_no_deterministico(self):
        def fora(corpo, url):
            raise TimeoutError("timed out")
        r, _, srv = rodar(fora)
        base, _, _ = rodar(sem_llm=True)
        self.assertEqual([c["nome"] for c in r["candidatos"]], [c["nome"] for c in base["candidatos"]])
        self.assertEqual(len(srv.pedidos), 1)  # desligou no primeiro timeout
        self.assertTrue(any("modo determinístico" in a for a in r["avisos"]))
        self.assertTrue(all(c["nota_llm"] is None for c in r["candidatos"]))

    def test_lixo_cai_no_deterministico(self):
        r, _, _ = rodar(lambda c, u: chat("não sei responder"))
        self.assertEqual(r["llm"]["consultas"], 0)
        self.assertTrue(any("consultas válidas" in a for a in r["avisos"]))
        self.assertTrue(all(c["nota_llm"] is None for c in r["candidatos"]))

    def test_sem_llm_nao_chama_servidor(self):
        r, chamadas, srv = rodar(sem_llm=True)
        self.assertEqual(srv.pedidos, [])
        self.assertFalse(r["llm"]["ligado"])
        self.assertNotIn("https://www.youtube.com/channel/UCbom/videos", chamadas)  # sem leitura extra


class TestPromptComPlaylists(unittest.TestCase):
    def test_playlists_vao_para_o_llm(self):
        _, _, srv = rodar()
        prompts = [p["corpo"]["messages"][0]["content"] for p in srv.pedidos]
        self.assertIn("Videocast Iscas Intelectuais", prompts[0])           # consultas
        self.assertTrue(any("Playlists: Videocast Iscas Intelectuais" in p for p in prompts[1:]))  # perfil


class TestCortePorNota(unittest.TestCase):
    def test_nota_minima_tira_da_lista_principal(self):
        r, _, _ = rodar(llm_nota_min=5)
        self.assertEqual([c["nome"] for c in r["candidatos"]], ["Convidado"])
        self.assertEqual([c["nome"] for c in r["reprovados_llm"]], ["Bom"])
        self.assertEqual(r["llm"]["reprovados"], 1)

    def test_todos_reprovados_avisa(self):
        r, _, _ = rodar(llm_nota_min=10)
        self.assertEqual(r["candidatos"], [])
        self.assertTrue(any("nenhum canal parecido" in a for a in r["avisos"]))

    def test_sem_corte_por_padrao_e_sem_llm(self):
        self.assertEqual(rodar()[0]["reprovados_llm"], [])
        self.assertEqual(rodar(sem_llm=True, llm_nota_min=9)[0]["reprovados_llm"], [])  # sem nota, sem corte
