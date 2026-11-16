"""Phone polish fixes: airport page order, nav selected state, accent CTA, source links, about and sources wording.
Fixtures only. No network. data/bts.json is git-ignored, so the BTS sample from tests/fixtures is used."""
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


class TestAirportPolish(unittest.TestCase):
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
             "--sitemap", str(tmp / "sitemap.xml"), "--date", "2026-11-14"],
            capture_output=True, text=True, timeout=60)
        assert res.returncode == 0, res.stderr
        cls.sfo = (out / "SFO.html").read_text(encoding="utf-8")
        cls.index = (out / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_ontime_figure_comes_before_at_a_glance(self) -> None:
        self.assertIn('class="glance-ontime"', self.sfo)
        self.assertLess(self.sfo.index('class="glance-ontime"'), self.sfo.index("At a glance"))

    def test_facts_do_not_repeat_the_code(self) -> None:
        m = re.search(r'<details class="glance-details"(?: open)?>(.*?)</details>', self.sfo, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertNotIn("Airport code", body)
        self.assertIn("<dt>City</dt>", body)
        self.assertIn("<dt>Time zone</dt>", body)

    def test_nav_marks_current_page(self) -> None:
        for page in (self.sfo, self.index):
            nav = nav_block(page)
            self.assertEqual(nav.count('aria-current="page"'), 1)
            self.assertRegex(nav, r'href="index.html" aria-current="page">Airports<')

    def test_stuck_button_is_accent(self) -> None:
        self.assertRegex(self.sfo, r'class="btn btn-accent" href="../stuck.html">I\'m stuck guide|class="btn btn-accent" href="../stuck.html">I&#x27;m stuck guide|class="btn btn-accent" href="../stuck.html">I(\'|&#39;|&#x27;)m stuck guide')
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.btn-accent\s*\{[^}]*var\(--accent\)")
        self.assertRegex(css, r'\.chip\[aria-current="page"\][^{]*\{[^}]*var\(--accent\)')

    def test_live_text_links_sources_and_calm_wind(self) -> None:
        self.assertIn('a.href = "../sources.html"', self.sfo)
        self.assertIn('"FAA NAS status"', self.sfo)
        self.assertIn('"aviationweather.gov METAR"', self.sfo)
        self.assertIn('"calm (0 kt)"', self.sfo)
        self.assertNotIn('" (FAA NAS status)"', self.sfo)


class TestAboutAndSourcesPolish(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.about = (ROOT / "about.html").read_text(encoding="utf-8")
        cls.sources = (ROOT / "sources.html").read_text(encoding="utf-8")

    def test_four_pill_nav_on_both(self) -> None:
        for name, text in (("about", self.about), ("sources", self.sources)):
            nav = nav_block(text)
            labels = re.findall(r">([^<]+)</a>", nav)
            self.assertEqual(labels, NAV_LABELS, name)
            self.assertNotIn("Back to live board", text, name)
        self.assertIn('href="about.html" aria-current="page">About<', nav_block(self.about))
        self.assertNotIn("aria-current", nav_block(self.sources))

    def test_about_rules_spaced_and_links_sources(self) -> None:
        self.assertIn('<ul class="rules-list">', self.about)
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"ul\.rules-list li\s*\{[^}]*padding:\s*12px")
        what = self.about.split("<h2>What this is</h2>")[1].split("<h2>")[0]
        self.assertIn('href="sources.html"', what)

    def test_sources_single_feed_header_and_plain_words(self) -> None:
        self.assertEqual(self.sources.count("<h2>Feeds the site reads</h2>"), 1)
        self.assertIn('<caption class="sr-only">Feeds the site reads</caption>', self.sources)
        self.assertIn("The site checks each feed about every 5 minutes. If a feed is down, the site keeps the last good report and says so.", self.sources)
        for bad in ("site job", "data file the feed fills", "Check times built"):
            self.assertNotIn(bad, self.sources)
        js = (ROOT / "sources.js").read_text(encoding="utf-8")
        self.assertIn('"Last updated "', js)
        self.assertNotIn("Check times built", js)
        self.assertIn("table-wrap--flat", self.sources)


if __name__ == "__main__":
    unittest.main()
