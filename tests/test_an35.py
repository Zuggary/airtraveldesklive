"""AN35 tests: scheduled (daily) closures are calm, the flight box, the hero glance lines, one place for the data age,
and charts that do not render empty. Fixtures only; no network."""
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk import feeds  # noqa: E402
from tools import build_airport_pages as bap  # noqa: E402
from tools import prerender_home as ph  # noqa: E402
from tools import prerender_text as pt  # noqa: E402
from tests import test_prerender as tp  # noqa: E402

from tools.build_airport_pages import airport_js as _an43_airport_js  # noqa: E402
AIRPORT_JS = _an43_airport_js()


NODE = shutil.which("node")
NIGHT = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)    # 2:00 AM in Los Angeles, inside 0730-1415 UTC
DAY = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)      # noon in Los Angeles, outside the window
UPD_NIGHT = "2026-11-15T09:55:00Z"
SNA_EVENT = {"kind": "closure", "reason": "closed", "reopen": "Nov 20 at 14:15 UTC.", "start": "Nov 15 at 07:30 UTC.", "daily": "0730-1415"}
FAA_XML = """<AIRPORT_STATUS_INFORMATION><Airport_Closure_List>
<Airport><ARPT>SNA</ARPT><Reason>!SNA 11/051 SNA AD AP CLSD DLY 0730-1415 2511150730-2511201415</Reason><Start>Nov 15 at 07:30 UTC.</Start><Reopen>Nov 20 at 14:15 UTC.</Reopen></Airport>
<Airport><ARPT>XYZ</ARPT><Reason>!XYZ 11/052 XYZ AD AP CLSD</Reason><Start>Nov 15 at 07:30 UTC.</Start><Reopen>Nov 15 at 18:00 UTC.</Reopen></Airport>
</Airport_Closure_List></AIRPORT_STATUS_INFORMATION>"""


def sna_card(events=None, level="stop"):
    return tp._airport("SNA", "John Wayne Airport", "America/Los_Angeles", level, events if events is not None else [SNA_EVENT], "closed", tp._wx())


class TestScheduledClosureData(unittest.TestCase):
    def test_daily_window_is_read_from_the_raw_reason(self):
        self.assertEqual(feeds.daily_window("!SNA 11/051 SNA AD AP CLSD DLY 0730-1415 2511150730-2511201415"), "0730-1415")
        self.assertEqual(feeds.daily_window("AD AP CLSD"), "")
        self.assertEqual(feeds.daily_window("AD AP CLSD DLY 2599-1415"), "")

    def test_feed_keeps_start_reopen_and_daily_only_for_daily_closures(self):
        evs = {e["airport"]: e for e in feeds.parse_faa(FAA_XML)}
        self.assertEqual(evs["SNA"]["fields"], {"reopen": "Nov 20 at 14:15 UTC.", "start": "Nov 15 at 07:30 UTC.", "daily": "0730-1415"})
        self.assertNotIn("daily", evs["XYZ"]["fields"])


class TestScheduledClosureRules(unittest.TestCase):
    def test_schedule_in_and_out_of_the_closed_hours_in_airport_time(self):
        a = pt.closure_schedule(SNA_EVENT, "America/Los_Angeles", NIGHT)
        self.assertEqual(a, {"in_window": True, "reopen": "6:15 AM", "close": "11:30 PM"})
        self.assertFalse(pt.closure_schedule(SNA_EVENT, "America/Los_Angeles", DAY)["in_window"])

    def test_listing_that_has_ended_is_not_a_closure(self):
        late = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
        self.assertFalse(pt.closure_schedule(SNA_EVENT, "America/Los_Angeles", late)["in_window"])

    def test_other_closures_are_not_scheduled(self):
        self.assertIsNone(pt.closure_schedule({"kind": "closure", "reopen": "Nov 15 at 18:00 UTC."}, "America/Chicago", NIGHT))
        self.assertIsNone(pt.closure_schedule({"kind": "ground_stop", "daily": "0730-1415"}, "America/Chicago", NIGHT))

    def test_levels(self):
        self.assertEqual(pt.effective_level(sna_card(), NIGHT), "night")
        self.assertEqual(pt.effective_level(sna_card(), DAY), "clear")
        self.assertEqual(pt.status_word(sna_card(), NIGHT), "Closed overnight")
        real = sna_card([{"kind": "closure", "reopen": "Nov 15 at 18:00 UTC."}])
        self.assertEqual(pt.effective_level(real, NIGHT), "closed")   # an unscheduled closure stays an alarm
        both = sna_card([SNA_EVENT, {"kind": "closure"}])
        self.assertEqual(pt.effective_level(both, NIGHT), "closed")
        stop = sna_card([SNA_EVENT, {"kind": "ground_stop"}])
        self.assertEqual(pt.effective_level(stop, DAY), "stop")


