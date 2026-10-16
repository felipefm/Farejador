import tempfile
import unittest
from pathlib import Path

from farejador.canais import chaves, chaves_do_canal, ler_exclusoes, url_base

ID = "UC" + "a" * 22


class TestCanais(unittest.TestCase):
    def test_url_base(self):
        self.assertEqual(url_base("@Fulano"), "https://www.youtube.com/@Fulano")
        self.assertEqual(url_base(ID), f"https://www.youtube.com/channel/{ID}")
        self.assertEqual(url_base("https://youtube.com/@x/videos?view=0"), "https://www.youtube.com/@x")
        self.assertEqual(url_base("www.youtube.com/channel/%s/featured" % ID), f"https://www.youtube.com/channel/{ID}")
        self.assertEqual(url_base("fulano"), "https://www.youtube.com/@fulano")
        with self.assertRaises(ValueError):
            url_base("   ")

    def test_chaves(self):
        self.assertEqual(chaves("@Fulano"), {"@fulano"})
        self.assertEqual(chaves(f"https://www.youtube.com/channel/{ID}"), {ID})
        self.assertEqual(chaves("# comentário"), set())
        self.assertEqual(chaves_do_canal(ID, "@Fulano"), {ID, "@fulano"})

    def test_exclusoes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "exclude.txt"
            p.write_text(f"# meus canais\n@Fulano\n\n{ID}  # outro\nhttps://www.youtube.com/@Beltrano/videos\n")
            self.assertEqual(ler_exclusoes(p), {"@fulano", ID, "@beltrano"})
            self.assertEqual(ler_exclusoes(Path(d) / "nao-existe.txt"), set())
