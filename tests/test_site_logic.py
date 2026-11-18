"""Tests for lib.js (search, commitments rules, summary) and the data files. Needs node for the lib.js tests."""
import json, shutil, subprocess, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desk.airports import BUSIEST_30  # noqa: E402
from tools import build_web  # noqa: E402

NODE = shutil.which("node")
AIRPORTS = [{"code": c, "name": build_web.display(c), "short": build_web.SHORT.get(c, c), "city": build_web.CITY[c]} for c in BUSIEST_30]


def js(expr, **data):
    """Run a JS expression with ATD (lib.js) and DATA (the kwargs as JSON); return the JSON result."""
    code = "const ATD=require(%s);const DATA=%s;process.stdout.write(JSON.stringify(%s));" % (
        json.dumps(str(ROOT / "lib.js")), json.dumps(data), expr)
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node not installed")
class TestSearch(unittest.TestCase):
    def find(self, q):
        return [a["code"] for a in js("ATD.searchAirports(DATA.list, DATA.q)", list=AIRPORTS, q=q)]

    def test_san_fran_finds_sfo(self):
        self.assertEqual(self.find("san fran")[0], "SFO")
        self.assertNotIn("SAN", self.find("san fran"))

    def test_code_city_and_name(self):
        self.assertEqual(self.find("SFO")[0], "SFO")
        self.assertEqual(self.find("sfo")[0], "SFO")
        self.assertEqual(self.find("newark")[0], "EWR")
        self.assertEqual(self.find("o'hare")[0], "ORD")
        self.assertEqual(self.find("kennedy")[0], "JFK")
        self.assertIn("MDW", self.find("chicago"))
        self.assertEqual(self.find("san diego")[0], "SAN")

    def test_empty_and_nonsense(self):
        self.assertEqual(self.find(""), [])
        self.assertEqual(self.find("zzzzqq"), [])

    def test_deep_link(self):
        codes = list(BUSIEST_30)
        self.assertEqual(js("ATD.airportFromSearch('?airport=sfo', DATA.codes)", codes=codes), "SFO")
        self.assertEqual(js("ATD.airportFromSearch('?airport=XXX', DATA.codes)", codes=codes), "")
        self.assertEqual(js("ATD.airportFromSearch('', DATA.codes)", codes=codes), "")


@unittest.skipUnless(NODE, "node not installed")
class TestCommitments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "data" / "dot-commitments.json").read_text())

    def view(self, airline):
        return js("ATD.commitmentView(DATA.c, DATA.id)", c=self.data, id=airline)

    def test_ten_airlines_and_source_date(self):
        self.assertEqual(len(self.data["airlines"]), 10)
        self.assertEqual(self.data["source_last_updated"], "2025-09-11")
        self.assertIn("2025-09-11", self.view("delta")["source"])
        self.assertEqual(self.view("delta")["dotUrl"], "https://www.transportation.gov/airconsumer/airline-cancellation-delay-dashboard")

    def test_spirit_not_listed(self):
        v = self.view("spirit")
        self.assertFalse(v["listed"])
        self.assertIn("not listed on the DOT dashboard", v["notListed"])
        self.assertEqual(v["rows"], [])

    def test_no_means_no_commitment(self):
        v = self.view("frontier")
        by = {r["key"]: r for r in v["rows"]}
        self.assertEqual(by["hotel"]["text"], "No commitment")
        self.assertFalse(by["hotel"]["committed"])
        self.assertEqual(by["rebook_same"]["text"], "Committed")
        self.assertEqual(len(v["rows"]), 8)
        for r in v["rows"]:
            self.assertNotIn(r["text"], ("No", "Yes"))

    def test_labels_come_from_the_file(self):
        v = self.view("alaska")
        self.assertEqual(v["rows"][0]["label"], self.data["commitment_labels"]["rebook_same"])

    def test_wording_rules(self):
        self.assertTrue(self.view("delta")["intro"].startswith("Your airline has committed to"))
        self.assertIn("14 CFR 260.6", self.view("delta")["refund"])
        self.assertIn("whatever the cause", self.view("delta")["refund"])
        self.assertIn("14 CFR 260.6", self.view("spirit")["refund"])
        for a in self.data["airlines"]:
            text = json.dumps(self.view(a["id"])).lower()
            self.assertNotIn("must cover", text)
            self.assertNotIn("must provide", text)

    def test_no_must_cover_anywhere_in_site_files(self):
        for name in ("index.html", "app.js", "lib.js", "privacy.html"):
            self.assertNotIn("must cover", (ROOT / name).read_text().lower(), name)

    def test_committed_file_unchanged_from_lane_copy(self):
        src = Path.home() / "factory-scratch" / "shared" / "dot-airline-commitments.json"
        if not src.is_file():
            self.skipTest("lane copy not on this machine")
        self.assertEqual(src.read_bytes(), (ROOT / "data" / "dot-commitments.json").read_bytes())


