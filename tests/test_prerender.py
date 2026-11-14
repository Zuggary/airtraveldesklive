"""AN23 phase 1 tests: pre-rendered live text, link wording, US spelling, titles and page order.

Every test builds from small fixtures written here (no git-ignored data files) and makes no network calls.
"""
from __future__ import annotations

import html
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import build_airport_pages as bap  # noqa: E402
from tools import check_links as cl  # noqa: E402
from tools import prerender_home as ph  # noqa: E402
from tools import prerender_text as pt  # noqa: E402

UPDATED = "2026-11-14T09:50:00Z"
NOW = datetime(2026, 11, 14, 9, 58, tzinfo=timezone.utc)  # 8 minutes after the data
BAD_STRINGS = ("(unchecked)", "traveller", "Loading current FAA status")


def _wx(text="clear", wind=9.0, gust=None):
    return {
        "cat": "VFR", "now_text": text, "obs_utc": "2026-11-14T09:36:00Z", "wind_kt": wind, "gust_kt": gust,
        "next3h_text": "clear through 6 am", "alert": False,
    }


def _airport(code, name, tz, level="clear", events=None, reason="", wx=None):
    return {
        "code": code, "name": name, "short": name.split()[0], "city": f"{code} City", "tz": tz,
        "lat": 33.0, "lon": -84.0, "level": level, "reason": reason, "events": events or [], "alerts": [],
        "aircraft_near": None, "wx": wx if wx is not None else _wx(),
    }


AIRPORTS = {
    "ATL": _airport("ATL", "Atlanta International", "America/New_York"),
    "DEN": _airport("DEN", "Denver International", "America/Denver", "stop",
                    [{"kind": "ground_stop"}], "thunderstorms", _wx("thunderstorms", 24.0, 35.0)),
    "ORD": _airport("ORD", "Chicago O'Hare International", "America/Chicago", "delay",
                    [{"kind": "ground_delay", "avg": "1 hour and 20 minutes"}], "low ceilings", _wx("low clouds", 0.0)),
    "JFK": _airport("JFK", "John F. Kennedy International", "America/New_York", "clear",
                    [{"kind": "closure"}], "runway work", _wx("rain", 12.0)),
    "SFO": _airport("SFO", "San Francisco International", "America/Los_Angeles", wx={}),
}


def _links(code, verified):
    base = {"label": "Airport website", "url": f"https://www.{code.lower()}.example/"}
    out = []
    for i, label in enumerate(("Airport website", "Terminal maps", "Parking", "Lost and found")):
        item = {"label": label, "url": f"https://www.{code.lower()}.example/{i}"}
        if verified is False:
            item["verified"] = False
        out.append(item)
    return out or [base]


GUIDE = {
    "version": 1, "checked_utc": "2026-11-14",
    "airports": {
        "ATL": {"operator": "City of Atlanta", "links": _links("ATL", False)},
        "DEN": {"operator": "City of Denver", "links": _links("DEN", True)},
        "ORD": {"operator": "City of Chicago", "links": _links("ORD", True)},
        "JFK": {"operator": "Port Authority", "links": _links("JFK", True)},
        "SFO": {"operator": "SF Airport Commission", "links": _links("SFO", True)},
    },
}

STATE = {
    "updated_utc": UPDATED, "stale_feeds": [],
    "events": [
        {"id": "gs:DEN", "kind": "ground_stop", "airport": "DEN", "reason": "thunderstorms", "source": "FAA",
         "sources": ["FAA"], "fields": {}},
        {"id": "gd:ORD", "kind": "ground_delay", "airport": "ORD", "reason": "low ceilings", "source": "FAA",
         "sources": ["FAA"], "fields": {"avg": "1 hour and 20 minutes"}},
    ],
}