class TestAirportPageNight(unittest.TestCase):
    def build(self, card, now, updated):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        d = tp.make_data(Path(tmp), {"SNA": card})
        tp._write(d / "airports.json", {"version": 1, "updated_utc": updated, "airports": {"SNA": card}})
        tp._write(d / "airport-guide.json", {"version": 1, "checked_utc": "2026-11-14", "airports": {"SNA": {"operator": "County", "links": tp._links("SNA", True)}}})
        out = Path(tmp) / "out"
        bap.build_pages(data_dir=d, out_dir=out, sitemap_path=None, build_date="2026-11-15", now=now)
        return (out / "SNA.html").read_text(encoding="utf-8")

    def test_daily_closure_is_calm_and_says_when_it_reopens(self):
        page = self.build(sna_card(), NIGHT, UPD_NIGHT)
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S).group(1)
        self.assertIn("closed overnight", h1)
        self.assertIn("reopens about 6:15 AM local time", h1)
        self.assertIn("ap-hero--night", page)
        self.assertNotIn("ap-hero--closed", page)
        self.assertIn('badge badge--night status-chip', page)
        self.assertNotIn("badge--stop status-chip", page)
        self.assertNotIn("is <em>closed</em> to flights", page)

    def test_open_hours_read_as_open_with_the_listing_noted(self):
        page = self.build(sna_card(), DAY, "2026-11-15T19:55:00Z")
        self.assertIn("No FAA delays at", page)
        self.assertIn("closes again about 11:30 PM local time", page)

    def test_stale_page_judges_the_schedule_at_the_data_time(self):
        later = datetime(2026, 11, 15, 22, 0, tzinfo=timezone.utc)   # 12 hours after the reading, outside the closed hours
        page = self.build(sna_card(), later, UPD_NIGHT)
        self.assertIn("Closed overnight at ", tp.visible_text(page))
        self.assertIn("Last known status", page)

    def test_a_real_closure_stays_an_alarm(self):
        card = sna_card([{"kind": "closure", "reopen": "Nov 15 at 18:00 UTC."}])
        page = self.build(card, NIGHT, UPD_NIGHT)
        self.assertIn("is <em>closed</em> to flights", page)
        self.assertIn("ap-hero--closed", page)
        self.assertIn("badge--stop status-chip", page)

    def test_page_script_carries_the_same_rule(self):
        page = self.build(sna_card(), NIGHT, UPD_NIGHT) + AIRPORT_JS  # AN43: the status script lives in ../airport.js
        for needle in ("function closureSchedule", "function effLevel", '"night"', "closed overnight", "badge--night"):
            self.assertIn(needle, page)


