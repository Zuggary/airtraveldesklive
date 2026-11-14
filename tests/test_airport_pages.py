"""Tests for AN16 Part B: wording fixes, static airport pages generator, sitemap, and site wiring."""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
URL_RE = re.compile(r"https?://[^\s'\"<>`]+", re.IGNORECASE)
DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive"
SITE_URL = "https://www.airtraveldesklive.com"


class _HtmlInspector(HTMLParser):
    """Extract visible text, headings, links, metas, and JSON-LD scripts from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.lang: str | None = None
        self.headings: list[int] = []
        self.visible_parts: list[str] = []
        self.anchors: list[dict[str, str]] = []
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.json_ld: list[str] = []
        self._skip_depth = 0
        self._in_json_ld = False
        self._json_ld_buf: list[str] = []
        self._cur_a: dict[str, str] | None = None
        self._cur_a_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t == "html":
            self.lang = attr_map.get("lang")
        elif t in ("script", "style"):
            self._skip_depth += 1
            if t == "script" and attr_map.get("type") == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_buf = []
        elif t in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(t[1]))
        elif t == "meta":
            self.metas.append(attr_map)
        elif t == "link":
            self.links.append(attr_map)
        elif t == "a":
            self._cur_a = dict(attr_map)
            self._cur_a_text = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style"):
            if self._in_json_ld:
                self.json_ld.append("".join(self._json_ld_buf))
                self._in_json_ld = False
            self._skip_depth = max(0, self._skip_depth - 1)
        elif t == "a" and self._cur_a is not None:
            self._cur_a["text"] = "".join(self._cur_a_text).strip()
            self.anchors.append(self._cur_a)
            self._cur_a = None
            self._cur_a_text = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_buf.append(data)
        if self._skip_depth == 0:
            self.visible_parts.append(data)
        if self._cur_a is not None:
            self._cur_a_text.append(data)

    @property
    def visible_text(self) -> str:
        return " ".join("".join(self.visible_parts).split())


def _inspect(html_text: str) -> _HtmlInspector:
    p = _HtmlInspector()
    p.feed(html_text)
    p.close()
    return p


class TestAirportPagesGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.guide = json.loads((DATA_DIR / "airport-guide.json").read_text(encoding="utf-8"))
        cls.airports_data = json.loads((DATA_DIR / "airports.json").read_text(encoding="utf-8"))
        cls.places = json.loads((DATA_DIR / "places.json").read_text(encoding="utf-8"))
        # data/bts.json is built in CI after the tests run, so the tests use their own small BTS sample
        # (the same shape and real values) and a private data folder for the generator.
        cls._data_tmp = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls._data_tmp.name)
        for name in ("airport-guide.json", "airports.json", "places.json"):
            shutil.copy2(DATA_DIR / name, cls.data_dir / name)
        shutil.copy2(ROOT / "tests" / "fixtures" / "bts-sample.json", cls.data_dir / "bts.json")
        cls.bts = json.loads((cls.data_dir / "bts.json").read_text(encoding="utf-8"))

        cls.allowed_urls: set[str] = {
            DOWNTIME_URL,
            f"{SITE_URL}/",
            f"{SITE_URL}/og.png",
            f"{SITE_URL}/airports/index.html",
            "https://schema.org",
            "https://www.openstreetmap.org",
            "https://www.openstreetmap.org/",
            "https://www.openstreetmap.org/copyright",
            "https://www.adsb.lol",
            "https://www.adsb.lol/",
            "https://nasstatus.faa.gov",
        }
        for code, entry in cls.guide["airports"].items():
            cls.allowed_urls.add(f"{SITE_URL}/airports/{code}.html")
            for item in entry.get("links") or []:
                if item.get("url"):
                    cls.allowed_urls.add(item["url"])
        for entry in (cls.places.get("airports") or {}).values():
            for kind in ("hotels", "cars"):
                for item in entry.get(kind) or []:
                    if item.get("website"):
                        cls.allowed_urls.add(item["website"])

        cls._tmp = tempfile.TemporaryDirectory()
        cls.out_dir = Path(cls._tmp.name) / "airports"
        cls.sitemap_path = Path(cls._tmp.name) / "sitemap.xml"
        cls.sitemap_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'  <url><loc>{SITE_URL}/</loc><lastmod>2026-11-14</lastmod></url>\n'
            "</urlset>\n",
            encoding="utf-8",
        )
        res = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "build_airport_pages.py"),
                "--data",
                str(cls.data_dir),
                "--out",
                str(cls.out_dir),
                "--now",
                "2026-11-14T09:55:00Z",
                "--sitemap",
                str(cls.sitemap_path),
                "--date",
                "2026-11-14",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            raise RuntimeError(res.stderr or res.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_sfo_zone_name_bts_scope_and_status_script(self) -> None:
        text = (self.out_dir / "SFO.html").read_text(encoding="utf-8")
        p = _inspect(text)
        self.assertIn("Pacific Time", p.visible_text)
        self.assertNotIn("America/Los_Angeles", p.visible_text)
        self.assertIn('var TZ = "America/Los_Angeles";', text)
        self.assertIn("On-time arrivals, " + self.bts["month_label"] + ", BTS", p.visible_text)
        for needle in ("FAA NAS status", "aviationweather.gov METAR", "checked ", "min ago", "timeZoneName"):
            self.assertIn(needle, text)

    def test_generates_30_pages_and_index(self) -> None:
        html_files = sorted(p.name for p in self.out_dir.glob("*.html"))
        expected = sorted(["index.html"] + [f"{c}.html" for c in self.guide["airports"]])
        self.assertEqual(html_files, expected)
        self.assertEqual(len(html_files), 31)

    def test_each_page_structure_wording_links_and_urls(self) -> None:
        codes = list(self.guide["airports"].keys())
        for fname in ["index.html"] + [f"{c}.html" for c in codes]:
            text = (self.out_dir / fname).read_text(encoding="utf-8")
            p = _inspect(text)
            self.assertEqual(p.lang, "en", fname)
            self.assertEqual(p.headings.count(1), 1, f"{fname} must have exactly one h1")
            for prev, cur in zip(p.headings, p.headings[1:]):
                self.assertLessEqual(cur, prev + 1, f"{fname} skipped heading level: {p.headings}")

            self.assertNotIn("Last checked", p.visible_text, fname)
            self.assertNotIn("live-dot", text, fname)
            self.assertNotIn("America/", p.visible_text, fname)
            if fname == "index.html":
                self.assertIn("Page built 2026-11-14.", p.visible_text)
            else:
                self.assertIn("FAA NAS status, checked ", p.visible_text, fname)
                self.assertEqual(text.count(">Live board<"), 2, f"{fname}: header chip and footer link only")
                self.assertNotIn("btn-primary", text, fname)
                self.assertIn("var TZ = ", text, fname)
            self.assertIn("Where this page's data comes from", p.visible_text, fname)
            self.assertIn("Skip to main content", p.visible_text, fname)

            vis_lower = p.visible_text.lower()
            raw_lower = text.lower()
            for forbidden in ("zach", "lucas"):
                self.assertNotIn(forbidden, vis_lower, f"{forbidden} in visible text of {fname}")
            self.assertNotIn("must cover", raw_lower, fname)
            self.assertNotIn("you're owed", raw_lower, fname)

            # Single JSON-LD BreadcrumbList only
            self.assertEqual(len(p.json_ld), 1, fname)
            ld = json.loads(p.json_ld[0])
            self.assertEqual(ld.get("@type"), "BreadcrumbList", fname)

            # Allowed URLs only
            found_urls = {html.unescape(u) for u in URL_RE.findall(text)}
            unexpected = found_urls - self.allowed_urls
            self.assertEqual(unexpected, set(), f"Unexpected URLs in {fname}: {unexpected}")

            if fname != "index.html":
                code = fname[:-5]
                name = self.airports_data["airports"][code]["name"]
                self.assertIn(code, p.visible_text, fname)
                self.assertIn(name, p.visible_text, fname)
                self.assertIn('id="status-chip"', text, fname)
                self.assertIn('id="weather-chip"', text, fname)
                self.assertIn("I'm stuck guide", p.visible_text, fname)
                self.assertIn("what you may be owed", vis_lower, fname)
                self.assertIn("not legal advice", vis_lower, fname)
                self.assertIn("© OpenStreetMap contributors", p.visible_text, fname)
                self.assertIn("We show no prices and do not know what is available", p.visible_text, fname)
                self.assertIn("Live refresh needs JavaScript. The status above is from the last site build", p.visible_text, fname)
                self.assertIn("About this page", p.visible_text, fname)
                self.assertIn("independent and not affiliated with the airport, the faa or any airline", vis_lower, fname)
                self.assertIn('href="../about.html"', text, fname)
                self.assertIn('class="stuck-note"', text, fname)
                self.assertIn('class="guide-pills"', text, fname)

                guide_links = self.guide["airports"][code]["links"]
                hrefs = {a.get("href") for a in p.anchors}
                for item in guide_links:
                    self.assertIn(item["url"], hrefs, f"{code} missing guide link {item['url']}")
                if len(guide_links) >= 4:
                    self.assertGreaterEqual(len(guide_links), 4)
                else:
                    self.assertIn("Fewer than 4 official links", text)
                if any(item.get("verified") is False for item in guide_links):
                    self.assertIn("Some airport sites block automatic checks, so we could not verify every link by script.", p.visible_text, code)
                    self.assertNotIn("(unchecked)", text, code)

                places_entry = (self.places.get("airports") or {}).get(code) or {}
                hotels = [x for x in (places_entry.get("hotels") or []) if x.get("name")]
                cars = [x for x in (places_entry.get("cars") or []) if x.get("name")]
                if len(hotels) > 5:
                    self.assertIn(f"Show all {len(hotels)} hotels", p.visible_text, code)
                else:
                    self.assertNotIn(" hotels</summary>", text, code)
                if len(cars) > 5:
                    self.assertIn(f"Show all {len(cars)} car rental places", p.visible_text, code)
                else:
                    self.assertNotIn(" car rental places</summary>", text, code)

                if code in self.bts.get("airports", {}):
                    self.assertIn('class="glance-ontime"', text, code)
                    self.assertIn("On-time arrivals, ", p.visible_text, code)
                    self.assertIn("flights counted", p.visible_text, code)
                    self.assertIn("BTS counts a flight on time if it arrives less than 15 minutes late", text, code)
                else:
                    self.assertNotIn('class="glance-ontime"', text, code)

    def test_missing_bts_airport_omits_bts_definition_and_rate(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            data_sub = tmp / "data"
            data_sub.mkdir()
            for name in ("airport-guide.json", "airports.json", "places.json"):
                shutil.copy2(DATA_DIR / name, data_sub / name)
            bts_copy = json.loads((ROOT / "tests" / "fixtures" / "bts-sample.json").read_text(encoding="utf-8"))
            bts_copy["airports"].pop("SFO", None)
            (data_sub / "bts.json").write_text(json.dumps(bts_copy), encoding="utf-8")

            out = tmp / "out"
            res = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "build_airport_pages.py"),
                    "--data",
                    str(data_sub),
                    "--out",
                    str(out),
                    "--date",
                    "2026-11-14",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            sfo_text = (out / "SFO.html").read_text(encoding="utf-8")
            self.assertNotIn("BTS counts a flight on time", sfo_text)
            self.assertNotIn("On-time arrivals, ", sfo_text)
            self.assertNotIn('class="glance-ontime"', sfo_text)
            self.assertIn('id="status-chip"', sfo_text)
            self.assertIn("About this page", sfo_text)

    def test_deterministic_output_and_sitemap_block(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            out1, out2 = tmp / "out1", tmp / "out2"
            sm1, sm2 = tmp / "s1.xml", tmp / "s2.xml"
            base_sm = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f'  <url><loc>{SITE_URL}/</loc><lastmod>2026-11-14</lastmod></url>\n'
                "</urlset>\n"
            )
            sm1.write_text(base_sm, encoding="utf-8")
            sm2.write_text(base_sm, encoding="utf-8")

            for out, sm, dt in ((out1, sm1, "2026-11-14"), (out2, sm2, "2026-11-15")):
                res = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tools" / "build_airport_pages.py"),
                        "--data",
                        str(self.data_dir),
                        "--out",
                        str(out),
                        "--now",
                "2026-11-14T09:55:00Z",
                "--sitemap",
                        str(sm),
                        "--date",
                        dt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(res.returncode, 0, res.stderr)

            # Same date run matches out1 byte-for-byte
            for p in out1.glob("*.html"):
                self.assertEqual(p.read_text(encoding="utf-8"), (self.out_dir / p.name).read_text(encoding="utf-8"))

            # Different date differs ONLY by the date string
            for p in out1.glob("*.html"):
                t1 = p.read_text(encoding="utf-8")
                t2 = (out2 / p.name).read_text(encoding="utf-8").replace("2026-11-15", "2026-11-14")
                self.assertEqual(t1, t2, p.name)
            self.assertEqual(
                sm1.read_text(encoding="utf-8"),
                sm2.read_text(encoding="utf-8").replace("2026-11-15", "2026-11-14"),
            )

            # Running twice on the same sitemap replaces the block instead of duplicating it
            res2 = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "build_airport_pages.py"),
                    "--out",
                    str(out1),
                    "--now",
                "2026-11-14T09:55:00Z",
                "--sitemap",
                    str(sm1),
                    "--date",
                    "2026-11-14",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(res2.returncode, 0, res2.stderr)
            sm_text = sm1.read_text(encoding="utf-8")
            self.assertEqual(sm_text.count("<!-- airports:begin -->"), 1)
            self.assertEqual(sm_text.count("<!-- airports:end -->"), 1)
            self.assertIn(f"{SITE_URL}/airports/index.html", sm_text)
            self.assertIn(f"{SITE_URL}/airports/SFO.html", sm_text)


class TestPartBWiringAndWording(unittest.TestCase):
    def test_wording_fixes_on_site_files_and_tv_untouched(self) -> None:
        for name in ("index.html", "app.js", "stuck.js", "stuck.html", "about.html"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("you're owed", text.lower(), name)

        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("Delayed? What you may be owed", index_html)
        self.assertIn("Check what you may be owed", index_html)

        tv_html = (ROOT / "tv.html").read_text(encoding="utf-8")
        self.assertIn("Delayed? Check what you're owed", tv_html)

        stuck_js = (ROOT / "stuck.js").read_text(encoding="utf-8")
        self.assertNotIn("may be possibly owed", stuck_js.lower())
        # Result screen builds "possibly owed" only in buildEmailDraft (once per screen)
        self.assertEqual(stuck_js.lower().count("possibly owed"), 2)  # cancelled vs else branch in buildEmailDraft
        self.assertEqual(stuck_js.lower().count("not legal advice"), 1)

    def test_airport_guide_heading_and_wiring(self) -> None:
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("· official pages", app_js)
        self.assertIn("Open the full ", app_js)
        self.assertIn('"airports/"', app_js)

        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn("/* AN16 airport pages */", css)

        for name in ("index.html", "about.html"):
            _, p = (_inspect((ROOT / name).read_text(encoding="utf-8")), None)
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn('href="airports/index.html">Airports</a>', text, name)

        sw_js = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn("./airports/index.html", sw_js)
        self.assertNotIn("./airports/SFO.html", sw_js)

        yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/build_airport_pages.py", yml)
        self.assertIn("_site/airports", yml)

        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("<!-- airports:begin -->", sitemap)
        self.assertIn("<!-- airports:end -->", sitemap)
        self.assertIn(f"{SITE_URL}/airports/index.html", sitemap)


if __name__ == "__main__":
    unittest.main()