@unittest.skipUnless(NODE, "node not installed")
class TestSummaryAndCountdown(unittest.TestCase):
    def test_summary(self):
        ap = [{"code": "SFO", "short": "San Francisco", "level": "delay", "events": [{"avg": "2 hours and 18 minutes"}]},
              {"code": "SAN", "short": "San Diego", "level": "delay", "events": [{"avg": "34 minutes"}]},
              {"code": "ATL", "short": "Atlanta", "level": "clear", "events": []}]
        self.assertEqual(js("ATD.nationalSummary(DATA.ap)", ap=ap),
                         "Delays at SAN and SFO.")
        ap2 = [{"code": "SFO", "short": "San Francisco", "level": "delay", "events": [{"kind": "ground_delay", "avg": "2 hours and 18 minutes"}]},
               {"code": "SNA", "short": "John Wayne", "level": "stop", "events": [{"kind": "closure"}]},
               {"code": "SAN", "short": "San Diego", "level": "delay", "events": [{"kind": "delay", "avg": "34 minutes"}]},
               {"code": "ATL", "short": "Atlanta", "level": "clear", "events": []}]
        want = ("John Wayne (SNA) is closed. Flights to San Francisco (SFO) are held about 2 h 18 min. "
                "San Diego (SAN) has delays of about 34 min.")
        self.assertEqual(js("ATD.troubleLine(DATA.ap)", ap=ap2), want)
        sys.path.insert(0, str(ROOT))
        from tools import prerender_home as ph
        self.assertEqual(ph.trouble_line(ap2), want)  # the build and the browser say the same
        self.assertEqual(js("ATD.troubleLine(DATA.ap)", ap=[]), "")
        self.assertEqual("Airport readings unavailable", js("ATD.nationalSummary([])"))

    def test_countdown(self):
        self.assertEqual(js("ATD.countdown(1000*60*60, 0)"), "ends in 1 h")
        self.assertEqual(js("ATD.countdown(1000*60*80, 0)"), "ends in 1 h 20 min")
        self.assertEqual(js("ATD.countdown(1000, 1000*60*5)"), "past listed end time")
        self.assertEqual(js("ATD.countdown(null, 0)"), "")

    def test_safe_url(self):
        self.assertEqual(js("ATD.safeUrl('javascript:alert(1)')"), "")
        self.assertEqual(js("ATD.safeUrl('https://a.test/x')"), "https://a.test/x")

    def test_three_tips(self):
        self.assertEqual(len(js("ATD.rebookTips()")), 3)


class TestSecurityWaits(unittest.TestCase):
    def test_schema(self):
        data = json.loads((ROOT / "data" / "security-waits.json").read_text())
        self.assertEqual(sorted(data), sorted(BUSIEST_30))
        for code, v in data.items():
            self.assertRegex(v["url"], r"^https://")
            self.assertIs(v["live_number"], False)
            self.assertIsInstance(v["note"], str)
            self.assertTrue(v["note"])
            self.assertIsInstance(v["verified"], bool)


class TestAirportCards(unittest.TestCase):
    def test_cards_from_events(self):
        FX = ROOT / "tests" / "fixtures"
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = build_web.build(Path(d), {}, (FX / "faa-1.xml").read_text(), '{"ac":[]}', {}, True)
            cards = json.loads((Path(d) / "airports.json").read_text())
        from desk.airports import BUSIEST_100
        self.assertEqual(sorted(cards["airports"]), sorted(BUSIEST_100))
        self.assertEqual(len(p["board"]), 30)
        for c in cards["airports"].values():
            self.assertIn(c["level"], ("clear", "delay", "stop"))
            self.assertTrue(c["city"])
            self.assertTrue(c["tz"])

    def test_near_airports_limit_and_order(self):
        evs = [{"source": "FAA", "airport": c, "kind": "ground_delay", "fields": {"avg": f"{i} minutes"}} for i, c in enumerate(["ATL", "DFW", "DEN", "ORD", "LAX", "JFK", "LAS"], 1)]
        evs.append({"source": "FAA", "airport": "SEA", "kind": "ground_stop", "fields": {}})
        evs.append({"source": "adsb.lol", "airport": "MCO", "kind": "squawk7700", "fields": {}})
        got = build_web.pick_near_airports(evs)
        self.assertEqual(len(got), 5)
        self.assertEqual(got[0], "SEA")
        self.assertEqual(got[1], "LAS")

    def test_near_count_uses_fetcher(self):
        from desk.airports import AIRPORTS
        evs = [{"source": "FAA", "airport": "SFO", "kind": "ground_delay", "fields": {"avg": "10 minutes"}, "reason": "wind"}]
        board = [{"code": c, "level": "amber" if c == "SFO" else "green"} for c in BUSIEST_30]
        urls = []
        def fetch(url):
            urls.append(url)
            return json.dumps({"ac": [{"hex": "a1", "lat": 37.6, "lon": -122.4}, {"hex": "a2", "lat": 37.7, "lon": -122.4}, {"hex": "a3"}]})
        out = build_web.build_airport_cards(evs, board, {"SFO": ["Wind Advisory"]}, "2026-01-01T00:00:00Z", near_fetch=fetch)
        self.assertEqual(out["airports"]["SFO"]["aircraft_near"], 2)
        self.assertEqual(out["airports"]["SFO"]["alerts"], ["Wind Advisory"])
        self.assertIsNone(out["airports"]["ATL"]["aircraft_near"])
        self.assertEqual(len(urls), 1)
        self.assertIn("/dist/20", urls[0])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(NODE, "node not installed")