class TestHeroGlanceAndFreshness(unittest.TestCase):
    def build_atl(self, now, updated, wx=None, security=None):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        card = tp._airport("ATL", "Atlanta International", "America/New_York", wx=wx if wx is not None else tp._wx())
        d = tp.make_data(Path(tmp), {"ATL": card})
        tp._write(d / "airports.json", {"version": 1, "updated_utc": updated, "airports": {"ATL": card}})
        tp._write(d / "airport-guide.json", {"version": 1, "checked_utc": "2026-11-14", "airports": {"ATL": {"operator": "City", "links": tp._links("ATL", True)}}})
        if security is not None:
            tp._write(d / "security-waits.json", {"ATL": security})
        out = Path(tmp) / "out"
        bap.build_pages(data_dir=d, out_dir=out, sitemap_path=None, build_date="2026-11-14", now=now)
        return (out / "ATL.html").read_text(encoding="utf-8")

    def test_next_three_hours_line_is_in_the_hero_with_source_and_age(self):
        page = self.build_atl(tp.NOW, tp.UPDATED, wx={**tp._wx(), "next3h_cat": "IFR", "next3h_storms": True, "taf_issue_utc": "2026-11-14T08:30:00Z"})
        hero = page.split('id="ap-hero"')[1].split("</section>")[0]
        m = re.search(r'<p id="ap-next3"[^>]*>(.*?)</p>', hero, re.S)
        self.assertIsNotNone(m)
        text = re.sub(r"<[^>]+>", "", m.group(1))
        self.assertIn("Next 3 hours: clear through 6 am (IFR: low ceiling or poor visibility). Storms possible", text)
        self.assertIn("aviationweather.gov TAF, issued", text)
        self.assertIn("1 hour old", text)
        self.assertNotIn("fact--next", page.split('id="right-now"')[1].split("</section>")[0])

    def test_no_forecast_means_no_line(self):
        page = self.build_atl(tp.NOW, tp.UPDATED, wx={})
        self.assertIn('id="ap-next3" class="gl gl--next" hidden></p>', page)

    def test_tsa_wait_shows_only_with_a_number_a_source_and_an_age(self):
        none = self.build_atl(tp.NOW, tp.UPDATED, security={"url": "https://www.atl.com/", "live_number": False})
        self.assertNotIn('id="ap-tsa"', none)
        ok = self.build_atl(tp.NOW, tp.UPDATED, security={"url": "https://www.atl.com/security", "wait_minutes": 22, "updated_utc": "2026-11-14T09:49:00Z", "source": "ATL security page"})
        text = re.sub(r"<[^>]+>", "", re.search(r'<p id="ap-tsa".*?</p>', ok, re.S).group(0))
        self.assertIn("TSA checkpoint wait: about 22 min", text)
        self.assertIn("ATL security page, 9 minutes old", text)
        old = self.build_atl(tp.NOW, tp.UPDATED, security={"url": "https://www.atl.com/security", "wait_minutes": 22, "updated_utc": "2026-11-14T07:00:00Z", "source": "ATL security page"})
        self.assertNotIn('id="ap-tsa"', old)
        nosrc = self.build_atl(tp.NOW, tp.UPDATED, security={"wait_minutes": 22, "updated_utc": "2026-11-14T09:49:00Z"})
        self.assertNotIn('id="ap-tsa"', nosrc)

    def test_the_data_age_is_stated_once(self):
        fresh = self.build_atl(tp.NOW, tp.UPDATED)
        text = tp.visible_text(fresh)
        self.assertIn("FAA data 8 min old, checked 4:50 AM EST. Source: FAA NAS status.", text)
        self.assertEqual(len(re.findall(r"checked 4:50 AM EST", text)), 1)
        later = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        stale = tp.visible_text(self.build_atl(later, tp.UPDATED))
        self.assertIn("This data is 4 hours old, not live.", stale)
        self.assertIn("Source: FAA NAS status, last checked 4:50 AM EST.", stale)
        self.assertNotIn("4 hours ago", stale.split("Source: FAA NAS status")[1][:70])
        self.assertIn("Last known status", stale)

    def test_age_line_wording(self):
        self.assertEqual(pt.faa_age_plain("2026-11-14T09:50:00Z", "America/New_York", tp.NOW, False), "FAA data 8 min old, checked 4:50 AM EST.")
        self.assertEqual(pt.faa_age_plain("2026-11-14T09:50:00Z", "America/New_York", tp.NOW, True), "FAA NAS status, last checked 4:50 AM EST.")
        self.assertEqual(pt.faa_age_plain("2026-11-14T09:58:00Z", "America/New_York", tp.NOW, False), "FAA data under 1 min old, checked 4:58 AM EST.")

    def test_official_links_sit_under_the_status_block(self):
        page = self.build_atl(tp.NOW, tp.UPDATED)
        self.assertLess(page.index('id="official-heading"'), page.index('id="right-now-heading"'))
        self.assertLess(page.index('id="ap-hero"'), page.index('id="official-heading"'))


