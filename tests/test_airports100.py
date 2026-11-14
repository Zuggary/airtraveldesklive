"""AN23 phase 1, item 6: the site covers the 100 busiest US airports (pages, search, sitemap, data jobs, links).

No network. Live data is built here from small fixtures; nothing reads a git-ignored file.
"""
from __future__ import annotations

import csv
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

from desk import wx  # noqa: E402
from desk.airports import AIRPORTS, BUSIEST_30, BUSIEST_100, CITY, SHORT, TZ, display  # noqa: E402
from tools import build_airport_links, build_airport_pages as bap, build_places, build_web  # noqa: E402
from tools import prerender_text as pt  # noqa: E402

DATA = ROOT / "data"
NEW70 = [c for c in BUSIEST_100 if c not in BUSIEST_30]
NODE = shutil.which("node")
NOW = "2026-11-14T09:55:00Z"
UPDATED = "2026-11-14T09:50:00Z"
SITE = "https://www.airtraveldesklive.com"


def _cards(skip: set[str] = frozenset(), level: dict[str, str] | None = None) -> dict:
    """A small airports.json for all 100 airports (fixture values, not real observations)."""
    cards = {}
    for code in BUSIEST_100:
        if code in skip:
            continue
        _, lat, lon = AIRPORTS[code]
        cards[code] = {
            "code": code, "name": display(code), "short": SHORT.get(code, code), "city": CITY[code], "tz": TZ[code],
            "lat": lat, "lon": lon, "level": (level or {}).get(code, "clear"), "reason": "", "events": [], "alerts": [],
            "aircraft_near": None,
            "wx": {"cat": "VFR", "now_text": "clear", "obs_utc": "2026-11-14T09:40:00Z", "wind_kt": 4.0, "gust_kt": None,
                   "next3h_text": "clear through 1 am", "next3h_cat": "VFR", "next3h_storms": False,
                   "taf_issue_utc": "2026-11-14T09:30:00Z", "alert": False, "source": "aviationweather.gov (METAR, TAF)"},
        }
    return {"version": 1, "updated_utc": UPDATED, "airports": cards}


def _build(tmp: Path, cards: dict, places: dict | None = None, more: dict | None = None, now: str = NOW) -> tuple[Path, Path]:
    data = tmp / "data"
    data.mkdir()
    for name in ("airport-guide.json", "airports-links.json"):
        shutil.copy2(DATA / name, data / name)
    shutil.copy2(ROOT / "tests" / "fixtures" / "bts-sample.json", data / "bts.json")
    (data / "airports.json").write_text(json.dumps(cards), encoding="utf-8")
    (data / "places.json").write_text(json.dumps(places or {"fetched_utc": "2026-11-13T00:00:00Z", "airports": {}}), encoding="utf-8")
    if more is not None:
        (data / "places-more.json").write_text(json.dumps(more), encoding="utf-8")
    out = tmp / "airports"
    sm = tmp / "sitemap.xml"
    sm.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                  f'  <url><loc>{SITE}/</loc></url>\n</urlset>\n', encoding="utf-8")
    res = subprocess.run([sys.executable, str(ROOT / "tools" / "build_airport_pages.py"), "--data", str(data), "--out", str(out),
                          "--sitemap", str(sm), "--date", "2026-11-14", "--now", now], capture_output=True, text=True, timeout=120)
    if res.returncode:
        raise RuntimeError(res.stderr or res.stdout)
    return out, sm


def _text(html: str) -> str:
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", body).split())


class TestAirportList(unittest.TestCase):
    def test_first_30_unchanged_and_100_listed(self) -> None:
        self.assertEqual(len(BUSIEST_100), 100)
        self.assertEqual(len(set(BUSIEST_100)), 100)
        self.assertEqual(BUSIEST_100[:30], BUSIEST_30)
        self.assertEqual(BUSIEST_30[:3], ["ATL", "DFW", "DEN"])
        for code in BUSIEST_100:
            self.assertIn(code, AIRPORTS, code)
            self.assertIn(code, TZ, code)
            self.assertIn(code, CITY, code)
            self.assertIn(code, SHORT, code)
            self.assertTrue(re.fullmatch(r"[A-Za-z_]+/[A-Za-z_/]+", TZ[code]), code)
            self.assertRegex(CITY[code], r", [A-Z]{2}$", code)


class TestPagesFromFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.missing = {"HNL", "LIT", "BHM"}   # no live data for these three: the page must say so
        places = {"fetched_utc": "2026-11-13T00:00:00Z", "airports": {
            "SFO": {"hotels": [{"name": "Test Hotel", "km": 1.2}], "cars": []}}}
        more = {"airports": {"PDX": {"hotels": [{"name": "Fixture Inn", "km": 2.0}], "cars": [{"name": "Fixture Cars", "km": 3.0}],
                                     "fetched_utc": "2026-11-12T10:00:00Z"}}}
        cls.out, cls.sitemap = _build(tmp, _cards(skip=cls.missing), places=places, more=more)
        cls.pages = {c: (cls.out / f"{c}.html").read_text(encoding="utf-8") for c in BUSIEST_100}
        cls.index = (cls.out / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_100_pages_and_the_index(self) -> None:
        names = sorted(p.name for p in self.out.glob("*.html"))
        self.assertEqual(names, sorted(["index.html"] + [f"{c}.html" for c in BUSIEST_100]))

    def test_titles_are_unique_and_name_the_code(self) -> None:
        titles = [re.search(r"<title>(.*?)</title>", html).group(1) for html in self.pages.values()]
        self.assertEqual(len(set(titles)), 100)
        for code, html in self.pages.items():
            self.assertIn(code, re.search(r"<title>(.*?)</title>", html).group(1))

    def test_each_page_has_status_text_or_an_honest_fallback(self) -> None:
        for code, html in self.pages.items():
            text = _text(html)
            if code in self.missing:
                self.assertIn("Live status loads here", text, code)
                self.assertNotIn("No FAA delays reported", text, code)
                self.assertNotIn('data-prerendered="1"', html, code)
            else:
                self.assertIn("No FAA delays reported", text, code)
                self.assertIn('data-prerendered="1"', html, code)
                self.assertIn("Weather now: clear", text, code)
                self.assertIn("Next 3 hours: clear through 1 am", text, code)

    def test_each_page_has_an_official_link_and_no_false_claims(self) -> None:
        guide = json.loads((DATA / "airport-guide.json").read_text(encoding="utf-8"))["airports"]
        links = json.loads((DATA / "airports-links.json").read_text(encoding="utf-8"))["airports"]
        for code, html in self.pages.items():
            self.assertIn("guide-pills", html, code)
            if code in NEW70:
                url = links[code]["home_link"]
                self.assertTrue(url.startswith("http"), code)
                self.assertIn(f'href="{url}"', html, code)
                self.assertIn(">Airport website</a>", html, code)
                self.assertTrue("Only the airport's own website is listed" in html, code)
                if links[code]["verified"]:
                    self.assertNotIn("Some airport sites block automatic checks", html, code)
                    self.assertIn(f"links checked {links[code]['checked']}", html, code)
                else:
                    self.assertIn("could not verify every link by script", html, code)
                    self.assertNotIn("links checked", html, code)
            else:
                self.assertIn(guide[code]["links"][0]["url"], html, code)
            for bad in ("traveller", "(unchecked)", "Loading current FAA status"):
                self.assertNotIn(bad, html, code)

    def test_places_list_only_where_there_is_data(self) -> None:
        self.assertIn("Hotels and car rental within 5 km", self.pages["SFO"])
        self.assertIn("Test Hotel", self.pages["SFO"])
        self.assertIn("Fixture Inn", self.pages["PDX"])
        self.assertIn("fetched 2026-11-12", self.pages["PDX"])
        for code in ("BHM", "HNL", "TUS"):
            self.assertNotIn("Hotels and car rental", self.pages[code], code)
            self.assertNotIn("OpenStreetMap", self.pages[code], code)
            self.assertNotIn("nearby hotels", self.pages[code], code)

    def test_new_airport_pages_say_where_the_link_comes_from(self) -> None:
        self.assertIn("OurAirports (public domain)", self.pages["BHM"])
        self.assertNotIn("OurAirports", self.pages["SFO"])

    def test_bts_block_only_with_a_number(self) -> None:
        bts = json.loads((ROOT / "tests" / "fixtures" / "bts-sample.json").read_text(encoding="utf-8"))["airports"]
        for code, html in self.pages.items():
            has = isinstance(bts.get(code), dict) and bts[code].get("ontime") is not None
            self.assertEqual("glance-ontime-num" in html, has, code)

    def test_index_lists_all_100_once(self) -> None:
        hrefs = re.findall(r'class="tap airport-index-link" href="([A-Z]{3})\.html"', self.index)
        self.assertEqual(sorted(hrefs), sorted(BUSIEST_100))
        self.assertIn("100 busiest US airports", self.index)
        self.assertNotIn("30 busiest", self.index)
        self.assertIn('id="state-hi"', self.index)
        self.assertIn('href="#state-al"', self.index)
        self.assertEqual(len(re.findall(r"<h1\b", self.index)), 1)

    def test_sitemap_has_100_airports_and_the_index(self) -> None:
        xml = self.sitemap.read_text(encoding="utf-8")
        locs = re.findall(r"<loc>([^<]+)</loc>", xml)
        airport_locs = [u for u in locs if "/airports/" in u]
        self.assertEqual(len(airport_locs), 101)
        self.assertIn(f"{SITE}/airports/index.html", airport_locs)
        for code in BUSIEST_100:
            self.assertIn(f"{SITE}/airports/{code}.html", airport_locs)
        self.assertEqual(len(set(locs)), len(locs))
        self.assertIn(f"{SITE}/", locs)

    def test_hero_type_for_new_airports(self) -> None:
        self.assertIn("Illustration of a coastal airport. It does not show HNL.", self.pages["HNL"])
        self.assertIn("Illustration of a hub airport. It does not show BHM.", self.pages["BHM"])


class TestStaleStillHonest(unittest.TestCase):
    def test_new_airport_page_two_hours_later_does_not_claim_a_clear_status_as_current(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out, _ = _build(Path(d), _cards(), now="2026-11-14T12:00:00Z")
            html = (out / "BHM.html").read_text(encoding="utf-8")
        text = _text(html)
        self.assertIn("Last known status", text)
        self.assertNotIn("Live refresh needs JavaScript", text)
        self.assertNotIn("Weather now:", text)
        self.assertIn("As of ", text)


class TestSearchFindsNewAirports(unittest.TestCase):
    @unittest.skipUnless(NODE, "node not installed")
    def test_search_by_code_city_and_name(self) -> None:
        lst = [{"code": c, "name": display(c), "short": SHORT[c], "city": CITY[c]} for c in BUSIEST_100]
        code = "const ATD=require(%s);const L=%s;const f=q=>ATD.searchAirports(L,q).map(a=>a.code);process.stdout.write(JSON.stringify({" % (
            json.dumps(str(ROOT / "lib.js")), json.dumps(lst))
        code += "bhm:f('BHM'),hnl:f('honolulu'),kona:f('kona'),gr:f('grand rapids'),ps:f('palm springs'),oma:f('eppley'),none:f('zzzzqq')}));"
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["bhm"][0], "BHM")
        self.assertEqual(got["hnl"][0], "HNL")
        self.assertEqual(got["kona"][0], "KOA")
        self.assertEqual(got["gr"][0], "GRR")
        self.assertEqual(got["ps"][0], "PSP")
        self.assertEqual(got["oma"][0], "OMA")
        self.assertEqual(got["none"], [])

    def test_home_page_text_counts(self) -> None:
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("No match among the 100 busiest airports.", index)
        self.assertNotIn("No match among the 30", index)
        self.assertIn('href="airports/index.html">All 100 busiest airports', index)
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("A.searchAirports(allAirports", app)
        self.assertIn('window.location.href = "airports/" + code + ".html"', app)
        self.assertIn("100 busiest", (ROOT / "about.html").read_text(encoding="utf-8"))

    def test_workflow_expects_100_pages_and_runs_the_places_batch(self) -> None:
        wf = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn('"$airport_count" -ne 100', wf)
        self.assertIn("Expected 100 airport pages", wf)
        self.assertIn("build_places.py --out data --more", wf)
        self.assertIn("data/places-more.json", wf)
        self.assertNotIn("-ne 30", wf)


class TestBoardDataForAll100(unittest.TestCase):
    FAA = ('<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Nov 14 09:50:00 2026 GMT</Update_Time><Delay_type><Name>Ground Stop Programs</Name>'
           '<Ground_Stop_List><Program><ARPT>BHM</ARPT><Reason>thunderstorms</Reason><End_Time>1:00 am CST.</End_Time></Program></Ground_Stop_List></Delay_type>'
           '<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay><ARPT>HNL</ARPT><Reason>volume</Reason>'
           '<Avg>20 minutes</Avg><Max>40 minutes</Max></Ground_Delay></Ground_Delay_List></Delay_type></AIRPORT_STATUS_INFORMATION>')

    def test_cards_for_100_with_levels_from_events_and_board_stays_30(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = build_web.build(Path(d), {}, self.FAA, '{"ac":[]}', {}, True)
            cards = json.loads((Path(d) / "airports.json").read_text())
        self.assertEqual(len(p["board"]), 30)
        self.assertEqual(sorted(cards["airports"]), sorted(BUSIEST_100))
        self.assertEqual(cards["airports"]["BHM"]["level"], "stop")
        self.assertEqual(cards["airports"]["HNL"]["level"], "delay")
        self.assertEqual(cards["airports"]["PNS"]["level"], "clear")
        self.assertEqual(cards["airports"]["PNS"]["city"], "Pensacola, FL")

    def test_when_the_faa_feed_fails_cards_keep_the_old_fetch_time(self) -> None:
        prev = {"updated_utc": "2026-11-14T05:00:00Z", "faa_updated_utc": "2026-11-14T04:55:00Z", "events": []}
        with tempfile.TemporaryDirectory() as d:
            real = build_web.feeds.fetch
            build_web.feeds.fetch = lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
            try:
                p = build_web.build(Path(d), prev, None, '{"ac":[]}', {}, True)
            finally:
                build_web.feeds.fetch = real
            cards = json.loads((Path(d) / "airports.json").read_text())
        self.assertIn("FAA", p["stale_feeds"])
        self.assertEqual(p["faa_updated_utc"], "2026-11-14T04:55:00Z")
        self.assertEqual(cards["updated_utc"], "2026-11-14T04:55:00Z")

    def test_fresh_feed_sets_the_fetch_time(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = build_web.build(Path(d), {}, self.FAA, '{"ac":[]}', {}, True)
            cards = json.loads((Path(d) / "airports.json").read_text())
        self.assertEqual(p["faa_updated_utc"], p["updated_utc"])
        self.assertEqual(cards["updated_utc"], p["updated_utc"])


class TestWeatherForAll100(unittest.TestCase):
    def test_icao_ids(self) -> None:
        self.assertEqual(wx.icao("SFO"), "KSFO")
        self.assertEqual(wx.icao("HNL"), "PHNL")
        self.assertEqual(wx.icao("OGG"), "PHOG")
        self.assertEqual(wx.icao("KOA"), "PHKO")
        self.assertEqual(wx.icao("LIH"), "PHLI")
        self.assertEqual(wx.icao("ANC"), "PANC")
        self.assertIsNone(wx.icao("XXX"))
        for code in BUSIEST_100:
            self.assertTrue(re.fullmatch(r"[KP][A-Z]{3}", wx.icao(code) or ""), code)

    def test_one_metar_request_and_one_taf_request_for_all_100(self) -> None:
        urls: list[str] = []
        now = datetime(2026, 11, 14, 9, 55, tzinfo=timezone.utc).timestamp()

        def fetcher(url: str) -> str:
            urls.append(url)
            ids = re.search(r"ids=([^&]+)", url).group(1).split(",")
            if "/metar" in url:
                return json.dumps([{"icaoId": i, "obsTime": now - 600, "wspd": 5, "fltCat": "VFR", "visib": 10, "clouds": [], "rawOb": ""}
                                   for i in ids])
            return "[]"
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(wx.maybe_fetch(d, now_ts=now, fetcher=fetcher), "ok")
            data = json.loads((Path(d) / "wx.json").read_text())
        self.assertEqual(len(urls), 2)
        self.assertEqual(len(re.search(r"ids=([^&]+)", urls[0]).group(1).split(",")), 100)
        self.assertEqual(sorted(data["hubs"]), sorted(BUSIEST_100))
        self.assertIn("HNL", data["hubs"])

    def test_ticker_weather_lines_stay_with_board_airports(self) -> None:
        # extras: the 70 extra airports are in wx.json for the pages, but the "Latest" list does not take them
        from desk.ticker import Ticker
        hubs = {"PNS": {"next3h_text": "storms through 2 am", "next3h_storms": True, "next3h_cat": "IFR"},
                "ATL": {"next3h_text": "storms through 2 am", "next3h_storms": True, "next3h_cat": "IFR"}}
        keep = set(BUSIEST_30)
        t = Ticker(keep_sec=3600, max_items=24)
        out = t.update(1.0e9, [], [], {"hubs": {c: h for c, h in hubs.items() if c in keep}}, {}, first_poll=True)
        text = " ".join(i["text"] for i in out)
        self.assertIn("ATL", text)
        self.assertNotIn("PNS", text)


class TestPlacesInBatches(unittest.TestCase):
    def test_small_batches_missing_first_then_oldest_and_an_hour_apart(self) -> None:
        calls: list[str] = []
        sleeps: list[float] = []

        def fetcher(q: str) -> str:
            calls.append(q)
            return json.dumps({"elements": []})
        with tempfile.TemporaryDirectory() as d:
            t0 = 1_800_000_000.0
            self.assertEqual(build_places.update_more(Path(d), now=t0, fetcher=fetcher, pause=5.0, batch=8, sleep=sleeps.append), "ok")
            self.assertEqual(len(calls), 8)
            self.assertEqual(sleeps, [5.0] * 7)                       # one query at a time, with a pause
            first = json.loads((Path(d) / "places-more.json").read_text())
            self.assertEqual(list(first["airports"]), NEW70[:8])
            self.assertEqual(build_places.update_more(Path(d), now=t0 + 600, fetcher=fetcher, sleep=sleeps.append), "skip")
            self.assertEqual(len(calls), 8)
            build_places.update_more(Path(d), now=t0 + 3700, fetcher=fetcher, sleep=lambda s: None)
            second = json.loads((Path(d) / "places-more.json").read_text())
            self.assertEqual(list(second["airports"]), NEW70[:8 + build_places.MORE_BATCH])

    def test_a_failure_keeps_the_old_entry_and_still_records_the_attempt(self) -> None:
        def boom(q: str) -> str:
            raise urllib.error.URLError("down")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build_places.update_more(Path(d), now=1_800_000_000.0, fetcher=boom, sleep=lambda s: None), "error")
            data = json.loads((Path(d) / "places-more.json").read_text())
            self.assertEqual(data["airports"], {})
            self.assertEqual(build_places.update_more(Path(d), now=1_800_000_100.0, fetcher=boom, sleep=lambda s: None), "skip")

    def test_the_first_30_are_never_asked_in_the_separate_step(self) -> None:
        asked: list[str] = []
        with tempfile.TemporaryDirectory() as d:
            t = 1_800_000_000.0
            for i in range(-(-70 // build_places.MORE_BATCH) + 1):
                build_places.update_more(Path(d), now=t + i * 4000, fetcher=lambda q: (asked.append(q), '{"elements":[]}')[1],
                                         sleep=lambda s: None)
            data = json.loads((Path(d) / "places-more.json").read_text())
        self.assertEqual(sorted(data["airports"]), sorted(NEW70))
        self.assertTrue(set(data["airports"]).isdisjoint(BUSIEST_30))


class TestOfficialLinks(unittest.TestCase):
    def test_vendored_file_has_70_airports_and_claims_only_what_was_checked(self) -> None:
        doc = json.loads((DATA / "airports-links.json").read_text(encoding="utf-8"))
        self.assertEqual(list(doc["airports"]), NEW70)
        self.assertEqual(doc["source_url"], "https://ourairports.com/data/")
        for code, e in doc["airports"].items():
            self.assertRegex(e["home_link"], r"^https?://[^\s]+$", code)
            self.assertIs(type(e["verified"]), bool, code)
            if e["verified"]:
                self.assertTrue(e["checked"], code)
                self.assertLess(e["status"], 400, code)
            self.assertIn(e["origin"], ("ourairports", "manual"), code)

    def test_builder_marks_verified_only_after_a_check(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.csv"
            with p.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["iata_code", "iso_country", "type", "home_link"])
                w.writerow(["BHM", "US", "large_airport", "https://bhm.example/"])
                w.writerow(["PNS", "US", "medium_airport", "https://pns.example/"])
                w.writerow(["DJT", "US", "large_airport", "https://pbi.example/"])
                w.writerow(["LIT", "US", "small_airport", "https://not-counted.example/"])
            no_check = build_airport_links.build(p, check=False)
            self.assertFalse(any(e["verified"] for e in no_check["airports"].values()))
            self.assertEqual(no_check["airports"]["BHM"]["home_link"], "https://bhm.example/")
            self.assertEqual(no_check["airports"]["PBI"]["home_link"], "https://pbi.example/")

            class Resp:
                def __init__(self, status: int) -> None:
                    self.status = status

                def close(self) -> None:
                    pass

            def opener(req, timeout):
                if "pns" in req.full_url:
                    raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
                return Resp(200)
            checked = build_airport_links.build(p, check=True, opener=opener, sleep=lambda s: None,
                                                now=datetime(2026, 11, 14, tzinfo=timezone.utc))
            self.assertTrue(checked["airports"]["BHM"]["verified"])
            self.assertEqual(checked["airports"]["BHM"]["checked"], "2026-11-14")
            self.assertFalse(checked["airports"]["PNS"]["verified"])
            self.assertEqual(checked["airports"]["PNS"]["status"], 403)


if __name__ == "__main__":
    unittest.main()
