"""AN23 phase 1 tests: pre-rendered live text, link wording, US spelling, titles and page order.

Every test builds from small fixtures written here (no git-ignored data files) and makes no network calls.
"""
from __future__ import annotations

import html
import io
import json
import re
import shutil
import subprocess
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

from tools.build_airport_pages import airport_js as _an43_airport_js  # noqa: E402
AIRPORT_JS = _an43_airport_js()


UPDATED = "2026-11-14T09:50:00Z"
NOW = datetime(2026, 11, 14, 9, 58, tzinfo=timezone.utc)  # 8 minutes after the data
NODE = shutil.which("node")
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
        self.assertIn("Weather now: clear, wind 10 mph", atl)  # AN34 r2: mph for travelers
        self.assertIn("aviationweather.gov METAR", atl)
        self.assertIn("FAA data 8 min old, checked 4:50 AM EST. Source: FAA NAS status.", atl)
        den = visible_text(self.pages["DEN"])
        self.assertIn("Weather now: thunderstorms, wind 28 mph gusting 40 mph", den)
        self.assertIn("FAA data 8 min old, checked 2:50 AM MST. Source: FAA NAS status.", den)
        # AN34 round 3: the reason is in the lead under the H1, not in a repeat FAA tile.
        self.assertIn("Reason listed: Thunderstorms", den)
        ord_text = visible_text(self.pages["ORD"])
        self.assertIn("wind calm", ord_text)

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
        self.assertIn("Checking the FAA's status page; if this stays blank see nasstatus.faa.gov", visible_text(den))
        self.assertNotIn("No FAA delays reported", visible_text(den).split("Official pages")[0])

    def test_stale_data_shows_age_notice_text(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_data(Path(t))
            out = Path(t) / "out"
            later = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
            bap.build_pages(data_dir=d, out_dir=out, sitemap_path=None, build_date="2026-11-14", now=later)
            atl = visible_text((out / "ATL.html").read_text(encoding="utf-8"))
        self.assertIn("This data is 4 hours old, not live.", atl)
        self.assertIn("Source: FAA NAS status, last checked 4:50 AM EST.", atl)
        self.assertNotIn("(4 hours ago)", atl.split("Source: FAA NAS status")[1][:60])  # AN35: the age is stated once, in the banner

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
        page = self.pages["ATL"] + AIRPORT_JS  # AN43
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
    def test_status_first_then_bts_then_help(self):
        # AN34 round 4: one "Today at" strip under the status (weather, then the record and the on-time month).
        page = self.pages["SFO"]
        order = [page.index(x) for x in (
            "<h1", 'id="status-chip"', 'id="official-heading"', 'id="right-now-heading"', 'aria-label="On-time arrivals"',
            'id="stuck-heading"', 'id="about-page-heading"', 'class="glance-details"')]
        self.assertEqual(order, sorted(order))

    def test_no_illustration_pill_or_card(self):
        page = self.pages["SFO"]
        self.assertNotIn("illus-tag", page)
        self.assertNotIn("Illustration of a", visible_text(page))
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertNotIn(".illus", css)

    def test_hero_art_is_in_the_band(self):
        page = self.pages["SFO"]
        self.assertIn('class="band-art" aria-hidden="true" data-art="', page)


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
        self.assertIn("FAA data 8 min old, checked 4:50 AM EST.", text)
        self.assertNotIn("We check every 5 minutes", text)
        self.assertIn("Ground stop at DEN. Delays at ORD.", text)
        self.assertNotIn("No FAA program does not mean your flight is on time.", text)
        self.assertIn("Denver (DEN) has a ground stop.", text)
        self.assertIn("Flights to Chicago (ORD) are held about 1 h 20 min", text)  # AN34 round 4: a known reason follows in plain words
        self.assertIn("Ground stop", text)
        self.assertIn("Ground delay", text)
        self.assertIn("People screened, Nov 12", text)
        self.assertIn("2.48 million", text)
        self.assertIn("Source: TSA checkpoint numbers, updated Nov 14", text)
        self.assertIn("Thunderstorms", text)

    def test_all_clear_summary(self):
        with tempfile.TemporaryDirectory() as t:
            clear = {"ATL": AIRPORTS["ATL"]}
            d = make_data(Path(t), airports=clear)
            _write(d / "state.json", {"updated_utc": UPDATED, "events": []})
            page = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), d, NOW)
        text = visible_text(page)
        self.assertIn("No FAA delays at the 100 busiest airports.", text)
        self.assertIn("No FAA program does not mean your flight is on time.", text)
        self.assertIn("No FAA delays or ground stops are listed right now.", text)

    def test_outside_programs_in_home_verdict(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_data(Path(t), airports={"ATL": AIRPORTS["ATL"]})
            template = (ROOT / "index.html").read_text(encoding="utf-8")
            events = [{"airport": code, "source": "FAA", "kind": "delay"} for code in ("ZZZ", "YYY", "XXX")]
            for listed, headline in (
                (events[:1], "Delays at ZZZ. The 100 busiest are clear."),
                (events, "Delays at 3 airports. The 100 busiest are clear."),
            ):
                _write(d / "state.json", {"updated_utc": UPDATED, "events": listed})
                text = visible_text(ph.prerender(template, d, NOW))
                self.assertIn(headline, text)
                self.assertNotIn("No FAA program does not mean your flight is on time.", text)
            self.assertIn("XXX, YYY, ZZZ.", text)

    def test_markers_removed_and_ids_kept_once(self):
        self.assertNotIn("<!--pr:", self.home)
        self.assertNotIn("<!--/pr:", self.home)
        for ident in ("summary", "updated-line", "events", "compare-cards", "stale-notice", "airport-search"):
            self.assertEqual(self.home.count(f'id="{ident}"'), 1, ident)

    def test_stale_notice_when_data_is_old(self):
        later = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        page = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), self.data, later)
        self.assertIn("This data is 4 hours old, not live.", visible_text(page))
        self.assertNotIn('role="status" hidden', page.split('id="stale-notice"')[1].split("</p>")[0])

    def test_no_data_keeps_fallback_text(self):
        with tempfile.TemporaryDirectory() as t:
            page = ph.prerender((ROOT / "index.html").read_text(encoding="utf-8"), Path(t), NOW)
        text = visible_text(page)
        self.assertIn("Last FAA check time unknown", text)
        self.assertNotIn("<!--pr:", page)

    def test_command_line_writes_file_and_survives_bad_template(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "site" / "index.html"
            rc = ph.main(["--template", str(ROOT / "index.html"), "--data", str(self.data), "--out", str(out),
                          "--now", "2026-11-14T09:58:00Z"])
            self.assertEqual(rc, 0)
            self.assertIn("checked 4:50 AM EST", visible_text(out.read_text(encoding="utf-8")))
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
        self.assertIn("Checking the FAA's status page; if this stays blank see nasstatus.faa.gov", self.tpl)
        for bad in BAD_STRINGS:
            self.assertNotIn(bad, self.tpl)
        for slot in ("summary", "updated", "events", "tsa", "stale"):
            self.assertIn(f"<!--pr:{slot}-->", self.tpl)
            self.assertIn(f"<!--/pr:{slot}-->", self.tpl)

    def test_main_column_order(self):
        # AN34: verdict, search first; then the programs and map, the board, the changes and travel volume, then help.
        # AN34 round 4: the page body ends on the help band; the stream and Lantern Drift are quiet footer lines.
        ids = ['id="now"', "airport-search", 'id="trouble"', 'id="map-section"', 'id="board-section"', 'id="changed"',
               'id="history"', 'id="compare"', 'id="owed"', "</main>", 'id="watch"', 'id="while-you-wait"']
        pos = [self.tpl.index(i) for i in ids]
        self.assertEqual(pos, sorted(pos))
        sections = re.findall(r'<section id="([a-z-]+)"', self.tpl.split("</main>")[0])
        self.assertEqual(sections[0], "now")  # AN32: the national answer first
        self.assertEqual(sections[-1], "owed")  # help last in the page body

    def test_watch_live_moved_to_the_footer(self):
        # Streaming links stay in the footer; YouTube only (Twitch removed 22 Nov).
        self.assertNotIn('href="#watch">Watch live</a>', self.tpl)
        footer = self.tpl[self.tpl.index('<footer'):]
        self.assertNotIn('id="load-live"', self.tpl)      # AN52: the player is the top-bar drawer (watch.js), not a footer embed
        self.assertIn("data-watch-open", footer)
        self.assertIn("youtube.com/@AirTravelDeskLive/live", footer)
        self.assertNotIn("twitch", footer.lower())   # 22 Nov: Twitch is off the site

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
        self.assertNotIn("check_links", wf)         # the slow link check runs in its own daily workflow, never in the 5-minute deploy job
        links = (ROOT / ".github" / "workflows" / "links.yml").read_text(encoding="utf-8")
        self.assertIn("tools/check_links.py", links)
        self.assertIn("continue-on-error: true", links)
        self.assertIn("timeout-minutes: 3", wf.split("other 70 airports")[1].split("- name:")[0])


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


LATER = datetime(2026, 11, 14, 21, 50, tzinfo=timezone.utc)  # 12 hours after the data
LIVE_WORDS = ("Right now", "right now", "Weather now")


def _forecast_airports():
    """SFO: window ended long before LATER. DEN: still open at LATER (ends 4 pm Mountain = 23:00 UTC)."""
    a = dict(AIRPORTS)
    a["SFO"] = _airport("SFO", "San Francisco International", "America/Los_Angeles")
    a["SFO"]["wx"]["next3h_text"] = "clear through 2 am Pacific"
    a["SFO"]["wx"]["taf_issue_utc"] = "2026-11-14T08:51:00Z"
    a["DEN"] = dict(AIRPORTS["DEN"], wx=_wx("thunderstorms", 24.0, 35.0))
    a["DEN"]["wx"]["next3h_text"] = "clear through 4 pm Mountain"
    a["DEN"]["wx"]["taf_issue_utc"] = "2026-11-14T09:30:00Z"
    return a


class TestStaleHonesty(unittest.TestCase):
    """AN23b: data older than 30 minutes drops live words and the bright all-clear look."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.data = make_data(tmp, airports=_forecast_airports())
        cls.template = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.stale_out, cls.fresh_out = tmp / "stale", tmp / "fresh"
        bap.build_pages(data_dir=cls.data, out_dir=cls.stale_out, sitemap_path=None, build_date="2026-11-14", now=LATER)
        bap.build_pages(data_dir=cls.data, out_dir=cls.fresh_out, sitemap_path=None, build_date="2026-11-14", now=NOW)
        rd = lambda d: {p.stem: p.read_text(encoding="utf-8") for p in d.glob("*.html")}  # noqa: E731
        cls.stale, cls.fresh = rd(cls.stale_out), rd(cls.fresh_out)
        cls.stale_home = ph.prerender(cls.template, cls.data, LATER)
        cls.fresh_home = ph.prerender(cls.template, cls.data, NOW)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_one_stale_limit(self):
        self.assertEqual(pt.STALE_MIN, 30)
        self.assertIn("var STALE_MIN = A.STALE_MIN;", (ROOT / "app.js").read_text(encoding="utf-8"))
        self.assertIn("var STALE_MIN = 30;", (ROOT / "lib.js").read_text(encoding="utf-8"))
        self.assertIn("var STALE_MIN = 30;", AIRPORT_JS)  # AN43: script moved to ../airport.js
        self.assertFalse(pt.is_stale(30))
        self.assertTrue(pt.is_stale(31))

    def test_age_units(self):
        self.assertEqual(pt.ago_text(5), "5 min ago")
        self.assertEqual(pt.ago_text(59), "59 min ago")
        self.assertEqual(pt.ago_text(60), "1 hour ago")
        self.assertEqual(pt.ago_text(738), "12 hours ago")
        self.assertEqual(pt.ago_text(1440), "1 day ago")
        self.assertEqual(pt.ago_text(3000), "2 days ago")
        self.assertEqual(pt.old_text(90), "1 hour old")

    def test_stale_airport_pages_have_no_live_words(self):
        for code in ("ATL", "DEN", "ORD", "JFK", "SFO"):
            page = self.stale[code]
            text = visible_text(page)
            for w in LIVE_WORDS:
                self.assertNotIn(w, text, f"{code}: {w}")
                self.assertNotIn(w, re.sub(r"<script.*?</script>", "", page, flags=re.S), f"{code} markup: {w}")
            self.assertNotIn("Live refresh", text)
            self.assertIn("Last known status", text)
            self.assertNotIn("min ago", text.replace("less than 1 min ago", ""))

    def test_stale_text_and_chip(self):
        atl = self.stale["ATL"]
        text = visible_text(atl)
        self.assertIn("As of 4:50 AM EST: no FAA delays reported", text)
        # AN34 round 3: one status block (eyebrow, H1, checked line); no repeat FAA tile.
        # AN34 round 4: the dateline line sits above the code lockup; stale, it reads "Last known status".
        self.assertIn("Last known status", text)
        self.assertIn("No FAA delays reported at Atlanta, as of", text)
        self.assertLess(text.index("Last known status"), text.index("No FAA delays reported at Atlanta, as of"))
        self.assertNotIn('class="card-status"', atl)
        self.assertIn("Source: FAA NAS status, last checked 4:50 AM EST.", text)
        self.assertIn("This data is 12 hours old, not live.", text)
        chip = re.search(r'<span id="status-chip" class="([^"]+)"', atl).group(1)
        self.assertIn("badge--stale", chip)
        self.assertNotIn("badge--clear", chip)
        self.assertNotIn("badge--clear", atl.split('id="right-now"')[1].split("</div>")[0])
        self.assertIn("As of 2:50 AM MST: ground stop", visible_text(self.stale["DEN"]))
        self.assertIn('id="weather-chip" class="badge weather-chip" hidden', atl)
        self.assertIn("12 hours ago", re.search(r'name="description" content="([^"]+)"', atl).group(1))
        self.assertNotIn("right now", re.search(r'name="description" content="([^"]+)"', atl).group(1))

    def test_notice_before_status(self):
        for code in ("ATL", "DEN", "SFO"):
            page = self.stale[code]
            self.assertLess(page.index('id="stale-notice"'), page.index('id="status-chip"'), code)
            self.assertLess(page.index('id="stale-notice"'), page.index('id="ap-verdict"'))
            self.assertNotIn('id="stale-notice" class="stale-notice" role="status" hidden', page)
        # The fresh page keeps the notice hidden.
        self.assertIn('id="stale-notice" class="stale-notice" role="status" hidden', self.fresh["ATL"])

    def test_expired_forecast_hidden_open_one_labelled(self):
        sfo = visible_text(self.stale["SFO"])
        self.assertNotIn("clear through 2 am", sfo)
        self.assertNotIn("Next 3 hours", sfo)
        den = visible_text(self.stale["DEN"])
        self.assertIn("Forecast issued 2:30 AM MST: clear through 4 pm Mountain", den)
        self.assertNotIn("Next 3 hours", den)
        # forecast_end resolves the clock in the airport zone, after the issue time.
        self.assertEqual(pt.forecast_end("clear through 2 am Pacific", "2026-11-14T08:51:00Z"),
                         datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc))
        self.assertIsNone(pt.forecast_end("clear", "2026-11-14T08:51:00Z"))

    def test_fresh_pages_keep_live_words(self):
        atl = visible_text(self.fresh["ATL"])
        # AN34 round 4: a dateline in the airport's zone replaces the "Right now" badge.
        self.assertIn("Early Saturday, 4:50 AM in Atlanta", atl)
        self.assertIn("right now", atl)
        self.assertIn("Weather now: clear, wind 10 mph", atl)
        self.assertIn("Next 3 hours:", atl)
        self.assertIn("badge badge--clear status-chip", self.fresh["ATL"])
        self.assertNotIn("badge--stale", self.fresh["ATL"].split("<script>")[0])
        self.assertNotIn("Last known status", atl)

    def test_stale_home(self):
        text = visible_text(self.stale_home)
        for w in LIVE_WORDS:
            self.assertNotIn(w, text, w)
        self.assertNotIn(" live ", text.replace("Watch live", "").replace("live video", "").replace("Live board", ""))
        self.assertIn("Last known status", text)
        self.assertIn("FAA NAS status. See last check above.", text)
        self.assertLess(self.stale_home.index('id="stale-notice"'), self.stale_home.index('id="summary"'))
        self.assertNotIn('role="status" hidden', self.stale_home.split('id="stale-notice"')[1].split("</p>")[0])

    def test_stale_home_all_clear_headline(self):
        with tempfile.TemporaryDirectory() as t:
            d = make_data(Path(t), airports={"ATL": AIRPORTS["ATL"]})
            _write(d / "state.json", {"updated_utc": UPDATED, "events": []})
            page = ph.prerender(self.template, d, LATER)
        text = visible_text(page)
        # The stale verdict explicitly dates the limited FAA listing evidence.
        self.assertIn("Last FAA check 4:50 AM (12 hours ago)", text)
        self.assertIn("No FAA programs were listed at the last check.", text)
        self.assertNotIn("right now", text)

    def test_fresh_home_keeps_live_words(self):
        text = visible_text(self.fresh_home)
        self.assertIn("Early Saturday, 4:50 AM EST", text)  # AN34 round 4: the dateline over the verdict
        self.assertIn("Ground stop at DEN. Delays at ORD.", text)
        self.assertNotIn("Last known status", text)
        self.assertEqual(self.fresh_home.count('role="status" hidden'), 1)

    def test_browser_script_wording_matches(self):
        page = self.fresh["ATL"] + AIRPORT_JS  # AN43
        for needle in ('"Last known status"', '"badge badge--stale"', '"As of "', "Last weather report: ",
                       "Forecast issued ", "forecastExpired", "function durText", '"1 hour"', "last checked "):
            self.assertIn(needle, page, needle)
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        lib = (ROOT / "lib.js").read_text(encoding="utf-8")
        for needle in ('"Last known status"', "badge--stale", "Forecast issued ", "A.isStale", "A.agoText"):
            self.assertIn(needle, app, needle)
        for needle in ("function durText", '"1 hour"', "function forecastExpired", "var STALE_MIN = 30;"):
            self.assertIn(needle, lib, needle)
        self.assertNotIn('" min ago"', app)
        self.assertNotIn('" h ago"', lib)
        self.assertNotIn("STALE_MIN = 20", app)


def _js(expr, **data):
    code = "const ATD=require(%s);const DATA=%s;process.stdout.write(JSON.stringify(%s));" % (
        json.dumps(str(ROOT / "lib.js")), json.dumps(data), expr)
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node not installed")
class TestBrowserHelpersAgree(unittest.TestCase):
    """lib.js (browser) and prerender_text.py (build) give the same words."""

    def test_age_words_match_python(self):
        for m in (0, 1, 5, 59, 60, 61, 119, 120, 738, 1439, 1440, 3000):
            self.assertEqual(_js("ATD.agoText(DATA.m)", m=m), pt.ago_text(m), m)
            self.assertEqual(_js("ATD.oldText(DATA.m)", m=m), pt.old_text(m), m)
        self.assertEqual(_js("[ATD.isStale(30), ATD.isStale(31), ATD.isStale(null)]"), [False, True, True])

    def test_forecast_window_matches_python(self):
        for text, issued in (("clear through 2 am Pacific", "2026-11-14T08:51:00Z"),
                             ("clear through 7:44 am Eastern", "2026-11-14T08:28:00Z"),
                             ("fog likely after 4 am Mountain", "2026-11-14T09:00:00Z"),
                             ("clear through 12 pm Central", "2026-11-14T09:00:00Z")):
            py = int(pt.forecast_end(text, issued).timestamp() * 1000)
            self.assertEqual(_js("ATD.forecastEnd(DATA.t, DATA.i, '')", t=text, i=issued), py, text)
        self.assertIsNone(_js("ATD.forecastEnd('clear', '2026-11-14T08:51:00Z', '')"))
        now = int(LATER.timestamp() * 1000)
        self.assertTrue(_js("ATD.forecastExpired('clear through 2 am Pacific', '2026-11-14T08:51:00Z', '', DATA.n)", n=now))
        self.assertFalse(_js("ATD.forecastExpired('clear through 4 pm Mountain', '2026-11-14T09:30:00Z', '', DATA.n)", n=now))

    def test_outside_program_leads_the_headline(self):
        # AN34 round 3: a closure at an airport outside the list must not sit under a "no delays" headline.
        out = [{"airport": "SNA", "kind": "closure"}]
        for stale, as_of, want in ((True, "as of 1:50 AM PST (12 hours ago)", "Last FAA check 1:50 AM PST (12 hours ago)"),
                                   (False, "", "Closure at SNA.")):
            self.assertEqual(ph.national_summary([], as_of, out), want)
            self.assertEqual(_js("ATD.nationalSummary([], DATA.a, DATA.o)", a=as_of, o=out), want)
        two = out + [{"airport": "PSP", "kind": "ground_delay"}]
        self.assertEqual(ph.national_summary([], "", two), _js("ATD.nationalSummary([], '', DATA.o)", o=two))
        self.assertEqual(ph.national_summary([], "", two), "Closure at SNA. Delays at PSP.")
        self.assertEqual(ph.national_summary([], ""), "Airport readings unavailable")

    def test_stale_summary_and_latest(self):
        s = _js("ATD.nationalSummary([], DATA.a)", a="as of 1:50 AM PST (12 hours ago)")
        self.assertEqual(s, "Last FAA check 1:50 AM PST (12 hours ago)")
        self.assertEqual(_js("ATD.nationalSummary([{level:'clear'}])"), "No FAA delays at the 100 busiest airports.")
        self.assertNotIn("right now", _js("ATD.impactText({kind:'closure'}, 'Denver', true)"))
        items = [{"text": "SFO · clear through 2 am Pacific (next 3 h)", "kind": "wx", "as_of_utc": "2026-11-14T08:51:00Z", "t_utc": "2026-11-14T09:50:00Z"},
                 {"text": "DEN · ground stop", "kind": "ground_stop", "t_utc": "2026-11-14T09:50:00Z"}]
        now = int(LATER.timestamp() * 1000)
        out = _js("ATD.latestItems(DATA.items, 6, DATA.n).map(function(i){return i.text})", items=items, n=now)
        self.assertEqual(out, ["DEN · ground stop"])


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
