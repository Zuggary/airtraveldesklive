"""AN17: the illustration library and every place a page shows one. No network calls, no Pillow."""
from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ILLUS = ROOT / "assets" / "illustrations"
LIB = json.loads((ILLUS / "library.json").read_text(encoding="utf-8"))
BY_FILE = {i["file"]: i for i in LIB["images"]}
sys.path.insert(0, str(ROOT / "tools"))
import build_airport_pages as bap  # noqa: E402


def webp_size(path: Path) -> tuple[int, int]:
    """Width and height from a RIFF/WEBP header (VP8, VP8L or VP8X), without Pillow."""
    d = path.read_bytes()
    if d[:4] != b"RIFF" or d[8:12] != b"WEBP":
        raise ValueError("not RIFF/WEBP")
    kind = d[12:16]
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", d[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        bits = struct.unpack("<I", d[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8X":
        return int.from_bytes(d[24:27], "little") + 1, int.from_bytes(d[27:30], "little") + 1
    raise ValueError("unknown WebP chunk " + repr(kind))


class _FigureScan(HTMLParser):
    """Collect every <img> with its alt, and whether it sits in a <figure> whose figcaption says Illustration."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.figs: list[dict] = []
        self.imgs: list[dict] = []
        self.in_caption = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "figure":
            self.figs.append({"caption": "", "imgs": []})
            self.stack.append("figure")
        elif tag == "figcaption":
            self.in_caption = True
        elif tag == "img":
            rec = {"src": a.get("src") or "", "alt": a.get("alt"), "loading": a.get("loading"),
                   "width": a.get("width"), "height": a.get("height"),
                   "fig": self.figs[-1] if "figure" in self.stack else None}
            self.imgs.append(rec)
            if rec["fig"] is not None:
                rec["fig"]["imgs"].append(rec)

    def handle_endtag(self, tag):
        if tag == "figure" and "figure" in self.stack:
            self.stack.remove("figure")
        elif tag == "figcaption":
            self.in_caption = False

    def handle_data(self, data):
        if self.in_caption and self.figs:
            self.figs[-1]["caption"] += data


def scan(html_text: str) -> list[dict]:
    p = _FigureScan()
    p.feed(html_text)
    return [i for i in p.imgs if "assets/illustrations" in i["src"]]


def check_img(tc: unittest.TestCase, img: dict, where: str) -> None:
    tc.assertIsNotNone(img["fig"], f"{where}: illustration outside a <figure>")
    tc.assertIn("Illustration", img["fig"]["caption"], f"{where}: no Illustration tag")
    tc.assertTrue((img["alt"] or "").strip(), f"{where}: empty alt")
    tc.assertEqual(img["loading"], "lazy", where)
    tc.assertTrue(img["width"] and img["height"], f"{where}: no width/height")
    tc.assertFalse(re.match(r"^(https?:)?//", img["src"]), f"{where}: other host")


class TestLibrary(unittest.TestCase):
    def test_library_matches_files(self) -> None:
        on_disk = {p.name for p in ILLUS.glob("*.webp")}
        self.assertEqual(on_disk, set(BY_FILE))
        self.assertEqual(len(BY_FILE), len(LIB["images"]), "duplicate file in library.json")

    def test_every_entry(self) -> None:
        for name, e in BY_FILE.items():
            self.assertTrue(e["alt"].strip(), name)
            self.assertEqual(e["tag"], "Illustration", name)
            self.assertIn(e["role"], ("meaning", "decoration"), name)
            path = ILLUS / name
            self.assertLess(path.stat().st_size, 150 * 1024, name)
            self.assertEqual(webp_size(path), (1280, 720), name)

    def test_no_rebook_image(self) -> None:
        self.assertFalse([n for n in BY_FILE if "stuck-rebook" in n])


class TestPages(unittest.TestCase):
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
            capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(res.stderr or res.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_airport_pages_hero(self) -> None:
        # AN32: the generic hero drawing is gone from airport pages.
        pages = [p for p in self.out.glob("*.html") if p.name != "index.html"]
        self.assertEqual(len(pages), 100)
        for page in pages:
            self.assertEqual(scan(page.read_text(encoding="utf-8")), [], page.stem)

    def test_airport_types(self) -> None:
        first30 = set("ATL DFW DEN ORD LAX JFK LAS MCO MIA CLT SEA PHX EWR SFO IAH BOS FLL MSP LGA DTW PHL SLC BWI IAD SAN DCA TPA BNA AUS MDW".split())
        self.assertEqual(
            {c for c, t in bap.AIRPORT_TYPE.items() if t == "coastal" and c in first30},
            set("SFO LAX SAN SEA MIA FLL TPA BOS JFK LGA EWR".split()))
        self.assertEqual({c for c, t in bap.AIRPORT_TYPE.items() if t == "mountain" and c in first30}, {"DEN", "SLC"})
        self.assertEqual({c for c, t in bap.AIRPORT_TYPE.items() if t == "desert" and c in first30}, {"PHX", "LAS"})
        # the other 70: every typed airport is on the list, and the Hawaii airports are coastal
        from desk.airports import BUSIEST_100
        self.assertTrue(set(bap.AIRPORT_TYPE) <= set(BUSIEST_100))
        for c in ("HNL", "OGG", "KOA", "LIH", "ANC"):
            self.assertEqual(bap.airport_type(c), "coastal", c)
        self.assertEqual(bap.airport_type("TUS"), "desert")
        self.assertEqual(bap.airport_type("BOI"), "mountain")
        self.assertEqual(bap.airport_type("BHM"), "hub")
        self.assertEqual(bap.airport_type("ATL"), "hub")

    def test_hero_choice_is_stable(self) -> None:
        for code in ("SFO", "DEN", "PHX", "ATL"):
            a = bap.pick_hero_illustration(code, LIB)
            self.assertEqual(a, bap.pick_hero_illustration(code, LIB))

    def test_index_airports_page_has_no_illustration(self) -> None:
        self.assertEqual(scan((self.out / "index.html").read_text(encoding="utf-8")), [])


class TestStaticFiles(unittest.TestCase):
    def test_html_pages(self) -> None:
        for name in ("index.html", "stuck.html", "about.html", "sources.html", "privacy.html"):
            for img in scan((ROOT / name).read_text(encoding="utf-8")):
                check_img(self, img, name)

    def test_no_other_host_and_no_rebook(self) -> None:
        for name in ("index.html", "stuck.html", "app.js", "stuck.js", "style.css", "sw.js", "tools/build_airport_pages.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("stuck-rebook", text, name)
            for m in re.finditer(r"""(?:https?:)?//[^\s"'<>)]*illustrations[^\s"'<>)]*""", text):
                self.fail(f"{name}: illustration from another host: {m.group(0)}")

    def _js_map(self, js_text: str, var: str) -> dict:
        m = re.search(r"var " + var + r" = (\{.*?\n  \});", js_text, re.S)
        self.assertTrue(m, var)
        return json.loads(m.group(1))

    def test_stuck_js_images(self) -> None:
        js = (ROOT / "stuck.js").read_text(encoding="utf-8")
        m = self._js_map(js, "STEP_ILLUSTRATIONS")
        self.assertEqual(set(m), {"stuck-meal", "stuck-hotel"})
        for cat, info in m.items():
            e = BY_FILE[info["file"]]
            self.assertEqual(e["category"], cat)
            self.assertEqual(e["role"], "meaning")
            self.assertEqual(info["alt"], e["alt"])
        self.assertIn('"figure"', js)
        self.assertIn('"figcaption", "illus-tag", "Illustration"', js)
        self.assertIn('img.loading = "lazy"', js)
        self.assertIn("img.alt = info.alt", js)
        self.assertEqual(len(re.findall(r'"assets/illustrations/"', js)), 1)

    def test_stuck_steps_only_meal_and_hotel(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        code = (
            "const s=require('./stuck.js');const out={};"
            "for(const [k,v] of Object.entries(s.STEPS_BY_SITUATION)){out[k]=v.map(t=>s.stepIllustrationKey(t));}"
            "console.log(JSON.stringify(out));"
        )
        res = subprocess.run([node, "-e", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        for situation, keys in out.items():
            self.assertTrue(set(keys) <= {"", "stuck-meal", "stuck-hotel"}, situation)
        steps = json.loads(subprocess.run(
            [node, "-e", "console.log(JSON.stringify(require('./stuck.js').STEPS_BY_SITUATION))"],
            cwd=ROOT, capture_output=True, text=True, timeout=30).stdout)
        for situation, texts in steps.items():
            for text, key in zip(texts, out[situation]):
                if re.search(r"rebook|refund|earlier flight", text, re.I) and not re.search(r"meal|hotel", text, re.I):
                    self.assertEqual(key, "", text)
        self.assertIn("stuck-meal", out["delayed"])
        self.assertIn("stuck-hotel", out["overnight"])

    def test_app_js_latest_map(self) -> None:
        js = (ROOT / "app.js").read_text(encoding="utf-8")
        m = self._js_map(js, "ILLUSTRATIONS")
        for cat, info in m.items():
            e = BY_FILE[info["file"]]
            self.assertEqual(e["category"], cat)
            self.assertEqual(e["role"], "meaning", f"{cat} uses a decoration image")
            self.assertEqual(info["alt"], e["alt"])
        for cat in ("ground-stop", "closure", "delay", "storm-hub", "fog", "wind", "snow-ice", "holding"):
            self.assertIn(cat, m)
        self.assertIn('"figure"', js)
        self.assertIn('"figcaption", "illus-tag", "Illustration"', js)
        self.assertIn('img.loading = "lazy"', js)
        self.assertIn("img.alt = info.alt", js)
        self.assertIn('"illus--thumb", 96, 54', js)
        self.assertIn('"tsa-record"', js)
        self.assertIn('illustrationFigure("holiday"', js)

    def test_no_decoration_in_use(self) -> None:
        used = set()
        for name in ("app.js", "stuck.js", "index.html", "stuck.html"):
            used |= set(re.findall(r"([a-z-]+-\d+\.webp)", (ROOT / name).read_text(encoding="utf-8")))
        for f in used:
            self.assertEqual(BY_FILE[f]["role"], "meaning", f)

    def test_sw_and_workflow(self) -> None:
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertNotIn(".webp", sw)
        self.assertNotIn("library.json", sw.split("STATIC_FILES = [")[1].split("];")[0])
        self.assertIn("assets/illustrations/", sw)
        wf = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn("cp assets/illustrations/*.webp assets/illustrations/library.json _site/assets/illustrations/", wf)

    def test_about_sentence(self) -> None:
        about = (ROOT / "about.html").read_text(encoding="utf-8")
        self.assertIn("Illustrations are generated images in a house style. They are decoration. They do not show real events.", about)


if __name__ == "__main__":
    unittest.main()
