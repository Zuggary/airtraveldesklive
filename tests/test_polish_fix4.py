"""Last polish round: airport disclosure and stale notice, About source groups, Sources licence links and crumb,
4-pill nav on Privacy and Stuck. Fixtures only. No network."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NAV_LABELS = ["Live board", "Airports", "Airlines", "Stuck?", "About"]  # AN34: one nav on every page


def nav_block(text: str) -> str:
    m = re.search(r'<nav class="header-nav"[^>]*>(.*?)</nav>', text, re.S)
    assert m, "no header nav"
    return m.group(1)


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class TestAirportRound4(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        d = tmp / "data"
        d.mkdir()
        for n in ("airport-guide.json", "airports.json", "places.json"):
            shutil.copy2(DATA / n, d / n)
        shutil.copy2(ROOT / "tests" / "fixtures" / "bts-sample.json", d / "bts.json")
        out = tmp / "out"
        res = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_airport_pages.py"), "--data", str(d), "--out", str(out),
             "--now", "2026-11-14T09:55:00Z", "--sitemap", str(tmp / "sitemap.xml"), "--date", "2026-11-14"],
            capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, res.stderr
        cls.sfo = (out / "SFO.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_facts_open_by_default_with_chevron_css(self) -> None:
        self.assertIn('<details class="glance-details" open>', self.sfo)
        css = read("style.css")
        self.assertIn(".glance-details summary::before", css)
        self.assertRegex(css, r"\.glance-details\[open\] > summary::before\s*\{[^}]*rotate\(45deg\)")

    def test_stuck_note_link_is_inline(self) -> None:
        css = read("style.css")
        self.assertRegex(css, r"\.stuck-note p \.tap[^{]*\{[^}]*display:\s*inline")
        self.assertIn("check what you may be owed</a>. This is plain-language help", self.sfo)

    def test_one_places_hierarchy(self) -> None:
        self.assertEqual(self.sfo.count("within 3.1 miles</h"), 1)
        self.assertIn("<h3>Hotels</h3>", self.sfo)
        self.assertIn("<h3>Car rental</h3>", self.sfo)

    def test_stale_notice_markup_and_script(self) -> None:
        # The notice sits above the status band; the script shows or hides it and holds the one stale limit.
        self.assertLess(self.sfo.index('id="stale-notice"'), self.sfo.index('id="status-chip"'))
        self.assertIn('class="stale-notice" role="status"', self.sfo)
        self.assertIn("var STALE_MIN = 30;", self.sfo)
        self.assertIn("https://nasstatus.faa.gov", self.sfo)
        self.assertIn(", not live. FAA's own page:", self.sfo)

    def test_one_age_format(self) -> None:
        script = self.sfo.split("<script>")[-1]
        self.assertEqual(script.count("\" min\""), 1)
        self.assertEqual(script.count("\" hours\""), 1)
        self.assertNotIn("\" h ago\"", script)


class TestAboutRound4(unittest.TestCase):
    def test_grouped_list_replaces_table(self) -> None:
        about = read("about.html")
        self.assertNotIn("<table", about)
        self.assertIn('<ul class="source-groups">', about)
        self.assertEqual(about.count("<li><strong>"), 5)
        self.assertIn('href="sources.html"', about.split("Where the data comes from")[1].split("Limits of the data")[0])
        self.assertIn("The site tries to refresh about every 5 minutes and keeps the last good data if a source is late.", about)
        self.assertNotIn("every 5 minutes by a script", about)

    def test_table_with_caption_is_on_sources(self) -> None:
        self.assertIn("<caption", read("sources.html"))
        self.assertIn("<table", read("sources.html"))


class TestSourcesRound4(unittest.TestCase):
    def test_licence_links_to_terms_and_crumb(self) -> None:
        s = read("sources.html")
        self.assertNotIn(">Terms</a>", s)
        self.assertIn('<td data-label="Licence and terms"><a href="https://www.usa.gov/government-works"', s)
        self.assertIn('<p class="crumb"><a href="about.html">About</a>', s)
        self.assertIn("Data and sources</p>\n        <h1>Data and sources</h1>", s)


class TestNavRound4(unittest.TestCase):
    def test_privacy_and_stuck_have_four_pills(self) -> None:
        for name in ("privacy.html", "stuck.html"):
            text = read(name)
            self.assertEqual(re.findall(r">([^<]+)</a>", nav_block(text)), NAV_LABELS, name)
            self.assertNotIn("Back to live board", text, name)
        self.assertNotIn("aria-current", nav_block(read("privacy.html")))  # privacy moved to the footer (AN34)
        self.assertIn('href="stuck.html" aria-current="page">Stuck?<', nav_block(read("stuck.html")))


if __name__ == "__main__":
    unittest.main()
