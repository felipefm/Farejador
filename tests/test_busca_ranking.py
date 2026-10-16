import unittest

from farejador import busca, ranking


def u(t):
    return {"termo": t, "chave": t}


class TestConsultas(unittest.TestCase):
    def test_frases_primeiro_depois_pares_sem_repetir(self):
        q = busca.montar_consultas([u("queijo"), u("pao"), u("mineiro")], [u("pao queijo")], 4)
        self.assertEqual(q[0], "pao queijo")
        self.assertNotIn("queijo pao", q)  # mesmas palavras da frase
        # pares restantes: queijo+mineiro, pao+mineiro; palavras soltas já cobertas
        self.assertEqual(q, ["pao queijo", "queijo mineiro", "pao mineiro"])

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
    def test_buscas_distintas_pesam_mais_que_videos(self):
        a = ranking.pontuar({"consultas": ["1", "2", "3"], "videos": ["x"]}, 8, 60)
        b = ranking.pontuar({"consultas": ["1"], "videos": list("abcdefgh")}, 8, 60)
        self.assertGreater(a["score"], b["score"])
        self.assertIn("3/8 buscas", a["motivo"])
        self.assertIn("atividade não verificada", a["motivo"])

    def test_bonus_e_penalidade(self):
        base = ranking.pontuar({"consultas": ["1"], "videos": []}, 8, 60)["score"]
        self.assertEqual(ranking.pontuar({"consultas": ["1"], "destaque": True}, 8, 60)["score"], base + 15)
        self.assertEqual(ranking.pontuar({"consultas": ["1"], "atividade": "ativo"}, 8, 60)["score"], base + 5)
        self.assertEqual(ranking.pontuar({"consultas": ["1"], "atividade": "inativo"}, 8, 60)["score"], base - 10)

    def test_atividade(self):
        agora = 100 * 86400
        self.assertEqual(ranking.atividade([agora - 10 * 86400], 60, agora), "ativo")
        self.assertEqual(ranking.atividade([agora - 90 * 86400, None], 60, agora), "inativo")
        self.assertEqual(ranking.atividade([None], 60, agora), "desconhecido")

    def test_ruido(self):
        self.assertTrue(ranking.eh_ruido("Fulano - Topic"))
        self.assertTrue(ranking.eh_ruido("FulanoVEVO"))
        self.assertFalse(ranking.eh_ruido("Fulano"))
