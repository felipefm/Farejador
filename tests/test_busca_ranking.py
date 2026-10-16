import unittest

from farejador import busca, ranking


def u(t):
    return {"termo": t, "chave": t}


class TestConsultas(unittest.TestCase):
    def test_ordem_titulos_frases_pares(self):
        q = busca.montar_consultas([u("queijo"), u("pao"), u("mineiro")], [u("pao queijo")], 6,
                                   titulos=["Pão de queijo na airfryer", "Doce de leite"])
        self.assertEqual(q, [("Pão de queijo na airfryer", "título"), ("Doce de leite", "título"),
                             ("pao queijo", "frase"), ("queijo mineiro", "par"), ("pao mineiro", "par")])

    def test_titulos_ocupam_no_maximo_metade(self):
        q = busca.montar_consultas([u("a1"), u("b1")], [u("c1 d1"), u("e1 f1")], 4, titulos=["t1", "t2", "t3"])
        self.assertEqual([o for _, o in q], ["título", "título", "frase", "frase"])

    def test_limite(self):
        self.assertEqual(len(busca.montar_consultas([u(str(i) + "x") for i in range(10)], [], 3)), 3)
        self.assertEqual(busca.montar_consultas([], [], 8), [])

    def test_agregar(self):
        e = lambda cid, t: {"channel_id": cid, "canal": cid.upper(), "titulo": t, "timestamp": 1}  # noqa: E731
        c = busca.agregar([("q1", [e("a", "v1"), e("a", "v2"), e("b", "v3")]), ("q2", [e("a", "v1")])])
        self.assertEqual(c["a"]["consultas"], ["q1", "q2"])
        self.assertEqual(c["a"]["videos"], ["v1", "v2"])
        self.assertEqual(c["b"]["consultas"], ["q1"])


class TestRanking(unittest.TestCase):
    def test_quantidade_de_videos_nao_pontua(self):
        a = ranking.pontuar({"consultas": ["1"], "videos": ["x"]}, 8, 60)
        b = ranking.pontuar({"consultas": ["1"], "videos": list("abcdefgh")}, 8, 60)
        self.assertEqual(a["score"], b["score"])

    def test_pesos(self):
        self.assertEqual(ranking.pontuar({"consultas": ["1", "2"]}, 8, 60)["score"], 20)
        self.assertEqual(ranking.pontuar({"destaque": True}, 8, 60)["score"], 15)
        m1 = ranking.pontuar({"mencoes": 1}, 8, 60)
        self.assertEqual(m1["score"], 20)
        self.assertIn("citado em 1 vídeo", m1["motivo"])
        m3 = ranking.pontuar({"mencoes": 3}, 8, 60)
        self.assertEqual(m3["score"], 30)
        self.assertIn("citado em 3 vídeos", m3["motivo"])
        self.assertEqual(ranking.pontuar({"mencoes": 50}, 8, 60)["score"], ranking.TETO_MENCAO)

    def test_atividade_nao_pontua(self):
        a = ranking.pontuar({"consultas": ["1"], "atividade": "ativo"}, 8, 60)
        b = ranking.pontuar({"consultas": ["1"]}, 8, 60)
        self.assertEqual(a["score"], b["score"])
        self.assertIn("publicou nos últimos 60 dias", a["motivo"])
        self.assertIn("atividade não verificada", b["motivo"])

    def test_sinais(self):
        self.assertEqual(ranking.sinais({"consultas": ["1", "2"]}), 2)
        self.assertEqual(ranking.sinais({"consultas": ["1"], "mencoes": 4}), 2)
        self.assertEqual(ranking.sinais({"mencoes": 4}), 1)
        self.assertEqual(ranking.sinais({"mencoes": 1, "destaque": True}), 2)

    def test_atividade(self):
        agora = 100 * 86400
        self.assertEqual(ranking.atividade([agora - 10 * 86400], 60, agora), "ativo")
        self.assertEqual(ranking.atividade([agora - 90 * 86400, None], 60, agora), "inativo")
        self.assertEqual(ranking.atividade([None], 60, agora), "desconhecido")

    def test_ruido(self):
        self.assertTrue(ranking.eh_ruido("Fulano - Topic"))
        self.assertTrue(ranking.eh_ruido("FulanoVEVO"))
        self.assertFalse(ranking.eh_ruido("Fulano"))
