import unittest

from farejador.palavras import extrair, tokens


class TestPalavras(unittest.TestCase):
    def test_tokens_ignoram_stopwords_e_numeros(self):
        chaves = [c for c, _ in tokens("Como fazer PÃO de queijo em 2024 | The best F1 video")]
        self.assertEqual(chaves, ["pao", "queijo", "f1"])

    def test_frequencia_por_video_vence_repeticao(self):
        videos = [
            {"titulo": "Pão de queijo mineiro", "tags": ["receita mineira"]},
            {"titulo": "Pão de queijo na airfryer", "tags": ["receita mineira", "airfryer"]},
            {"titulo": "Bolo bolo bolo bolo", "tags": []},
            {"titulo": "Queijo minas caseiro", "tags": []},
        ]
        uni, frases = extrair(videos)
        termos = [u["termo"] for u in uni]
        self.assertEqual(termos[0], "queijo")       # em 3 vídeos
        self.assertNotIn("bolo", termos)            # repetido, mas num só vídeo
        self.assertIn("pão queijo", [f["termo"] for f in frases])
        self.assertIn("receita mineira", [f["termo"] for f in frases])

    def test_ignora_nome_do_proprio_canal(self):
        videos = [{"titulo": "Cozinha da Ana: lasanha"}, {"titulo": "Cozinha da Ana: lasanha de berinjela"}]
        uni, _ = extrair(videos, ignorar=["Cozinha da Ana", "@cozinhadaana"])
        self.assertEqual([u["termo"] for u in uni], ["lasanha"])

    def test_tags_do_canal_pesam(self):
        videos = [{"titulo": "xadrez rápido"}, {"titulo": "abertura siciliana"}]
        uni, _ = extrair(videos, tags_canal=["siciliana"])
        self.assertEqual(uni[0]["termo"], "siciliana")
