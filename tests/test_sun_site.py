"""AN18 site parts: sun.js, TV day and night, airport 'Sun now' line, home page Lantern Drift card. No network."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.build_airport_pages import airport_js as _an43_airport_js  # noqa: E402
AIRPORT_JS = _an43_airport_js()


ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
# sun.js is a byte-for-byte copy of the AN18 module (also used by the stream map). Change it only by copying a new version.
SUN_JS_SHA256 = "f71d752f7c98c428d048acda29c04b7865da3a6d4637b9f8dee826f13de4c6e6"
LANTERN = "https://www.lanterndrift.com/"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def node_eval(code: str):
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestSunModule(unittest.TestCase):
    def test_sun_js_is_the_recorded_copy(self) -> None:
        self.assertEqual(hashlib.sha256((ROOT / "sun.js").read_bytes()).hexdigest(), SUN_JS_SHA256)

    def test_sun_js_makes_no_network_calls(self) -> None:
        text = read("sun.js")
        for bad in ("fetch(", "XMLHttpRequest", "WebSocket", "import(", "sendBeacon", "http://", "https://"):
            self.assertNotIn(bad, text, bad)

    @unittest.skipUnless(NODE, "node not installed")
    def test_node_tests_pass(self) -> None:
        r = subprocess.run([NODE, str(ROOT / "tests" / "node" / "test_sun.js")], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok - ", r.stdout)


class TestTvSun(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tv = read("tv.html")

    def test_loads_local_sun_js_only(self) -> None:
        self.assertIn('<script src="sun.js"></script>', self.tv)
        self.assertLess(self.tv.index('src="cine.js"'), self.tv.index('src="sun.js"'))

    def test_label_and_accent(self) -> None:
        self.assertIn("Sun position: computed", self.tv)
        # AN32: the site accent moved to #7cc4ff; the TV page keeps its own accent for the stream.
        self.assertRegex(self.tv, r"--sun-accent:\s*" + re.escape("#4CC3FF"))

    def test_layer_is_per_minute_and_phones_use_flat_bands(self) -> None:
        self.assertIn("Math.floor(Date.now() / 60000)", self.tv)
        self.assertIn("sunMinuteNow()", self.tv)   # part of the static layer key: rebuilt once a minute
        self.assertIn("window.innerWidth < 700", self.tv)
        self.assertIn("Sun.flatBands(", self.tv)
        self.assertIn("{ dayTint: false }", self.tv)
        self.assertIn("Sun.shade(", self.tv)
        self.assertIn("Sun.darkness(", self.tv)    # city lights at hubs in the dark

    def test_no_new_network_request_from_the_sun_code(self) -> None:
        start = self.tv.index("// ---------- sun: day and night")
        end = self.tv.index("function buildStatic(")
        block = self.tv[start:end]
        for bad in ("fetch(", "XMLHttpRequest", "http://", "https://", "new Image"):
            self.assertNotIn(bad, block, bad)

    def test_flat_fallback_still_present(self) -> None:
        self.assertIn("window.innerWidth < 900", self.tv)
        self.assertIn("if (isFlat()) ctx.drawImage(src", self.tv)

    def test_no_ad_code(self) -> None:
        for bad in ("adsbygoogle", "googlesyndication", "doubleclick"):
            self.assertNotIn(bad, self.tv)


class TestAirportSunNow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.out = tmp / "airports"
        sm = tmp / "sitemap.xml"
        sm.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n</urlset>\n', encoding="utf-8")
        res = subprocess.run([sys.executable, str(ROOT / "tools" / "build_airport_pages.py"), "--data", str(ROOT / "data"),
                              "--out", str(cls.out), "--sitemap", str(sm), "--date", "2026-11-14"], capture_output=True, text=True, timeout=60)
        if res.returncode:
            raise RuntimeError(res.stderr or res.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_every_page_has_a_hidden_sun_line_with_zone_and_source(self) -> None:
        pages = [p for p in self.out.glob("*.html") if p.name != "index.html"]
        self.assertEqual(len(pages), 100)
        from desk.airports import AIRPORTS, TZ
        for p in pages:
            t = p.read_text(encoding="utf-8")
            code = p.stem
            a = {"tz": TZ[code], "lat": AIRPORTS[code][1]}
            m = re.search(r'<p id="sun-now" class="sun-now" data-lat="([^"]+)" data-lon="([^"]+)" data-tz="([^"]+)" hidden></p>', t)
            self.assertIsNotNone(m, code)
            self.assertEqual(m.group(3), a["tz"], code)
            self.assertAlmostEqual(float(m.group(1)), a["lat"], 3)
            self.assertIn('<p id="sun-now-source" class="small" hidden>Sun times calculated for the airport\'s location.</p>', t, code)
            self.assertIn('<script src="../sun.js" type="text/atd-late"></script>', t, code)  # AN43: the paint script is in ../airport.js
            # in the "Right now" section, so it is next to the status
            self.assertLess(t.index('id="right-now"'), t.index('id="sun-now"'))
            self.assertLess(t.index('id="sun-now"'), t.index('id="stuck-heading"'))

    def test_js_off_shows_nothing(self) -> None:
        t = (self.out / "SFO.html").read_text(encoding="utf-8")
        # no text sits outside a hidden element until the script runs
        self.assertNotIn("Sun now:", re.sub(r"<script.*?</script>", "", t, flags=re.S))

    def test_script_makes_no_request(self) -> None:
        t = AIRPORT_JS  # AN43: the daylight script moved from each page into the shared airport.js
        s = t[t.index('var p = document.getElementById("sun-now")'):]
        s = s[:s.index("})();")]
        for bad in ("fetch(", "XMLHttpRequest", "http"):
            self.assertNotIn(bad, s)

    @unittest.skipUnless(NODE, "node not installed")
    def test_card_text_for_sfo_and_polar_cases(self) -> None:
        code = ("const S=require(%s);const ms=Date.UTC(2026,10,14,20,0);"
                "process.stdout.write(JSON.stringify({sfo:S.hubCardText(37.621,-122.379,'America/Los_Angeles',ms),"
                "nosr:S.hubCardText(78.2,15.6,'Europe/Oslo',Date.UTC(2026,11,21,12,0)),"
                "noss:S.hubCardText(78.2,15.6,'Europe/Oslo',Date.UTC(2026,5,21,12,0))}))") % json.dumps(str(ROOT / "sun.js"))
        r = node_eval(code)
        self.assertRegex(r["sfo"], r"sunrise \d{1,2}:\d{2} [ap]m, sunset \d{1,2}:\d{2} [ap]m PT, ")
        self.assertIn("no sunrise", r["nosr"])
        self.assertIn("no sunset", r["noss"])


class TestHomeCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.idx = read("index.html")

    def test_card_link(self) -> None:
        m = re.search(r'<a class="btn btn-secondary wait-link" href="([^"]+)" target="_blank" rel="([^"]+)">', self.idx)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), LANTERN)
        self.assertNotIn("?", m.group(1))
        self.assertNotIn("utm", m.group(1).lower())
        self.assertIn("noopener", m.group(2))
        self.assertIn("While you wait: play Lantern Drift", self.idx)
        self.assertIn("A free game from us. No ads, no cookies.", self.idx)

    def test_card_sits_low_after_the_data_sections(self) -> None:
        # AN34 round 4: the game is a quiet line in the footer, after every data section.
        i = self.idx.index('id="while-you-wait"')
        for sec in ('id="now"', 'id="map-section"', 'id="owed"', 'id="compare"'):
            self.assertLess(self.idx.index(sec), i, sec)
        self.assertGreater(i, self.idx.index("<footer"))

    def test_tap_target_is_44px(self) -> None:
        css = read("style.css")
        self.assertRegex(css, r"\.wait-card \.wait-link\s*\{[^}]*min-height:\s*44px")

    def test_only_the_game_url_is_new(self) -> None:
        guide = read("tests/test_guide.py")
        self.assertIn('"https://www.lanterndrift.com/"', guide)


class TestSiteWiring(unittest.TestCase):
    def test_service_worker_caches_sun_js_and_cache_name_bumped(self) -> None:
        sw = read("sw.js")
        self.assertIn('"./sun.js"', sw)
        self.assertIn('CACHE_NAME = "atd-offline-v18"', sw)

    def test_workflow_publishes_sun_js(self) -> None:
        yml = read(".github/workflows/status.yml")
        self.assertRegex(yml, r"for file in [^;]*\bsun\.js\b")

    def test_sources_row(self) -> None:
        html = read("sources.html")
        self.assertIn('<tr data-src="sun">', html)
        self.assertIn("Sun position (computed from NOAA solar equations, no network)", html)
        self.assertIn("Public domain method", html)
        sources = read("tools/build_sources.py")
        self.assertIn('"id": "sun"', sources)

    def test_privacy_load_sentence_still_true(self) -> None:
        p = read("privacy.html")
        self.assertIn("The page loads only files hosted on this site", p)
        self.assertIn("Lantern Drift", p)


if __name__ == "__main__":
    unittest.main()