class TestFlightBox(unittest.TestCase):
    def test_airline_table_covers_the_ten_airlines(self):
        ids = {a["id"] for a in json.loads((ROOT / "data" / "dot-commitments.json").read_text(encoding="utf-8"))["airlines"]}
        self.assertEqual(set(bap.FLIGHT_STATUS), ids)
        for _name, codes, url in bap.FLIGHT_STATUS.values():
            self.assertTrue(url.startswith("https://"))
            self.assertEqual(len(codes), 2)

    def test_box_is_honest_and_carries_no_tracking(self):
        html = "\n".join(bap._flight_check("ATL"))
        self.assertIn("Opens the airline\\'s own status page or home page. We do not track individual flights.".replace("\\'", "'"), html)
        self.assertEqual(html.count("<li><a"), 10)
        self.assertEqual(html.count("(airline's own site)"), 4)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("XMLHttpRequest", html)
        self.assertNotIn("location.", html)
        self.assertNotIn("?q=", html)
        self.assertIn("We do not know the airline code", html)

    @unittest.skipUnless(NODE, "node not installed")
    def test_script_picks_the_airline_by_code(self):
        html = "\n".join(bap._flight_check("ATL"))
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        code = r"""
const opened = []; const els = {};
const make = (id) => els[id] = { id, value: "", hidden: false, textContent: "", className: "", handlers: {}, addEventListener(t, f) { this.handlers[t] = f; } };
make("flight-form"); make("flight-no"); make("flight-msg"); make("flight-airlines");
global.document = { getElementById: (id) => els[id] };
global.window = { open: (u) => opened.push(u) };
%s
const run = (v) => { els["flight-no"].value = v; els["flight-form"].handlers.submit({ preventDefault() {} }); };
const out = {};
run("DL 123"); out.dl = opened.slice();
run("dl123"); out.dl2 = opened.length;
run("WN-4567"); out.wn = opened[opened.length - 1];
run("ZZ 9"); out.zz = [els["flight-msg"].textContent, els["flight-airlines"].hidden, opened.length];
run("DAL 55"); out.dal = opened[opened.length - 1];
run("hello"); out.bad = els["flight-msg"].textContent;
process.stdout.write(JSON.stringify(out));
""" % script
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["dl"], ["https://www.delta.com/us/en/flight-status"])
        self.assertEqual(out["dl2"], 2)
        self.assertEqual(out["wn"], "https://www.southwest.com/air/flight-status/")
        self.assertIn("We do not know the airline code ZZ", out["zz"][0])
        self.assertFalse(out["zz"][1])
        self.assertEqual(out["zz"][2], 3)  # nothing opened for the unknown code
        self.assertEqual(out["dal"], "https://www.delta.com/us/en/flight-status")
        self.assertIn("like DL 123", out["bad"])