class TestAn12Helpers(unittest.TestCase):
    def test_clear_tile_is_an_empty_bar_and_flat_clear_has_no_arrow(self):
        v = js("ATD.tileView(DATA.t)", t={"status": "green", "fill": 0.4, "trend": "flat", "text": "clear"})
        self.assertEqual((v["fillPct"], v["trendMark"], v["word"]), (0, "", "Clear"))

    def test_fill_percent_and_colour_status(self):
        v = js("ATD.tileView(DATA.t)", t={"status": "orange", "fill": 0.75, "trend": "up", "text": "avg 1 h 30 m"})
        self.assertEqual((v["fillPct"], v["status"], v["trendMark"], v["detail"]), (75, "orange", "↑", "avg 1 h 30 m"))
        self.assertEqual(js("ATD.tileView(DATA.t)", t={"status": "red", "fill": 1, "text": "ground stop"})["word"], "Ground stop")
        self.assertEqual(js("ATD.tileView(DATA.t)", t={"status": "yellow", "fill": 5})["fillPct"], 100)

    def test_latest_leaves_out_owed_and_repeats(self):
        items = [{"text": "a", "kind": "new", "t_utc": "2026-11-14T10:00:00Z"}, {"text": "a", "kind": "new", "t_utc": "2026-11-14T09:00:00Z"},
                 {"text": "o", "kind": "owed", "t_utc": "2026-11-14T11:00:00Z"}, {"text": "b", "kind": "wx", "t_utc": "2026-11-14T10:30:00Z"}]
        out = js("ATD.latestItems(DATA.i, 6)", i=items)
        self.assertEqual([x["text"] for x in out], ["b", "a"])

    def test_holiday_view_keeps_missing_days_empty(self):
        h = {"days": [{"date": "2026-11-22", "dow": "Sun", "day": 22, "count": 100, "ly_count": 200}, {"date": "2026-11-23", "dow": "Mon", "day": 23, "count": None, "ly_count": 100, "is_record": True}], "days_to": 12}
        v = js("ATD.holidayView(DATA.h)", h=h)
        self.assertEqual(v["rows"][0]["nowPct"], 50.0)
        self.assertIsNone(v["rows"][1]["nowPct"])
        self.assertTrue(v["rows"][1]["isRecord"])


@unittest.skipUnless(NODE, "node not installed")
class TestRound4Words(unittest.TestCase):
    """AN34 round 4: the dateline and the plain reason read the same in the build and the browser."""

    def test_dateline_parity(self):
        sys.path.insert(0, str(ROOT))
        from datetime import datetime
        from tools import prerender_text as pt
        for hour, want in ((1, "Early Monday, 1:05 AM"), (9, "Monday morning, 9:05 AM"), (13, "Monday afternoon, 1:05 PM"),
                           (19, "Monday evening, 7:05 PM"), (22, "Monday night, 10:05 PM")):
            local = datetime(2026, 11, 16, hour, 5)
            self.assertEqual(pt.dateline(local), want)
            clock = local.strftime("%I:%M %p").lstrip("0")
            self.assertEqual(js("ATD.dateline(DATA.p)", p={"weekday": "Monday", "hour": hour, "clock": clock}), want)

    def test_reason_words_parity(self):
        sys.path.insert(0, str(ROOT))
        from tools import prerender_home as ph
        for raw, want in (("low ceilings", "low clouds"), ("WX: thunderstorms", "thunderstorms"), ("something new", ""), ("", "")):
            self.assertEqual(ph.reason_words(raw), want)
            self.assertEqual(js("ATD.reasonWords(DATA.r)", r=raw), want)
        ap = [{"code": "SFO", "short": "San Francisco", "level": "delay", "reason": "low ceilings",
               "events": [{"kind": "ground_delay", "avg": "2 hours and 46 minutes"}]}]
        want = "Flights to San Francisco (SFO) are held about 2 h 46 min for low clouds."
        self.assertEqual(ph.trouble_line(ap), want)
        self.assertEqual(js("ATD.troubleLine(DATA.ap)", ap=ap), want)


class TestLongClosureListing(unittest.TestCase):
    """AN34 round 4: a closure listed to end days out does not read as a plain reopening time."""

    def test_far_reopen_is_explained(self):
        sys.path.insert(0, str(ROOT))
        from datetime import datetime, timezone
        from tools import prerender_home as ph
        now = datetime(2026, 11, 16, 6, 30, tzinfo=timezone.utc)
        far = {"kind": "closure", "fields": {"reopen": "Nov 21 at 14:15 UTC."}}
        listing = ph.closure_listing(far, now)
        self.assertIn("FAA listing runs to Nov 21", listing)
        self.assertIn("often cover nightly closures", listing)
        near = {"kind": "closure", "fields": {"reopen": "Nov 16 at 14:15 UTC."}}
        self.assertTrue(ph.closure_listing(near, now).startswith("Listed reopening Nov 16"))
