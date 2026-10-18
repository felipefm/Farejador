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

    def test_arquivar_e_remover_do_arquivo(self):
        self.b.gravar_candidatos("@a", [cand("x"), cand("y"), cand("z")])
        self.b.decidir("x", "aprovado")
        self.b.decidir("y", "descartado")
        self.assertEqual(self.b.arquivar_decididos(), 2)
        self.assertEqual(self.b.arquivar_decididos(), 0)  # já arquivados
        self.assertEqual(self.b.candidatos("aprovado"), [])
        self.assertEqual(self.b.candidatos("descartado"), [])
        self.assertEqual({c["channel_id"] for c in self.b.candidatos("arquivado")}, {"x", "y"})
        self.assertEqual([c["channel_id"] for c in self.b.candidatos("novo")], ["z"])
        self.assertEqual(self.b.urls_aprovadas(), [])
        self.assertEqual(self.b.urls_aprovadas(arquivados=True), ["https://www.youtube.com/@x"])
        self.assertTrue({"y", "@y"} & self.b.chaves_decididas())  # arquivado continua na exclusão
        self.assertEqual(self.b.gravar_candidatos("@b", [cand("y")]), 0)  # e não volta como novo
        with self.assertRaises(TransicaoInvalida):
            self.b.remover_arquivado("z")  # novo não é removível
        with self.assertRaises(KeyError):
            self.b.remover_arquivado("nada")
        self.b.remover_arquivado("y")
        self.assertFalse({"y", "@y"} & self.b.chaves_decididas())
        self.assertEqual(self.b.gravar_candidatos("@b", [cand("y")]), 1)  # removido pode reaparecer
        self.assertEqual(self.b.candidato("y")["estado"], "novo")

    def test_migra_banco_antigo(self):
        import sqlite3
        p = Path(self.tmp.name) / "antigo.db"
        db = sqlite3.connect(p)
        from farejador.banco import ESQUEMA
        antigo = ESQUEMA.replace("metube_msg TEXT,", "metube_msg TEXT").replace(
            "arquivado_em TEXT                      -- preenchido = fora das abas, ainda na exclusão", "")
        db.executescript(antigo)
        db.execute("INSERT INTO candidatos (channel_id, url, estado, visto_em) VALUES ('x', 'u', 'aprovado', 'h')")
        db.commit()
        db.close()
        b = Banco(p)
        self.assertEqual(b.arquivar_decididos(), 1)
        self.assertEqual([c["channel_id"] for c in b.candidatos("arquivado")], ["x"])

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
            self.b.decidir("x", "novo")
        self.b.decidir("x", "aprovado")  # desfaz o descarte por engano
        self.assertEqual(self.b.candidato("x")["estado"], "aprovado")
        self.b.decidir("x", "descartado")
        self.b.arquivar_decididos()
        with self.assertRaises(TransicaoInvalida):
            self.b.decidir("x", "aprovado")  # arquivado: só removendo do arquivo

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



class TestSementes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Banco(Path(self.tmp.name) / "x.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bonus_por_semente_extra(self):
        self.b.gravar_candidatos("@a", [cand("forte", 9), cand("duplo", 5)])
        self.b.gravar_candidatos("@b", [cand("duplo", 4)])
        lista = self.b.candidatos("novo", bonus_semente=3)
        self.assertEqual([(c["channel_id"], c["ordem"]) for c in lista], [("forte", 9), ("duplo", 8)])  # 5 + 3
        self.assertEqual(lista[1]["bonus_sementes"], 3)
        lista = self.b.candidatos("novo", bonus_semente=5)
        self.assertEqual([c["channel_id"] for c in lista], ["duplo", "forte"])  # 5 + 5 > 9
        self.assertEqual([c["channel_id"] for c in self.b.candidatos("novo")], ["forte", "duplo"])  # sem bônus

    def test_mantem_a_melhor_versao_entre_sementes(self):
        self.b.gravar_candidatos("@a", [cand("x", 8, motivo="forte em @a")])
        self.b.gravar_candidatos("@b", [cand("x", 2, motivo="fraco em @b")], fraco=True)
        c = self.b.candidato("x")
        self.assertEqual((c["score_final"], c["motivo"], c["sementes"]), (8, "forte em @a", ["@a", "@b"]))

    def test_motivo_de_fraco_cruzado(self):
        self.b.gravar_candidatos("@a", [cand("x", 2, motivo="apareceu em 1/8 buscas")], fraco=True)
        self.assertTrue(self.b.candidato("x")["motivo"].startswith("fraco nesta semente, mas apareceu em outra"))