@unittest.skipUnless(NODE, "node not installed")
class TestHomeScheduledClosure(unittest.TestCase):
    def js(self, expr, **data):
        code = "const ATD=require(%s);const DATA=%s;process.stdout.write(JSON.stringify(%s));" % (json.dumps(str(ROOT / "lib.js")), json.dumps(data), expr)
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_schedule_matches_python(self):
        for now in (NIGHT, DAY):
            py = pt.closure_schedule(SNA_EVENT, "America/Los_Angeles", now)
            self.assertEqual(self.js("ATD.closureSchedule(DATA.e, DATA.tz, DATA.n)", e=SNA_EVENT, tz="America/Los_Angeles", n=int(now.timestamp() * 1000)), py)

    def test_headline_lines_match_python(self):
        out = [{"airport": "SNA", "kind": "closure", "tz": "America/Los_Angeles", "fields": {"daily": "0730-1415", "reopen": "Nov 20 at 14:15 UTC."}}]
        for now, stale in ((NIGHT, False), (NIGHT, True), (DAY, False)):
            ms = int(now.timestamp() * 1000)
            self.assertEqual(self.js("ATD.nationalSummary([], DATA.a, DATA.o, DATA.n)", a="as of 1:50 AM" if stale else "", o=out, n=ms),
                             ph.national_summary([], "as of 1:50 AM" if stale else "", out, now))
        self.assertEqual(ph.national_summary([], "", out, NIGHT), "SNA is closed overnight, reopens about 6:15 AM local time. Airport readings unavailable")
        self.assertEqual(ph.national_summary([], "", out, DAY), "Airport readings unavailable")

    def test_scheduled_airport_is_not_trouble_and_gets_one_calm_line(self):
        card = sna_card()
        for now in (NIGHT, DAY):
            ms = int(now.timestamp() * 1000)
            self.assertEqual(self.js("ATD.troubleLine([DATA.a], false, DATA.n)", a=card, n=ms), ph.trouble_line([card], False, now))
            self.assertEqual(self.js("ATD.nationalSummary([DATA.a], '', [], DATA.n)", a=card, n=ms), ph.national_summary([card], "", [], now))
        self.assertEqual(ph.trouble_line([card], False, NIGHT), "John (SNA) is closed overnight, reopens about 6:15 AM local time.")
        self.assertEqual(ph.trouble_line([card], False, DAY), "")
        self.assertTrue(ph.national_summary([card], "", [], NIGHT).startswith("No delays or ground stops"))

    def test_program_row_is_calm(self):
        state = {"updated_utc": UPD_NIGHT, "events": [{"id": "closure:SNA", "kind": "closure", "airport": "SNA", "source": "FAA", "sources": ["FAA"], "tz": "America/Los_Angeles",
                                                           "fields": {"daily": "0730-1415", "reopen": "Nov 20 at 14:15 UTC."}}]}
        row = ph.render_events(state, {"SNA": sna_card()}, UPD_NIGHT, NIGHT)
        self.assertIn("event-card--night", row)
        self.assertNotIn("event-card--stop", row)
        self.assertIn("Closed overnight", row)
        self.assertIn("reopens about 6:15 AM local time", row)
        self.assertNotIn("Checked", row)
        self.assertEqual(ph.render_events(state, {"SNA": sna_card()}, "2026-11-15T19:55:00Z", DAY).count("event-card"), 0)

    def test_home_one_age_line_and_board_note(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("We watch all 100 busiest airports", index)
        self.assertIn("lists the 30 busiest plus any other airport with a listed FAA program", index)
        self.assertEqual(index.count("We watch all 100 busiest airports"), 1)
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("We check every 5 minutes", app)
        self.assertNotIn("We check every 5 minutes", (ROOT / "tools" / "prerender_home.py").read_text(encoding="utf-8"))
        self.assertEqual(self.js("ATD.faaAgePlain(4, '11:17 PM PST', false)"), "FAA data 4 min old, checked 11:17 PM PST.")
        self.assertEqual(self.js("ATD.faaAgePlain(0, '11:17 PM PST', false)"), pt.faa_age_plain("2026-11-14T09:58:00Z", "America/New_York", tp.NOW, False).replace("4:58 AM EST", "11:17 PM PST"))
        self.assertEqual(self.js("ATD.faaAgePlain(700, '11:17 PM PST', true)"), "FAA NAS status, last checked 11:17 PM PST.")


class TestChartsDoNotRenderEmpty(unittest.TestCase):
    def test_thanksgiving_block_is_left_out_when_no_day_is_counted(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        body = app.split("function holidayCard(hv)")[1].split("function signed")[0]
        self.assertIn("if (!done) {", body)
        self.assertLess(body.index("if (!done) {"), body.index('el("div", "hol-grid")'))
        self.assertIn("return c;", body.split("if (!done) {")[1].split('el("div", "hol-grid")')[0])

    def test_seven_day_chart_needs_three_counted_days_and_visible_bars(self):
        app = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("days.length >= 3", app)
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertNotIn(".bar7 i { display: block; border-radius: 6px 6px 2px 2px; background: var(--surface-3);", css)


if __name__ == "__main__":
    unittest.main()
