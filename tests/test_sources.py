"""Tests for FA20: sources.html, tools/build_sources.py, the changed-in-the-last-hour digest, the 24 h chart data and the logo.
No network. Fixtures only: nothing here reads a git-ignored data file."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_about import parse_html  # noqa: E402
from tools import build_sources  # noqa: E402

NODE = shutil.which("node")
FIX = ROOT / "tests" / "fixtures" / "board-history-sample.json"
OWN_HOSTS = {"", "www.airtraveldesklive.com"}
PAGES = ("index.html", "about.html", "stuck.html", "privacy.html", "sources.html")


def js(expr: str, **data) -> object:
    code = "const ATD=require(%s);const DATA=%s;process.stdout.write(JSON.stringify(%s));" % (
        json.dumps(str(ROOT / "lib.js")), json.dumps(data), expr)
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestSourcesPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text, cls.p = parse_html("sources.html")

    def test_structure_and_meta(self) -> None:
        self.assertEqual(self.p.html_lang, "en")
        self.assertEqual("".join(self.p.title_parts).strip(), "Data and sources: Air Travel Desk")
        self.assertEqual(self.p.h1_count, 1)
        self.assertGreaterEqual(self.p.h2_count, 4)
        self.assertEqual(self.p.table_count, 2)
        self.assertEqual(self.p.caption_count, 2)
        canon = [l.get("href") for l in self.p.links if l.get("rel") == "canonical"]
        self.assertEqual(canon, ["https://www.airtraveldesklive.com/sources.html"])
        self.assertIn("Skip to main content", self.text)
        self.assertIn("automated and may be wrong or late", self.text)

    def test_contact_and_forbidden_strings(self) -> None:
        emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.text))
        self.assertEqual(emails, {"hello@airtraveldesklive.com"})
        lower = self.text.lower()
        for bad in ("zach", "lucas", "gmail", "adsbygoogle", "googlesyndication", "emergency"):
            self.assertNotIn(bad, lower)

    def test_no_third_party_scripts_or_links_in_head(self) -> None:
        for s in self.p.scripts:
            src = s.get("src", "")
            if src:
                self.assertIn((urlparse(src).hostname or "").lower(), OWN_HOSTS, src)
        for l in self.p.links:
            href = l.get("href", "")
            if href:
                self.assertIn((urlparse(href).hostname or "").lower(), OWN_HOSTS, href)

    def test_rows_match_the_build_list(self) -> None:
        ids = re.findall(r'<tr data-src="([a-z0-9-]+)"', self.text)
        self.assertEqual(ids, [s["id"] for s in build_sources.SOURCES])
        for s in build_sources.SOURCES:
            self.assertIn(s["page"], self.text, s["id"])
            self.assertIn(s["terms"], self.text, s["id"])
            self.assertIn(s["licence"].replace("©", "&copy;") if "&copy;" in self.text else s["licence"], self.text, s["id"])

    def test_every_site_feed_in_about_is_listed(self) -> None:
        about, _ = parse_html("about.html")
        for name in ("FAA NAS status", "National Weather Service", "aviationweather.gov", "adsb.lol", "OpenStreetMap",
                     "Natural Earth", "TSA", "Bureau of Transportation Statistics", "Airline Cancellation and Delay Dashboard"):
            self.assertIn(name, about, name)
            self.assertIn(name, self.text, name)
        self.assertIn('href="sources.html"', about)

    def test_not_used_list_present(self) -> None:
        self.assertIn('id="not-used"', self.text)
        self.assertGreaterEqual(len(build_sources.NOT_USED), 4)
        for line in build_sources.NOT_USED:
            self.assertIn(line.replace("'", "&#x27;"), self.text.replace("&#39;", "&#x27;"))

    def test_every_row_has_licence_terms_update_and_checked_cell(self) -> None:
        rows = re.findall(r'<tr data-src=.*?</tr>', self.text, flags=re.S)
        self.assertEqual(len(rows), len(build_sources.SOURCES))
        for r in rows:
            for label in ("What we use it for", "Licence and terms", "How often it updates", "Last checked"):
                self.assertIn('data-label="%s"' % label, r)
            self.assertNotIn(">Terms</a>", r)
            self.assertRegex(r, r'<td data-label="Licence and terms"><a href="[^"]+"[^>]*>[^<]+</a></td>')
            self.assertIn("src-checked", r)

    def test_script_files_exist(self) -> None:
        srcs = [s.get("src") for s in self.p.scripts if s.get("src")]
        self.assertEqual(srcs, ["lib.js", "sources.js"])
        for f in srcs:
            self.assertTrue((ROOT / f).is_file())
        js_text = (ROOT / "sources.js").read_text(encoding="utf-8")
        self.assertIn("data/sources.json", js_text)
        self.assertNotIn("http", js_text)


class TestSiteWiring(unittest.TestCase):
    def test_footer_link_on_every_page(self) -> None:
        for page in PAGES:
            _, parser = parse_html(page)
            links = [a for a in parser.footer_anchors if a.get("href") == "sources.html"]
            self.assertTrue(links, page)
            self.assertEqual(links[0].get("text"), "Data and sources", page)

    def test_airport_page_footer_links_to_sources(self) -> None:
        from tools import build_airport_pages as b
        self.assertIn('href="../sources.html"', b._render_footer())
        self.assertIn("../brand/logo.svg", b._render_header())

    def test_sitemap_sw_and_workflow(self) -> None:
        self.assertIn("https://www.airtraveldesklive.com/sources.html", (ROOT / "sitemap.xml").read_text(encoding="utf-8"))
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        for f in ("./sources.html", "./sources.js", "./brand/logo.svg", "./about.html"):
            self.assertIn('"%s"' % f, sw)
        yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        m = re.search(r"for file in ([^;]+); do", yml)
        copied = set(m.group(1).split())
        self.assertTrue({"sources.html", "sources.js"} <= copied)
        self.assertIn("tools/build_sources.py", yml)
        self.assertRegex(yml, r"for f in [^;]*\bsources\.json\b")
        self.assertLess(yml.index("tools/build_places.py"), yml.index("tools/build_sources.py"))
        self.assertLess(yml.index("tools/build_sources.py"), yml.index("Prepare _site"))

    def test_sw_cache_files_exist(self) -> None:
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        for rel in re.findall(r'"\./([^"]+\.(?:html|js|css|svg|png))"', sw):
            if rel.startswith("airports/"):
                continue  # built in CI, git-ignored
            self.assertTrue((ROOT / rel).is_file(), rel)


class TestBuildSources(unittest.TestCase):
    def test_times_come_from_data_files_and_missing_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "state.json").write_text(json.dumps({"updated_utc": "2026-11-14T09:50:00Z"}), encoding="utf-8")
            (d / "wx.json").write_text(json.dumps({"fetched_utc": "2026-11-14T09:44:42Z"}), encoding="utf-8")
            (d / "nhc.json").write_text("not json", encoding="utf-8")
            doc = build_sources.build(d, datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc))
            by = {s["id"]: s for s in doc["sources"]}
            self.assertEqual(by["faa-nas"]["checked"], "2026-11-14T09:50:00Z")
            self.assertEqual(by["aviationweather"]["checked"], "2026-11-14T09:44:42Z")
            self.assertIsNone(by["nhc"]["checked"])
            self.assertIsNone(by["spc"]["checked"])
            self.assertEqual(doc["generated_utc"], "2026-11-14T10:00:00Z")
            self.assertEqual(len(doc["sources"]), len(build_sources.SOURCES))

    def test_main_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(build_sources.main(["--out", td]), 0)
            doc = json.loads((Path(td) / "sources.json").read_text(encoding="utf-8"))
            self.assertEqual([s["id"] for s in doc["sources"]], [s["id"] for s in build_sources.SOURCES])

    def test_list_is_well_formed(self) -> None:
        ids = [s["id"] for s in build_sources.SOURCES]
        self.assertEqual(len(ids), len(set(ids)))
        for s in build_sources.SOURCES:
            for k in ("name", "page", "terms", "licence", "used_for", "update", "kind", "group"):
                self.assertTrue(s[k], (s["id"], k))
            self.assertIn(s["kind"], ("time", "date", "static", "stream"))
            self.assertTrue(s["page"].startswith("https://") or s["page"].endswith(".html"))


@unittest.skipUnless(NODE, "node not installed")
class TestChangedLastHour(unittest.TestCase):
    def setUp(self) -> None:
        self.hist = json.loads(FIX.read_text(encoding="utf-8"))
        self.board = [{"code": c, "name": c, "status": "green"} for c in ("ATL", "DFW", "DEN", "ORD", "LAX", "JFK")]

    def run_it(self, board, now):
        return js("ATD.changedLastHour(DATA.h, DATA.b, DATA.n)", h=self.hist, b=board, n=now)

    def test_lists_changes_since_reading_about_an_hour_old(self) -> None:
        for b in self.board:
            if b["code"] == "ORD":
                b["status"] = "red"
            if b["code"] == "JFK":
                b["status"] = "yellow"
            if b["code"] == "ATL":
                b["status"] = "orange"
        r = self.run_it(self.board, "2026-11-14T09:20:00Z")
        # The 08:12 reading is 68 min old and is nearest to 60.
        self.assertTrue(r["ok"])
        self.assertEqual(r["baseT"], "2026-11-14T08:12:00Z")
        got = [(c["code"], c["from"], c["to"], c["dir"]) for c in r["changes"]]
        self.assertEqual(got, [("ORD", "orange", "red", "worse"), ("ATL", "green", "orange", "worse")])

    def test_better_is_listed_after_worse(self) -> None:
        b = [dict(x) for x in self.board]
        for x in b:
            if x["code"] == "ATL":
                x["status"] = "yellow"
        r = self.run_it(b, "2026-11-14T09:20:00Z")
        self.assertEqual([(c["code"], c["dir"]) for c in r["changes"]], [("ATL", "worse"), ("JFK", "better"), ("ORD", "better")])

    def test_no_change_gives_empty_list(self) -> None:
        b = [dict(x) for x in self.board]
        for x in b:
            if x["code"] == "JFK":
                x["status"] = "yellow"
            if x["code"] == "ORD":
                x["status"] = "orange"
        r = self.run_it(b, "2026-11-14T09:20:00Z")
        self.assertTrue(r["ok"])
        self.assertEqual(r["changes"], [])

    def test_no_reading_about_an_hour_old(self) -> None:
        r = self.run_it(self.board, "2026-11-14T13:00:00Z")
        self.assertFalse(r["ok"])
        r = js("ATD.changedLastHour(null, DATA.b, DATA.n)", b=self.board, n="2026-11-14T09:20:00Z")
        self.assertFalse(r["ok"])
        r = js("ATD.changedLastHour({points: []}, DATA.b, 'nonsense')", b=self.board)
        self.assertFalse(r["ok"])

    def test_airport_missing_from_old_reading_is_skipped(self) -> None:
        b = self.board + [{"code": "ZZZ", "name": "ZZZ", "status": "red"}]
        r = self.run_it(b, "2026-11-14T09:20:00Z")
        self.assertNotIn("ZZZ", [c["code"] for c in r["changes"]])


@unittest.skipUnless(NODE, "node not installed")
class TestHistorySeries(unittest.TestCase):
    def test_counts_not_green_and_stops(self) -> None:
        hist = json.loads(FIX.read_text(encoding="utf-8"))
        rows = js("ATD.historySeries(DATA.h)", h=hist)
        self.assertEqual([(r["notGreen"], r["stops"], r["total"]) for r in rows], [(0, 0, 6), (2, 0, 6), (3, 1, 6)])

    def test_keeps_only_last_24_hours(self) -> None:
        pts = [{"hour_utc": "x", "t_utc": "2026-11-13T%02d:30:00Z" % h, "board": {"ATL": {"level": "yellow"}}} for h in range(0, 24)]
        pts.append({"hour_utc": "y", "t_utc": "2026-11-14T10:30:00Z", "board": {"ATL": {"level": "green"}}})
        rows = js("ATD.historySeries({points: DATA.p})", p=pts)
        self.assertEqual(rows[-1]["t"], "2026-11-14T10:30:00Z")
        self.assertLessEqual(len(rows), 24)
        self.assertNotIn("2026-11-13T00:30:00Z", [r["t"] for r in rows])

    def test_empty_and_bad_input(self) -> None:
        self.assertEqual(js("ATD.historySeries(null)"), [])
        self.assertEqual(js("ATD.historySeries({points:[{t_utc:'bad',board:{}}]})"), [])


@unittest.skipUnless(NODE, "node not installed")
class TestCheckedView(unittest.TestCase):
    def test_views(self) -> None:
        now = int(datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
        v = js("ATD.checkedView('time','2026-11-14T09:50:00Z',DATA.n)", n=now)
        self.assertEqual((v["text"], v["age"]), ("2026-11-14 09:50:00 UTC", "10 min ago"))
        v = js("ATD.checkedView('time','2026-11-14T04:00:00Z',DATA.n)", n=now)
        self.assertEqual(v["age"], "6 hours ago")
        self.assertIn("checked on this date", js("ATD.checkedView('date','2026-11-13',DATA.n)", n=now)["text"])
        self.assertEqual(js("ATD.checkedView('time',null,DATA.n)", n=now)["text"], "No time on file")
        self.assertEqual(js("ATD.checkedView('static',null,DATA.n)", n=now)["text"], "Static file")
        self.assertEqual(js("ATD.checkedView('stream',null,DATA.n)", n=now)["age"], None)


class TestHomePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")

    def test_digest_and_chart_sections(self) -> None:
        for needle in ('id="changed"', "Changed in the last hour", 'id="changed-list"', 'id="history"', "Last 24 hours", 'id="hist-box"'):
            self.assertIn(needle, self.html)

    def test_app_reads_history_and_builds_accessible_chart(self) -> None:
        self.assertIn('data/board-history.json', self.app)
        for needle in ('"title"', '"desc"', 'role: "img"', "aria-labelledby", "Show the numbers as a table", 'scope', "Source: FAA NAS status"):
            self.assertIn(needle, self.app)
        self.assertNotRegex(self.app, r"<script[^>]+src=\"https?://")

    def test_chart_has_no_library(self) -> None:
        for lib in ("d3", "chart.js", "plotly", "highcharts"):
            self.assertNotIn(lib, self.html.lower())

    def test_css_uses_tokens_for_chart(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        block = css[css.index("FA20: brand mark"):]
        self.assertIn("var(--amber)", block)
        self.assertIn("var(--red)", block)
        self.assertIn("var(--green)", block)
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,6}\b")


class TestLogo(unittest.TestCase):
    def test_logo_files_and_header_use(self) -> None:
        logo = (ROOT / "brand" / "logo.svg").read_text(encoding="utf-8")
        for needle in ("#0B1730", "#4CC3FF", 'rx="44"', "<circle"):
            self.assertIn(needle, logo)
        self.assertNotIn("<text", logo)
        self.assertNotIn("#FFB300", logo)
        fav = (ROOT / "favicon.svg").read_text(encoding="utf-8")
        self.assertIn("#4CC3FF", fav)
        self.assertNotIn("<text", fav)
        for page in PAGES:
            text = (ROOT / page).read_text(encoding="utf-8")
            self.assertRegex(text, r'<img class="brand-logo" src="brand/logo\.svg" width="36" height="36" alt="Air Travel Desk logo">', page)

    def test_logo_is_published(self) -> None:
        yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn("brand/*.svg", yml)


if __name__ == "__main__":
    unittest.main()
