"""AN38: the new art set. The old AN17 illustrations (WebP files, library.json, the "Illustration" pill) are gone.
No network calls, no Pillow."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "assets" / "art"
sys.path.insert(0, str(ROOT / "tools"))
import build_airport_pages as bap  # noqa: E402

LEVELS = ("clear", "delay", "stop", "closed", "night")
STEP_BASES = ("step-meal", "step-hotel", "step-rebook", "step-refund", "state-delayed", "state-cancelled")
TEXT_FILES = ("index.html", "stuck.html", "about.html", "app.js", "stuck.js", "style.css", "sw.js", "theme.js",
              "tools/build_airport_pages.py", "tools/build_airline_pages.py", ".github/workflows/status.yml")


class _Imgs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.imgs: list[dict] = []
        self.arts: list[dict] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            self.imgs.append(a)
        if "data-art" in a:
            self.arts.append(a)


def parse(html_text: str) -> _Imgs:
    p = _Imgs()
    p.feed(html_text)
    return p


def all_hero_keys() -> set[str]:
    keys = set()
    for kind in ("hub", "coastal", "mountain", "desert"):
        for lvl in LEVELS:
            for day in (False, True):
                keys.add(bap.hero_art_key(kind, lvl, day))
    return keys


class TestOldArtGone(unittest.TestCase):
    def test_folder_and_names(self) -> None:
        self.assertFalse((ROOT / "assets" / "illustrations").exists())
        for name in TEXT_FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("assets/illustrations", text, name)
            self.assertNotIn("library.json", text, name)
            self.assertNotIn("illus-tag", text, name)
            self.assertNotIn(">Illustration<", text, name)
            if name == ".github/workflows/status.yml":
                text = text.replace("assets/art/airports/*.webp", "")
            self.assertNotIn(".webp", text, name)

    def test_no_pill_or_card_css(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"\.illus[\s{,.-]")
        self.assertNotIn("illus-card", css)


class TestHeroChoice(unittest.TestCase):
    def test_key_follows_state_and_time(self) -> None:
        self.assertEqual(bap.hero_art_key("coastal", "clear", False), "airport-coastal")
        self.assertEqual(bap.hero_art_key("coastal", "clear", True), "ap-clear-day")
        self.assertEqual(bap.hero_art_key("hub", "delay", False), "ap-delay-night")
        self.assertEqual(bap.hero_art_key("hub", "delay", True), "ap-delay-day")
        self.assertEqual(bap.hero_art_key("hub", "stop", True), "ap-stop-day")
        self.assertEqual(bap.hero_art_key("hub", "closed", False), "ap-closed-night")
        self.assertEqual(bap.hero_art_key("desert", "night", True), "ap-sched-night")
        self.assertEqual(bap.hero_art_key("desert", "none", False), "airport-desert")

    def test_sun(self) -> None:
        noon = datetime(2026, 6, 21, 19, 0, tzinfo=timezone.utc)   # noon in Phoenix
        night = datetime(2026, 6, 21, 8, 0, tzinfo=timezone.utc)   # 1 a.m. in Phoenix
        self.assertTrue(bap.solar_is_day(33.43, -112.01, noon))
        self.assertFalse(bap.solar_is_day(33.43, -112.01, night))

    def test_every_hero_file_exists_and_is_small(self) -> None:
        for key in sorted(all_hero_keys()):
            sizes = bap.ART_SIZES if key.startswith("airport-") else bap.ART_STATE_SIZES
            for w in sizes:
                for ext in ("avif", "jpg"):
                    self.assertTrue((ART / f"{key}-{w}.{ext}").is_file(), f"{key}-{w}.{ext}")
            self.assertLess((ART / f"{key}-{sizes[-1]}.avif").stat().st_size, 90 * 1024, key)
            self.assertLess((ART / f"{key}-{sizes[0]}.avif").stat().st_size, 60 * 1024, key)

    def test_step_files_exist_and_are_small(self) -> None:
        for base in STEP_BASES:
            for variant in ("", "-light"):
                for ext in ("avif", "jpg"):
                    self.assertTrue((ART / f"{base}{variant}-960.{ext}").is_file(), base + variant)
                self.assertLess((ART / f"{base}{variant}-960.avif").stat().st_size, 60 * 1024, base + variant)


class TestAirportPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        data = tmp / "data"
        data.mkdir()
        for n in ("airport-guide.json", "airports.json", "places.json"):
            shutil.copy2(ROOT / "data" / n, data / n)
        shutil.copy2(ROOT / "tests" / "fixtures" / "bts-sample.json", data / "bts.json")
        cls.out = tmp / "airports"
        res = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_airport_pages.py"), "--data", str(data),
             "--out", str(cls.out), "--sitemap", str(tmp / "sitemap.xml"), "--date", "2026-11-14"],
            capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError(res.stderr or res.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_hero_art_is_decorative_and_present(self) -> None:
        pages = [p for p in self.out.glob("*.html") if p.name != "index.html"]
        self.assertEqual(len(pages), 100)
        for page in pages:
            text = page.read_text(encoding="utf-8")
            p = parse(text)
            self.assertEqual(len(p.arts), 1, page.stem)
            self.assertIn('aria-hidden="true"', text.split('data-art="')[0].rsplit("<div", 1)[1], page.stem)
            for img in p.imgs:
                self.assertIn("alt", img, page.stem)
                self.assertTrue(img.get("width") and img.get("height"), f"{page.stem}: width and height")
                self.assertNotRegex(img.get("src") or "", r"^(https?:)?//", page.stem)
            for ref in re.findall(r'(?:src|srcset)="([^"]*assets/art/[^"]*)"', text):
                for piece in ref.split(","):
                    rel = piece.strip().split(" ")[0].replace("../", "")
                    self.assertTrue((ROOT / rel).is_file(), f"{page.stem}: {rel}")
            self.assertNotIn("Illustration<", text, page.stem)
            self.assertIn(bap.ART_NOTE, text, page.stem)
            self.assertIn('src="../airport.js"', text, page.stem)            # AN43: the hero art script lives in ../airport.js
            self.assertIn("window.ATDHeroArt = update", bap.airport_js(), page.stem)

    def test_art_script_matches_python_rule(self) -> None:
        text = bap.airport_js()                       # AN43: the hero art rule ships in the shared airport.js
        self.assertIn('data-kind="', (self.out / "ATL.html").read_text(encoding="utf-8"))
        for needle in ('"ap-sched-night"', '"ap-" + lvl', '"ap-clear-day"', '"airport-" + KIND'):
            self.assertIn(needle, text)

    def test_state_changes_the_art(self) -> None:
        # the same airport with a delay level uses a different picture than the clear one
        self.assertNotEqual(bap.hero_art_key("hub", "delay", False), bap.hero_art_key("hub", "clear", False))
        self.assertEqual(len({bap.hero_art_key("hub", l, d) for l in LEVELS for d in (False, True)}), 9)


class TestStuckArt(unittest.TestCase):
    def _node(self, code: str):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        res = subprocess.run([node, "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_each_step_kind_has_art(self) -> None:
        out = self._node("const s=require('./stuck.js');const o={};"
                         "for(const [k,v] of Object.entries(s.STEPS_BY_SITUATION)){o[k]=v.map(t=>s.stepArtKey(t));}"
                         "console.log(JSON.stringify(o));")
        for key in ("meal", "hotel", "rebook", "refund"):
            self.assertTrue(any(key in v for v in out.values()), key)
        self.assertIn("refund", out["cancelled"])
        self.assertIn("rebook", out["cancelled"])
        self.assertIn("meal", out["delayed"])
        self.assertIn("hotel", out["overnight"])
        for situation, keys in out.items():
            self.assertTrue(set(keys) <= {"", "meal", "hotel", "rebook", "refund"}, situation)

    def test_step_and_state_files_named_in_js(self) -> None:
        m = self._node("const s=require('./stuck.js');console.log(JSON.stringify({a:s.STEP_ART,b:s.STATE_ART}));")
        self.assertEqual(set(m["a"]), {"meal", "hotel", "rebook", "refund"})
        self.assertEqual(set(m["b"]), {"delayed", "cancelled"})
        for base in list(m["a"].values()) + list(m["b"].values()):
            self.assertIn(base, STEP_BASES)
            self.assertTrue((ART / f"{base}-960.avif").is_file(), base)
            self.assertTrue((ART / f"{base}-light-960.avif").is_file(), base)

    def test_js_images_are_decorative_and_lazy(self) -> None:
        js = (ROOT / "stuck.js").read_text(encoding="utf-8")
        self.assertIn('img.alt = ""', js)
        self.assertIn('aria-hidden", "true"', js)
        self.assertIn('img.loading = "lazy"', js)
        self.assertIn("img.width = 960", js)
        self.assertNotRegex(js, r"https?://[^\"']*assets/art")

    def test_art_is_not_animated(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        block = css.split("/* AN38 art:")[1].split(".art-note")[0]
        self.assertNotIn("animation", block)
        self.assertNotIn("transition", block)


class TestPagesAndCss(unittest.TestCase):
    def test_home_and_stuck_art_files_exist(self) -> None:
        for name in ("index.html", "stuck.html"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for ref in re.findall(r'assets/art/[\w.-]+', text):
                self.assertTrue((ROOT / ref).is_file(), ref)
            self.assertIn("generated illustrations, not photos of real events", text, name)

    def test_art_css_has_soft_edges_and_no_box(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        block = css.split("/* AN38 art:")[1].split(".art-note")[0]
        self.assertIn("mask-image", block)
        self.assertNotIn("border:", block.split(".art-strip img")[0].replace("border-radius", ""))
        self.assertNotIn("invert(", css)
        js = (ROOT / "stuck.js").read_text(encoding="utf-8")
        self.assertIn('"-light"', js)
        self.assertIn('"atd-theme"', js)
        self.assertIn("prefers-color-scheme: light", js)

    def test_about_sentence(self) -> None:
        about = (ROOT / "about.html").read_text(encoding="utf-8")
        self.assertIn("never a real event, aircraft or airport", about)


if __name__ == "__main__":
    unittest.main()