TSA = {"latest_date": "2026-11-12", "latest_count": 2484345, "ly_date": "2025-11-13", "ly_count": 2434496,
       "fetched_utc": "2026-11-14T09:45:06Z"}


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def make_data(tmp: Path, airports=None) -> Path:
    d = tmp / "data"
    d.mkdir()
    _write(d / "airports.json", {"version": 1, "updated_utc": UPDATED, "airports": airports or AIRPORTS})
    _write(d / "airport-guide.json", GUIDE)
    _write(d / "places.json", {"fetched_utc": "2026-11-10T00:00:00Z", "airports": {}})
    shutil.copy2(ROOT / "tests" / "fixtures" / "bts-sample.json", d / "bts.json")
    _write(d / "state.json", STATE)
    _write(d / "tsa.json", TSA)
    return d


def visible_text(page: str) -> str:
    """Text a reader gets with JavaScript off: scripts, styles and tags removed."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", page, flags=re.S)
    page = re.sub(r"</?(?:a|span|em|strong|b|i)\b[^>]*>", "", page)  # inline tags do not break the text
    page = re.sub(r"<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page))


class _Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.data = make_data(tmp)
        cls.out = tmp / "airports"
        bap.build_pages(data_dir=cls.data, out_dir=cls.out, sitemap_path=None, build_date="2026-11-14", now=NOW)
        cls.pages = {p.stem: p.read_text(encoding="utf-8") for p in cls.out.glob("*.html")}
        cls.home = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), cls.data, NOW)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()


class TestAirportPrerender(_Built):
    def test_status_words_with_js_off(self):
        want = {"ATL": "No FAA delays reported", "DEN": "Ground stop", "ORD": "Ground delay program", "JFK": "Closed"}
        for code, word in want.items():
            text = visible_text(self.pages[code])
            self.assertIn(word, text, code)
            self.assertIn(f"<title>{code} airport status", self.pages[code])
        # Only the right word shows for each airport's status chip.
        self.assertNotIn("No FAA delays reported", visible_text(self.pages["DEN"]).split("Right now")[0])

    def test_weather_summary_source_and_age_as_text(self):
        atl = visible_text(self.pages["ATL"])
        self.assertIn("Weather now: clear, wind 9 kt", atl)
        self.assertIn("aviationweather.gov METAR", atl)
        self.assertIn("FAA NAS status, checked 4:50 AM EST (8 min ago)", atl)
        den = visible_text(self.pages["DEN"])
        self.assertIn("Weather now: thunderstorms, wind 24 kt gusting 35 kt", den)
        self.assertIn("FAA NAS status, checked 2:50 AM MST (8 min ago)", den)
        self.assertIn("Reason: thunderstorms", den)
        ord_text = visible_text(self.pages["ORD"])
        self.assertIn("wind calm (0 kt)", ord_text)

    def test_values_come_only_from_data(self):
        # An airport with no weather in the data shows no weather line and no invented value.
        sfo = visible_text(self.pages["SFO"])
        self.assertNotIn("Weather now:", sfo)
        self.assertIn("No FAA delays reported", sfo)

    def test_missing_airport_data_gives_plain_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_data(Path(t), airports={"ATL": AIRPORTS["ATL"]})
            out = Path(t) / "out"
            bap.build_pages(data_dir=d, out_dir=out, sitemap_path=None, build_date="2026-11-14", now=NOW)
            den = (out / "DEN.html").read_text(encoding="utf-8")
        self.assertIn("Live status loads here; the FAA's own page is nasstatus.faa.gov", visible_text(den))
        self.assertNotIn("No FAA delays reported", visible_text(den).split("Official pages")[0])

    def test_stale_data_shows_age_notice_text(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_data(Path(t))
            out = Path(t) / "out"
            later = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
            bap.build_pages(data_dir=d, out_dir=out, sitemap_path=None, build_date="2026-11-14", now=later)
            atl = visible_text((out / "ATL.html").read_text(encoding="utf-8"))
        self.assertIn("This data is 4 hours old.", atl)
        self.assertIn("FAA NAS status, checked 4:50 AM EST (4 hours ago)", atl)

    def test_description_states_the_status_in_plain_words(self):
        for code, word in (("ATL", "No FAA delays reported"), ("DEN", "Ground stop"), ("JFK", "Closed")):
            m = re.search(r'<meta name="description" content="([^"]+)"', self.pages[code])
            self.assertIn(word, m.group(1), code)
            if code == "ATL":
                self.assertIn("Checked 4:50 AM EST", m.group(1))
            self.assertLessEqual(len(m.group(1)), 200, code)

    def test_titles_short_and_open_graph_in_sync(self):
        for code in ("ATL", "DEN", "ORD", "JFK", "SFO"):
            page = self.pages[code]
            title = re.search(r"<title>(.*?)</title>", page).group(1)
            self.assertEqual(title, f"{code} airport status: is {code} delayed? Live FAA status")
            self.assertLessEqual(len(title), 60)
            og = re.search(r'property="og:title" content="([^"]+)"', page).group(1)
            tw = re.search(r'name="twitter:title" content="([^"]+)"', page).group(1)
            self.assertEqual(og, title)
            self.assertEqual(tw, title)
            ogd = re.search(r'property="og:description" content="([^"]+)"', page).group(1)
            d = re.search(r'name="description" content="([^"]+)"', page).group(1)
            self.assertEqual(ogd, d)
        idx = re.search(r"<title>(.*?)</title>", self.pages["index"]).group(1)
        self.assertLessEqual(len(idx), 60)

    def test_browser_script_refreshes_same_elements(self):
        page = self.pages["ATL"]
        for needle in ('getElementById("right-now")', 'getElementById("status-chip")', 'getElementById("checked-line")',
                       'box.textContent = ""', 'data-prerendered="1"'):
            self.assertIn(needle, page)
        # Written once in the HTML: one status chip, one right-now box, one checked line.
        for ident in ("status-chip", "right-now", "checked-line", "weather-chip"):
            self.assertEqual(page.count(f'id="{ident}"'), 1, ident)
        # The script words match the Python words, so the refresh does not change the text.
        for word in ("No FAA delays reported", "Ground delay program", "Ground stop", "Closed"):
            self.assertIn(word, page)


class TestAirportOrder(_Built):
    def test_status_first_then_bts_then_illustration(self):
        page = self.pages["SFO"]
        order = [page.index(x) for x in (
            "<h1", 'id="status-chip"', 'id="right-now-heading"', 'aria-label="On-time arrivals"',
            'class="illus-card"', 'id="glance-heading"', 'id="official-heading"')]
        self.assertEqual(order, sorted(order))

    def test_illustration_keeps_caption_and_tag(self):
        page = self.pages["SFO"]
        if "illus-card" not in page:
            self.skipTest("no illustration library in this checkout")
        self.assertIn("Illustration of a coastal airport. It does not show SFO.", visible_text(page))
        self.assertIn('class="illus-tag">Illustration<', page)
        self.assertIn('width="1280" height="720"', page)

    def test_illustration_card_css(self):
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.illus--hero\s*\{[^}]*max-width:\s*420px")
        self.assertRegex(css, r"\.illus img\s*\{[^}]*aspect-ratio:\s*16 / 9")


class TestLinkWording(_Built):
    NOTE = "Some airport sites block automatic checks, so we could not verify every link by script."

    def test_blocked_link_page_has_note_and_no_checked_claim(self):
        atl = visible_text(self.pages["ATL"])
        self.assertIn(self.NOTE, atl)
        self.assertNotIn("links checked", atl)
        self.assertNotIn("unchecked", self.pages["ATL"])
        self.assertIn("could not verify every link by script", atl.split("Where this page's data comes from")[1])

    def test_fully_checked_page_keeps_true_claim_and_no_note(self):
        den = visible_text(self.pages["DEN"])
        self.assertNotIn(self.NOTE, den)
        self.assertIn("links checked 2026-11-14", den)

    def test_no_pill_text_has_unchecked(self):
        for code, page in self.pages.items():
            self.assertNotIn("unchecked", page, code)

    def test_app_js_has_note_and_no_unchecked(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("(unchecked)", app)
        self.assertIn(self.NOTE, app)
        self.assertIn("anyBlocked", app)


class TestHomePrerender(_Built):
    def test_text_with_js_off(self):
        text = visible_text(self.home)
        self.assertIn("FAA NAS status, checked 4:50 AM EST (8 min ago)", text)
        self.assertIn("1 airport with a ground stop", text)
        self.assertIn("1 airport with delays", text)
        self.assertIn("longest: Chicago, avg 1 h 20 min", text)
        self.assertIn("Ground stop", text)
        self.assertIn("Ground delay", text)
        self.assertIn("People screened, Nov 12", text)
        self.assertIn("2.48 million", text)
        self.assertIn("Source: TSA checkpoint numbers, updated Nov 14", text)
        self.assertIn("Reason: thunderstorms", text)

    def test_all_clear_summary(self):
        with tempfile.TemporaryDirectory() as t:
            clear = {"ATL": AIRPORTS["ATL"]}
            d = make_data(Path(t), airports=clear)
            _write(d / "state.json", {"updated_utc": UPDATED, "events": []})
            page = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), d, NOW)
        text = visible_text(page)
        self.assertIn("No delays or ground stops at the 30 busiest airports right now", text)
        self.assertIn("No FAA delays or ground stops are listed right now.", text)

    def test_markers_removed_and_ids_kept_once(self):
        self.assertNotIn("<!--pr:", self.home)
        self.assertNotIn("<!--/pr:", self.home)
        for ident in ("summary", "updated-line", "events", "compare-cards", "stale-notice", "airport-search"):
            self.assertEqual(self.home.count(f'id="{ident}"'), 1, ident)

    def test_stale_notice_when_data_is_old(self):
        later = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        page = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), self.data, later)
        self.assertIn("This data is 4 hours old.", visible_text(page))
        self.assertNotIn('role="status" hidden', page.split('id="stale-notice"')[1].split("</p>")[0])

    def test_no_data_keeps_fallback_text(self):
        with tempfile.TemporaryDirectory() as t:
            page = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), Path(t), NOW)
        text = visible_text(page)
        self.assertIn("Live status loads here; the FAA's own page is nasstatus.faa.gov", text)
        self.assertNotIn("<!--pr:", page)

    def test_command_line_writes_file_and_survives_bad_template(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "site" / "index.html"
            rc = ph.main(["--template", str(ROOT / "index.html"), "--data", str(self.data), "--out", str(out),
                          "--now", "2026-11-14T09:58:00Z"])
            self.assertEqual(rc, 0)
            self.assertIn("checked 4:50 AM EST (8 min ago)", visible_text(out.read_text(encoding="utf-8")))
            bad = Path(t) / "bad.html"
            bad.write_text("<html><body><!--pr:summary-->x<!--/pr:summary--></body></html>", encoding="utf-8")
            out2 = Path(t) / "o2.html"
            ph.main(["--template", str(bad), "--data", str(self.data), "--out", str(out2)])
            self.assertIn("x", out2.read_text(encoding="utf-8"))
            self.assertNotIn("<!--pr:", out2.read_text(encoding="utf-8"))


class TestHomeTemplateAndOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tpl = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_template_is_clean_with_sensible_fallback(self):
        self.assertIn("Live status loads here; the FAA's own page is nasstatus.faa.gov", self.tpl)
        for bad in BAD_STRINGS:
            self.assertNotIn(bad, self.tpl)
        for slot in ("summary", "updated", "events", "tsa", "stale"):
            self.assertIn(f"<!--pr:{slot}-->", self.tpl)
            self.assertIn(f"<!--/pr:{slot}-->", self.tpl)

    def test_main_column_order(self):
        ids = ["airport-search", 'id="now"', 'id="changed"', 'id="board-section"', 'id="history"', 'id="map-section"',
               'id="owed"', 'id="compare"', 'id="watch"', 'id="while-you-wait"']
        pos = [self.tpl.index(i) for i in ids]
        self.assertEqual(pos, sorted(pos))
        sections = re.findall(r'<section id="([a-z-]+)"', self.tpl)
        self.assertEqual(sections[0], "airports")  # search first
        self.assertEqual(sections[1], "now")  # live status next
        self.assertEqual(sections[-1], "while-you-wait")  # Lantern Drift last
        self.assertEqual(sections[-2], "watch")  # Twitch block just above it

    def test_watch_live_text_link_near_top(self):
        link = self.tpl.index('<a class="tap" href="#watch">Watch live</a>')
        self.assertLess(link, self.tpl.index('id="airport-search"'))
        self.assertLess(link, self.tpl.index('<main'))
        # The Twitch chip and the embed button now live in the lower block.
        self.assertGreater(self.tpl.index('id="load-live"'), self.tpl.index('id="compare"'))
        self.assertGreater(self.tpl.index("twitch.tv/airtraveldesklive"), self.tpl.index('id="compare"'))

    def test_every_script_id_still_exists(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        ids = set(re.findall(r'\$\("([A-Za-z-]+)"\)', app))
        missing = sorted(i for i in ids if f'id="{i}"' not in self.tpl)
        self.assertEqual(missing, [])


class TestSpellingAndSource(unittest.TestCase):
    def test_no_bad_strings_in_site_source(self):
        files = [ROOT / n for n in ("index.html", "stuck.html", "about.html", "sources.html", "privacy.html", "tv.html",
                                    "app.js", "lib.js", "stuck.js", "sources.js", "cine.js", "sun.js", "sw.js", "style.css")]
        files += sorted((ROOT / "tools").glob("*.py")) + sorted((ROOT / "desk").glob("*.py"))
        files += [ROOT / "data" / "airport-guide.json", ROOT / "data" / "dot-commitments.json"]
        for f in files:
            if not f.is_file():
                continue
            text = f.read_text(encoding="utf-8")
            for bad in BAD_STRINGS:
                self.assertNotIn(bad, text, f"{f.name} holds {bad!r}")

    def test_no_bad_strings_in_built_pages(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_data(Path(t))
            out = Path(t) / "out"
            bap.build_pages(data_dir=d, out_dir=out, sitemap_path=None, build_date="2026-11-14", now=NOW)
            built = list(out.glob("*.html")) + [Path(t) / "home.html"]
            (Path(t) / "home.html").write_text(
                ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), d, NOW), encoding="utf-8")
            for f in built:
                text = f.read_text(encoding="utf-8")
                for bad in BAD_STRINGS:
                    self.assertNotIn(bad, text, f"{f.name} holds {bad!r}")
                if f.name == "ATL.html":
                    self.assertIn("traveler", text)


class TestWorkflow(unittest.TestCase):
    def test_prerender_and_link_check_are_wired(self):
        wf = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/prerender_home.py", wf)
        self.assertIn("--out _site/index.html", wf)
        self.assertLess(wf.index("Prepare _site directory"), wf.index("tools/prerender_home.py"))
        self.assertLess(wf.index("tools/build_airport_pages.py"), wf.index("Prepare _site directory"))
        step = wf.split("Check airport guide links")[1].split("- name:")[0]
        self.assertIn("continue-on-error: true", step)
        self.assertIn("tools/check_links.py", step)
        self.assertNotIn("link-report.json", wf.split("Prepare _site directory")[1].split("Check that every public")[0])


class _Resp:
    def __init__(self, status):
        self.status = status

    def close(self):
        pass


class TestCheckLinks(unittest.TestCase):
    def test_collect_links_keeps_only_http_urls(self):
        guide = {"airports": {"ATL": {"links": [
            {"label": "A", "url": "https://a.example/x"}, {"label": "B", "url": "javascript:alert(1)"},
            {"label": "C", "url": ""}, {"label": "D", "url": "http://d.example/"}]}}}
        got = cl.collect_links(guide)
        self.assertEqual([g["url"] for g in got], ["https://a.example/x", "http://d.example/"])

    def test_check_url_uses_head_and_names_the_site(self):
        seen = []

        def opener(req, timeout):
            seen.append((req.get_method(), req.get_header("User-agent"), timeout))
            return _Resp(200)

        res = cl.check_url("https://a.example/", opener)
        self.assertEqual(res, {"status": 200, "ok": True, "error": ""})
        self.assertEqual(seen[0][0], "HEAD")
        self.assertIn("airtraveldesklive.com", seen[0][1])
        self.assertLessEqual(seen[0][2], 15)

    def test_check_url_handles_errors_without_raising(self):
        def blocked(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

        def down(req, timeout):
            raise TimeoutError("slow")

        self.assertEqual(cl.check_url("https://a.example/", blocked), {"status": 403, "ok": False, "error": "HTTP 403"})
        res = cl.check_url("https://a.example/", down)
        self.assertEqual((res["status"], res["ok"], res["error"]), (None, False, "TimeoutError"))
        self.assertTrue(cl.check_url("https://a.example/", lambda r, t: _Resp(301))["ok"])

    def test_run_checks_dedupes_and_pauses_per_host(self):
        calls, sleeps = [], []
        clock = [100.0]

        def opener(req, timeout):
            calls.append(req.full_url)
            return _Resp(200)

        links = [
            {"code": "ATL", "label": "a", "url": "https://one.example/a"},
            {"code": "ATL", "label": "b", "url": "https://one.example/b"},
            {"code": "DEN", "label": "c", "url": "https://two.example/c"},
            {"code": "DEN", "label": "d", "url": "https://one.example/a"},
        ]
        res = cl.run_checks(links, opener, sleep=sleeps.append, clock=lambda: clock[0], host_pause=1.5)
        self.assertEqual(calls, ["https://one.example/a", "https://one.example/b", "https://two.example/c"])
        self.assertEqual(len(res), 4)
        self.assertEqual(len(sleeps), 1)  # only the second request to one.example waits
        self.assertAlmostEqual(sleeps[0], 1.5)

    def test_run_checks_limit(self):
        links = [{"code": "X", "label": "l", "url": f"https://h{i}.example/"} for i in range(5)]
        res = cl.run_checks(links, lambda r, t: _Resp(200), sleep=lambda s: None, limit=2)
        self.assertEqual(len(res), 2)

    def test_report_shape_and_freshness_and_main(self):
        rep = cl.build_report([{"ok": True}, {"ok": False}], NOW)
        self.assertEqual((rep["total"], rep["ok"], rep["failed"]), (2, 1, 1))
        self.assertEqual(rep["checked_utc"], "2026-11-14T09:58:00Z")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "link-report.json"
            guide = Path(t) / "g.json"
            guide.write_text(json.dumps({"airports": {}}), encoding="utf-8")
            self.assertEqual(cl.main(["--guide", str(guide), "--out", str(out)]), 0)  # no links: no network
            self.assertEqual(json.loads(out.read_text())["total"], 0)
            self.assertTrue(cl.report_is_fresh(out, 24))
            self.assertFalse(cl.report_is_fresh(out, 0))
            self.assertFalse(cl.report_is_fresh(Path(t) / "none.json", 24))
            old = datetime(2030, 1, 1, tzinfo=timezone.utc)
            self.assertFalse(cl.report_is_fresh(out, 24, now=old))
            # A bad guide file never fails the build.
            self.assertEqual(cl.main(["--guide", str(Path(t) / "missing.json"), "--out", str(Path(t) / "r2.json")]), 0)

    def test_report_file_is_not_committed(self):
        self.assertIn("data/link-report.json", (ROOT / ".gitignore").read_text(encoding="utf-8"))


class TestTextHelpers(unittest.TestCase):
    def test_clock_and_age(self):
        self.assertEqual(pt.clock_label(UPDATED, "America/Los_Angeles"), "1:50 AM PST")
        self.assertEqual(pt.clock_label("2026-11-14T20:05:00Z", "America/New_York"), "3:05 PM EST")
        self.assertEqual(pt.clock_label("2026-11-14T12:00:00Z", ""), "12:00 PM UTC")
        self.assertEqual(pt.clock_label("nonsense", "America/New_York"), "")
        self.assertEqual(pt.ago_text(0), "less than 1 min ago")
        self.assertEqual(pt.ago_text(125), "2 hours ago")
        self.assertEqual(pt.checked_text("bad", "", NOW), "check time unknown")


if __name__ == "__main__":
    unittest.main()
