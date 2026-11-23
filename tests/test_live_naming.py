"""23 Nov (Zach): one live thing per name. The stream is the Live stream, the wall page is the Live map, the home page is just Home."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [p for p in ROOT.rglob("*.html") if ".git" not in p.parts and "node_modules" not in p.parts and p.parts[len(ROOT.parts):][0] not in ("data", "assets", "_site")]


class LiveNamingTest(unittest.TestCase):
    def test_no_live_board_or_live_wall_anywhere(self):
        for p in PAGES:
            t = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(?i)live board", t), str(p))
            self.assertIsNone(re.search(r"(?i)live wall", t), str(p))

    def test_home_page_has_one_plain_line_for_each_live_thing(self):
        t = (ROOT / "index.html").read_text(encoding="utf-8")
        m = re.search(r'<p class="home-two">(.*?)</p>', t, re.S)
        self.assertIsNotNone(m)
        self.assertIn(">Live stream</a>", m.group(1))
        self.assertIn('<a href="/wall/">Live map</a>', m.group(1))
        self.assertIn('class="chip wall-chip" href="/wall/">Live map</a>', t)

    def test_header_has_no_home_chip(self):
        for p in [ROOT / "index.html", ROOT / "about.html", ROOT / "stuck.html"]:
            self.assertNotRegex(p.read_text(encoding="utf-8"), r'<a class="chip[^"]*" href="/"', p.name)


if __name__ == "__main__":
    unittest.main()
