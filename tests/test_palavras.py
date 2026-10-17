import unittest

from farejador.palavras import Ignorados, extrair, limpar_titulo, titulos_representativos, tokens

IGN = Ignorados("Café Brasil", "@LucianoPiresCafeBrasil", ["lídercast", "cafezinho"])


class TestPalavras(unittest.TestCase):
    def test_tokens_ignoram_stopwords_e_numeros(self):
        chaves = [c for c, _ in tokens("Como fazer PÃO de queijo em 2024 | The best F1 video")]
        self.assertEqual(chaves, ["pao", "queijo", "f1"])

    def test_ignora_nome_handle_colado_e_termos_extras(self):
        for t in ("cafe", "café", "brasil", "pires", "luciano", "lidercast", "cafezinho"):
            self.assertIn(tokens(t)[0][0], IGN, t)
        self.assertNotIn("brasileiro", IGN)
        self.assertNotIn("lideranca", IGN)

    def test_minimo_de_videos_distintos(self):
        videos = [
            {"titulo": "Pão de queijo mineiro", "tags": ["receita mineira"]},
            {"titulo": "Pão de queijo na airfryer", "tags": ["receita mineira"]},
            {"titulo": "Bolo bolo bolo bolo candidos", "tags": []},
            {"titulo": "Queijo minas caseiro", "tags": ["receita mineira"]},
        ]
        uni, frases = extrair(videos, min_videos=3)
        self.assertEqual(uni[0]["termo"], "queijo")  # 3 títulos vale mais que 3 tags
        self.assertEqual({u["termo"] for u in uni}, {"queijo", "receita", "mineira"})
        self.assertEqual(uni[0]["videos"], 3)
        self.assertNotIn("bolo", [u["termo"] for u in uni])      # repetido, mas num vídeo só
        self.assertNotIn("candidos", [u["termo"] for u in uni])  # ruído de 1 vídeo
        self.assertEqual([f["termo"] for f in frases], ["receita mineira"])  # "pão queijo" só em 2
        self.assertIn("pão queijo", [f["termo"] for f in extrair(videos, min_videos=2)[1]])

    def test_nome_do_canal_nao_vira_palavra(self):
        videos = [{"titulo": f"Café Brasil {i} – Liderança"} for i in range(3)]
        uni, _ = extrair(videos, ignorar=IGN)
        self.assertEqual([u["termo"] for u in uni], ["liderança"])

    def test_tags_do_canal_so_reforcam(self):
        videos = [{"titulo": "xadrez rápido"}, {"titulo": "xadrez abertura siciliana"},
                  {"titulo": "xadrez siciliana"}, {"titulo": "siciliana de novo"}]
        uni, _ = extrair(videos, tags_canal=["siciliana", "damas"], min_videos=3)
        termos = [u["termo"] for u in uni]
        self.assertEqual(termos[0], "siciliana")  # empata em vídeos com xadrez, ganha pela tag
        self.assertNotIn("damas", termos)          # tag do canal sem evidência nos vídeos

    def test_limpar_titulo(self):
        self.assertEqual(limpar_titulo("Café Brasil 950 – O Fim da Verdade", IGN), "O Fim da Verdade")
        self.assertEqual(limpar_titulo("LíderCast 312 | Liderança em tempos de crise #podcast", IGN),
                         "Liderança em tempos de crise")
        self.assertEqual(limpar_titulo("Cafezinho 600 – A Síndrome do Impostor 🔥", IGN), "A Síndrome do Impostor")
        self.assertEqual(limpar_titulo("Café Brasil 951", IGN), "")

    def test_titulos_representativos(self):
        videos = [{"titulo": "Café Brasil 1 – Receita de bolo"},
                  {"titulo": "Café Brasil 2 – Liderança no trabalho remoto"},
                  {"titulo": "Café Brasil 3"},
                  {"titulo": "Café Brasil 4 – Filosofia estoica e liderança"}]
        uni = [{"chave": "lideranca"}, {"chave": "estoica"}]
        frases = [{"chave": "filosofia estoica"}]
        t = titulos_representativos(videos, uni, frases, IGN, n=2)
        self.assertEqual(t, ["Filosofia estoica e liderança", "Liderança no trabalho remoto"])

    def test_titulos_representativos_diversos(self):
        videos = [{"titulo": "Filosofia estoica no trabalho"}, {"titulo": "Filosofia estoica para iniciantes"},
                  {"titulo": "Liderança em tempos de crise"}]
        t = titulos_representativos(videos, [{"chave": "estoica"}, {"chave": "lideranca"}],
                                    [{"chave": "filosofia estoica"}], n=3)
        self.assertEqual(t, ["Filosofia estoica no trabalho", "Liderança em tempos de crise"])

    def test_generica_youtube(self):
        self.assertEqual(tokens("YouTube mesa redonda no domingo, palestra"), [("redonda", "redonda")])

    def test_lista_sem_duplicata(self):
        ig = Ignorados("Sertec Manutenção", "@SERTECMANUTENCAO")
        self.assertEqual(sum(t.startswith("(tudo contido") for t in ig.lista()), 1)

    def test_frase_que_so_estende_outra_cai(self):
        videos = [{"titulo": f"vídeo {i}", "tags": ["filtro de linha", "filtro de linha gamer", "filtro linha metal",
                                                   "régua tomada"]} for i in range(6)]
        _, frases = extrair(videos)
        self.assertEqual(sorted(f["termo"] for f in frases), ["filtro linha", "régua tomada"])

    def test_titulo_sem_palavra_chave_nao_vira_busca(self):
        videos = [{"titulo": "Feliz dia do Professor"}, {"titulo": "Multímetro digital barato"}]
        t = titulos_representativos(videos, [{"chave": "multimetro"}], [], n=3)
        self.assertEqual(t, ["Multímetro digital barato"])

    def test_limpar_titulo_sem_pontuacao_solta(self):
        self.assertEqual(limpar_titulo("🔧 FILTRO DE LINHA… OU UM FILTRO DE LINHA “CAPADO”?"),
                         "FILTRO DE LINHA OU UM FILTRO DE LINHA CAPADO")
