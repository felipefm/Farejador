import tempfile
import unittest
from pathlib import Path

from farejador.banco import Banco, TransicaoInvalida


def cand(cid, score=10, **k):
    return {"channel_id": cid, "nome": cid.upper(), "handle": f"@{cid}", "url": f"https://www.youtube.com/@{cid}",
            "score_final": score, "score": score, **k}


class TestBanco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Banco(Path(self.tmp.name) / "x.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sementes(self):
        a = self.b.adicionar_semente("@a")
        self.assertEqual(self.b.adicionar_semente("@a"), a)  # sem duplicata
        self.b.adicionar_semente("@b")
        self.assertEqual([s["entrada"] for s in self.b.sementes()], ["@a", "@b"])
        self.assertTrue(self.b.remover_semente(a))
        self.assertFalse(self.b.remover_semente(a))

    def test_descartado_nunca_volta(self):
        self.b.gravar_candidatos("@a", [cand("x", 5), cand("y", 9)])
        self.b.decidir("x", "descartado")
        novos = self.b.gravar_candidatos("@b", [cand("x", 99, motivo="voltou?")])
        self.assertEqual(novos, 0)
        self.assertEqual([c["channel_id"] for c in self.b.candidatos("novo")], ["y"])
        x = self.b.candidato("x")
        self.assertEqual((x["estado"], x["score"], x["motivo"]), ("descartado", 5, None))  # não sobrescreve
        self.assertEqual(x["sementes"], ["@a", "@b"])  # mas registra que apareceu de novo
        with self.assertRaises(TransicaoInvalida):
            self.b.decidir("x", "aprovado")
        with self.assertRaises(TransicaoInvalida):
            self.b.decidir("x", "novo")

    def test_transicoes(self):
        self.b.gravar_candidatos("@a", [cand("x")])
        self.b.decidir("x", "aprovado")
        self.b.decidir("x", "aprovado")  # idempotente
        self.b.decidir("x", "descartado")
        with self.assertRaises(KeyError):
            self.b.decidir("nao-existe", "aprovado")

    def test_novo_e_atualizado_e_ordenado(self):
        self.b.gravar_candidatos("@a", [cand("x", 3), cand("y", 7)])
        self.b.gravar_candidatos("@b", [cand("x", 8, nota_llm=9.0)])
        lista = self.b.candidatos("novo")
        self.assertEqual([c["channel_id"] for c in lista], ["x", "y"])
        self.assertEqual((lista[0]["score"], lista[0]["nota_llm"], lista[0]["sementes"]), (8, 9.0, ["@a", "@b"]))

    def test_exclusoes_e_exportacao(self):
        self.b.gravar_candidatos("@a", [cand("x"), cand("y"), cand("z")])
        self.b.decidir("x", "aprovado")
        self.b.decidir("y", "descartado")
        self.assertEqual(self.b.chaves_decididas(), {"x", "@x", "y", "@y"})
        self.assertEqual(self.b.urls_aprovadas(), ["https://www.youtube.com/@x"])

    def test_execucoes_e_interrupcao(self):
        e = self.b.criar_execucao(["@a"])
        self.b.atualizar_execucao(e, progresso="busca 1/8")
        self.assertEqual(self.b.execucao(e)["progresso"], "busca 1/8")
        self.assertEqual(self.b.interromper_pendentes(), 1)
        r = self.b.execucao(e)
        self.assertEqual(r["estado"], "interrompida")
        self.assertIsNotNone(r["fim"])
        self.b.atualizar_execucao(e, estado="ok", resumo={"@a": {"candidatos": 1}})
        self.assertEqual(self.b.execucao(e)["resumo"], {"@a": {"candidatos": 1}})
