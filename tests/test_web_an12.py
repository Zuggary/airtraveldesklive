"""AN12 on the website: weather, storms, trails, holding, ticker, board bars, holiday card. No network."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desk import board_history, holding, holiday, screen, storms, ticker, tracks  # noqa: E402
from tools import build_web  # noqa: E402

FX = ROOT / "tests" / "fixtures"
build_web.EXTRA_PAUSE = 0
REC = json.loads((FX / "wx-recorded.json").read_text())["recorded_ts"]
BAD_TIME = re.compile(r"\bUTC\b|\bGMT\b|\b\d{3,4}\s?Z\b|\bZulu\b", re.IGNORECASE)


def fake_fetch(near: str = "adsb-near-1.json"):
    calls: list[str] = []

    def get(url: str) -> str:
        calls.append(url)
        if "metar" in url:
            return (FX / "wx-metar.json").read_text()
        if "format=json" in url and "taf" in url:
            return (FX / "wx-taf.json").read_text()
        if "airsigmet" in url:
            return (FX / "storms-airsigmet.json").read_text()
        if "day1otlk" in url:
            return (FX / "storms-spc.json").read_text()
        if "CurrentStorms" in url:
            return (FX / "nhc-empty.json").read_text()
        if "adsb.lol" in url:
            return (FX / near).read_text()
        raise AssertionError(url)
    get.calls = calls
    return get


def run_build(out: Path, prev: dict, faa: str = "faa-1.xml", prev_national=None, prev_history=None, near="adsb-near-1.json", ts: float = REC):
    get = fake_fetch(near)
    p = build_web.build(out, prev, (FX / faa).read_text(), '{"ac":[]}', {}, True, extras=True, extra_fetch=get,
                        prev_national=prev_national, prev_history=prev_history, now_ts=ts)
    return p, get


def ev(kind, code, **fields):
    return {"id": f"{kind}:{code}", "source": "FAA", "kind": kind, "airport": code, "fields": fields, "reason": "thunderstorms", "tz": "America/New_York"}


class TestBoardBars(unittest.TestCase):
    def test_clear_is_an_empty_green_bar(self):
        t = {x["code"]: x for x in screen.board_from_events([])}["ATL"]
        self.assertEqual((t["status"], t["fill"], t["text"]), ("green", 0.0, "clear"))

    def test_fill_is_average_over_120_and_colour_is_faa_status(self):
        tiles = {x["code"]: x for x in screen.board_from_events([
            ev("ground_delay", "ATL", avg="1 hour and 30 minutes"), ev("delay", "ORD", max="45 minutes"),
            ev("ground_stop", "JFK"), ev("closure", "LAX")])}
        self.assertAlmostEqual(tiles["ATL"]["fill"], 0.75)
        self.assertEqual(tiles["ATL"]["status"], "orange")
        self.assertAlmostEqual(tiles["ORD"]["fill"], 45 / 120)
        self.assertEqual(tiles["ORD"]["status"], "yellow")
        self.assertEqual((tiles["JFK"]["status"], tiles["JFK"]["fill"]), ("red", 1.0))
        self.assertEqual((tiles["LAX"]["status"], tiles["LAX"]["fill"]), ("red", 1.0))
        self.assertEqual(screen.board_from_events([ev("ground_delay", "ATL", avg="3 hours")])[0]["fill"], 1.0)

    def test_job_writes_board_with_fill_for_every_tile(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = run_build(Path(d), {})
            self.assertEqual(len(p["board"]), 30)
            for t in p["board"]:
                if t["status"] == "green":
                    self.assertEqual(t["fill"], 0.0)
                elif t["status"] in ("yellow", "orange") and t["avg_min"] is not None:
                    self.assertAlmostEqual(t["fill"], min(1.0, t["avg_min"] / 120), places=3)
            self.assertEqual(set(p["zones"]), {"PT", "MT", "CT", "ET"})

    def test_trend_reads_the_hour_before(self):
        now = datetime(2026, 11, 14, 12, 30, tzinfo=timezone.utc)
        prev = {"points": [{"hour_utc": "2026-11-14T11:00Z", "board": {"ATL": {"level": "orange", "avg_min": 100}, "ORD": {"level": "green", "avg_min": None}}}]}
        self.assertEqual(board_history.hour_ago(prev, now)["ATL"]["avg_min"], 100)
        tiles = {x["code"]: x for x in screen.board_from_events([ev("ground_delay", "ATL", avg="30 minutes"), ev("ground_delay", "ORD", avg="60 minutes")], board_history.hour_ago(prev, now))}
        self.assertEqual(tiles["ATL"]["trend"], "down")
        self.assertEqual(tiles["ORD"]["trend"], "up")
        self.assertIsNone(board_history.hour_ago(prev, datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)))

    def test_history_keeps_24_hours_and_adds_each_hour_once(self):
        board = screen.board_from_events([])
        hist: dict = {}
        for h in range(30):
            now = datetime(2026, 11, 13, 0, 5, tzinfo=timezone.utc).replace(day=13 + h // 24, hour=h % 24)
            hist = board_history.add_hour(hist, board, now)
            hist = board_history.add_hour(hist, board, now.replace(minute=40))
        self.assertEqual(len(hist["points"]), 24)


class TestTickerAndText(unittest.TestCase):
    def test_no_squawks_anywhere(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = run_build(Path(d), {})
            blob = json.dumps(p).lower()
            for word in ("squawk", "7700", "7600", "7500", "emergency"):
                self.assertNotIn(word, blob)

    def test_ticker_never_repeats_within_ten_minutes(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            p1, _ = run_build(out, {}, "faa-1.xml", ts=REC)
            seen = {}
            prev = json.loads((out / "state.json").read_text())
            for step, faa in enumerate(["faa-2.xml", "faa-2.xml", "faa-2.xml", "faa-1.xml", "faa-1.xml"], 1):
                ts = REC + 300 * step
                p, _ = run_build(out, prev, faa, ts=ts)
                prev = json.loads((out / "state.json").read_text())
                for it in p["ticker"]:
                    key = (it["text"])
                    t = datetime.strptime(it["t_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                    if key in seen and abs(t - seen[key]) > 0:
                        self.fail(f"repeat of {key!r}")
                    seen[key] = t
            texts = [i["text"] for i in prev["ticker"]]
            self.assertEqual(len(texts), len(set(texts)))

    def test_every_ticker_item_names_an_airport_a_time_or_an_action(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = run_build(Path(d), {})
            for it in p["ticker"]:
                self.assertTrue(re.search(r"\b[A-Z]{3}\b|\d:\d\d|\b(am|pm)\b|Check|Delayed", it["text"]), it["text"])

    def test_ticker_restore_keeps_the_cooldown_across_runs(self):
        t = ticker.Ticker(keep_sec=3600)
        t.restore([{"key": "hold:JFK", "kind": "hold", "text": "3 aircraft look to be holding near JFK", "t_utc": "2026-11-14T12:00:00Z", "tag": "HOLDING"}])
        now = datetime(2026, 11, 14, 12, 5, tzinfo=timezone.utc).timestamp()
        self.assertFalse(t.add("hold:JFK", "hold", "3 aircraft look to be holding near JFK", now))
        later = datetime(2026, 11, 14, 12, 11, tzinfo=timezone.utc).timestamp()
        self.assertTrue(t.add("hold:JFK", "hold", "4 aircraft look to be holding near JFK", later))

    def test_no_z_or_utc_in_spoken_or_caption_text(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = run_build(Path(d), {})
            texts = [l["text"] for l in p["last_lines"]] + [i["text"] for i in p["ticker"]]
            wxj = json.loads((Path(d) / "wx.json").read_text())
            for h in wxj["hubs"].values():
                texts += [h.get("now_text") or "", h.get("next3h_text") or ""]
            cards = json.loads((Path(d) / "airports.json").read_text())["airports"]
            for c in cards.values():
                texts += [(c.get("wx") or {}).get("now_text") or "", (c.get("wx") or {}).get("next3h_text") or ""]
            self.assertTrue(len(texts) > 5)
            for t in texts:
                self.assertIsNone(BAD_TIME.search(t), t)


class TestWeatherLayers(unittest.TestCase):
    def test_wx_storms_nhc_written_with_source_and_age(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            run_build(out, {})
            w = json.loads((out / "wx.json").read_text())
            self.assertIn("aviationweather.gov", w["source"])
            self.assertTrue(w["hubs"] and w["fetched_utc"])
            self.assertIn("spc", json.loads((out / "storms.json").read_text()))
            self.assertEqual(json.loads((out / "nhc.json").read_text())["storms"], [])

    def test_layers_respect_their_cache_cadence(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            _, g1 = run_build(out, {}, ts=REC)
            _, g2 = run_build(out, {}, ts=REC + 300)
            first = [u for u in g1.calls if "aviationweather" in u or "noaa" in u]
            second = [u for u in g2.calls if "aviationweather" in u or "noaa" in u]
            self.assertTrue(first)
            self.assertEqual(second, [], "weather layers must not refetch inside their cache time")

    def test_storm_note_for_a_hub_inside_an_area(self):
        payload = {"source": "NOAA SPC", "fetched_utc": "x", "spc": {"areas": [{"label": "ENH", "rings": [[[-85, 33], [-83, 33], [-83, 34.5], [-85, 34.5], [-85, 33]]]},
                                                                               {"label": "MRGL", "rings": [[[-120, 30], [-100, 30], [-100, 40], [-120, 40], [-120, 30]]]}]},
                   "sigmets": []}
        notes = storms.hub_notes(payload, {"ATL": (33.64, -84.43), "DEN": (39.86, -104.67)})
        self.assertEqual(notes["ATL"]["spc"], "ENH")
        self.assertNotIn("DEN", notes, "a marginal risk alone does not earn an airport note")

    def test_airport_cards_carry_weather(self):
        with tempfile.TemporaryDirectory() as d:
            run_build(Path(d), {})
            cards = json.loads((Path(d) / "airports.json").read_text())["airports"]
            with_wx = [c for c in cards.values() if c.get("wx")]
            self.assertTrue(with_wx)
            self.assertIn("aviationweather.gov", with_wx[0]["wx"]["source"])


class TestTrailsAndHolding(unittest.TestCase):
    def test_trails_continue_from_the_previous_published_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            run_build(out, {}, near="adsb-near-1.json", ts=REC)
            prev_nat = json.loads((out / "national.json").read_text())
            self.assertTrue(all(len(a["trail"]) == len(a["meta"]) for a in prev_nat["aircraft"]))
            p1 = {a["hex"]: len(a["trail"]) for a in prev_nat["aircraft"]}
            run_build(out, {}, near="adsb-near-2.json", prev_national=prev_nat, ts=REC + 300)
            nat = json.loads((out / "national.json").read_text())
            grown = [a for a in nat["aircraft"] if len(a["trail"]) > p1.get(a["hex"], 99)]
            self.assertTrue(grown, "at least one aircraft must have a longer trail after the second run")
            self.assertTrue(all(len(a["trail"]) <= tracks.WEB_TRAIL for a in nat["aircraft"]))
            self.assertEqual(nat["interval_s"], 300.0)
            self.assertLessEqual(len(nat["aircraft"]), tracks.WEB_CAP)

    def test_old_aircraft_are_not_carried_over(self):
        nt = tracks.NationalTracker()
        kept = nt.load({"n": 5, "aircraft": [
            {"hex": "aaa", "t": REC - 100, "trail": [[1, 2]], "meta": [[REC - 100, 5000]], "ln": 5},
            {"hex": "bbb", "t": REC - 5000, "trail": [[1, 2]], "meta": [[REC - 5000, 5000]], "ln": 1}]}, now_ts=REC)
        self.assertEqual(kept, 1)

    def circle(self, lat, lon, now, hexid, alt=8000, steps=6):
        import math
        pts = []
        for i in range(steps):
            ang = math.radians(90 * i)
            r = 3.0 / 60.0
            pts.append((lon + r * math.sin(ang) / math.cos(math.radians(lat)), lat + r * math.cos(ang), now - (steps - 1 - i) * 300.0, alt))
        return {"hex": hexid, "pts": pts}

    def test_holding_shows_only_three_or_more_and_only_circling_tracks(self):
        hubs = holding.hub_positions()
        lat, lon = hubs["JFK"]
        three = [self.circle(lat, lon, REC, f"c{i}") for i in range(3)]
        got = holding.holding_map(holding.count_by_hub(three, hubs, REC, holding.WEB), REC)
        self.assertEqual(got["JFK"]["count"], 3)
        two = holding.holding_map(holding.count_by_hub(three[:2], hubs, REC, holding.WEB), REC)
        self.assertEqual(two, {})
        straight = [{"hex": f"s{i}", "pts": [(lon + 0.05 * k, lat + 0.01 * i, REC - (5 - k) * 300.0, 9000) for k in range(6)]} for i in range(4)]
        self.assertEqual(holding.count_by_hub(straight, hubs, REC, holding.WEB), {})

    def test_low_aircraft_do_not_count(self):
        hubs = holding.hub_positions()
        lat, lon = hubs["JFK"]
        low = [self.circle(lat, lon, REC, f"l{i}", alt=1200) for i in range(4)]
        self.assertEqual(holding.count_by_hub(low, hubs, REC, holding.WEB), {})


class TestHoliday(unittest.TestCase):
    TSA = {
        "fetched_utc": "2026-11-14T12:00:00Z", "latest_date": "2026-11-12", "latest_count": 2484345, "ly_date": "2025-11-13", "ly_count": 2434496,
        "last7": [{"date": "2026-11-12", "count": 2484345}], "record": {"date": "2025-11-30", "count": 3134613},
        "thanksgiving": {"date_this_year": "2026-11-26", "last_year_date": "2025-11-27", "busiest_date": "2025-11-30",
                         "last_year_week": [{"date": "2025-11-23", "count": 2617142}, {"date": "2025-11-27", "count": 1559165}, {"date": "2025-11-30", "count": 3134613}],
                         "this_year_week": [{"date": "2026-11-22", "count": 2700000}]},
    }

    def test_card_has_dated_values_the_record_and_days_left(self):
        from datetime import date
        h = holiday.assemble(self.TSA, date(2026, 11, 14))
        self.assertEqual(h["days_to"], 12)
        self.assertEqual(h["thanksgiving"], "2026-11-26")
        days = {d["date"]: d for d in h["days"]}
        self.assertEqual(days["2026-11-22"]["count"], 2700000)
        self.assertEqual(days["2026-11-22"]["ly_count"], 2617142)
        self.assertIsNone(days["2026-11-29"]["count"])
        self.assertTrue(days["2026-11-29"]["is_record"] and days["2026-11-29"]["is_busiest"])
        self.assertTrue(days["2026-11-26"]["is_thanksgiving"])
        self.assertEqual(h["record"]["count"], 3134613)
        self.assertEqual(h["source"], "TSA")

    def test_job_writes_the_card_when_tsa_json_exists(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "tsa.json").write_text(json.dumps(self.TSA))
            p, _ = run_build(out, {})
            self.assertEqual(p["holiday"]["source"], "TSA")


if __name__ == "__main__":
    unittest.main()
