import unittest

from farejador import mencoes

UC = "UC" + "b" * 22


class TestMencoes(unittest.TestCase):
    def test_extrai_formas_de_link_e_conta_videos_distintos(self):
        videos = [
            {"id": "1", "descricao": "Convidado: https://www.youtube.com/@Fulano. Veja youtube.com/@fulano"},
            {"id": "2", "descricao": f"canal youtube.com/channel/{UC} e m.youtube.com/c/Beltrano"},
            {"id": "3", "descricao": "https://youtube.com/@Fulano/videos e https://youtube.com/user/Velho"},
            {"id": "4", "descricao": "instagram.com/@fulano e @solto não contam; youtube.com/watch?v=x também não"},
        ]
        a = mencoes.extrair(videos)
        self.assertEqual(set(a), {"@fulano", UC, "c/beltrano", "user/velho"})
        self.assertEqual(a["@fulano"]["videos"], {"1", "3"})
        self.assertEqual(a["@fulano"]["url"], "https://www.youtube.com/@Fulano")
        self.assertEqual(a[UC]["url"], f"https://www.youtube.com/channel/{UC}")

    def test_filtra_proprio_criador_e_rodape(self):
        achados = {
            "@ref": {"videos": {"1"}}, "@cafebrasilcortes": {"videos": {"1"}},
            "@rodape": {"videos": set("12345")}, "@convidado": {"videos": {"2", "3"}},
        }
        validos, ignorados = mencoes.filtrar(achados, 6, {"@ref"}, "Café Brasil", "@LucianoPiresCafeBrasil")
        self.assertEqual(set(validos), {"@convidado"})
        motivos = dict(ignorados)
        self.assertEqual(motivos["@ref"], "é o próprio canal")
        self.assertIn("criador", motivos["@cafebrasilcortes"])
        self.assertIn("rodapé", motivos["@rodape"])

    def test_rodape_exige_amostra_minima(self):
        validos, _ = mencoes.filtrar({"@x": {"videos": {"1", "2"}}}, 2, set(), "Ref", "@ref")
        self.assertIn("@x", validos)
