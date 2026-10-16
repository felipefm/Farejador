import unittest

from farejador.config import Config


class TestConfig(unittest.TestCase):
    def test_env(self):
        cfg = Config.from_env({"FAREJADOR_PAUSA": "4", "FAREJADOR_VERBOSE": "true", "FAREJADOR_SALVAR_BRUTO": "0",
                               "FAREJADOR_IGNORAR_TERMOS": "podcast, lídercast ,,", "FAREJADOR_MAX_BUSCAS": ""})
        self.assertEqual(cfg.pausa, 4.0)
        self.assertTrue(cfg.verbose)
        self.assertFalse(cfg.salvar_bruto)
        self.assertEqual(cfg.max_buscas, 8)
        self.assertEqual(cfg.termos_ignorados(), ["podcast", "lídercast"])

    def test_padroes(self):
        cfg = Config()
        self.assertEqual(cfg.detalhes_videos, cfg.videos_referencia)  # lê detalhes de todos os vídeos
        self.assertEqual(cfg.min_videos_termo, 3)
        self.assertEqual(cfg.min_sinais, 2)
