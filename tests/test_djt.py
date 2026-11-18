"""West Palm Beach feed aliases and home rendering, using synthetic observations."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desk import airports, feeds, holding, state, tracks, wx
from tools import archive_snapshot, build_status, build_web, prerender_home


class TestDJT(unittest.TestCase):
    def test_faa_aliases_from_both_builders(self):
        for code in ("PBI", "DJT", "KPBI", "KDJT", " pbi "):
            with self.subTest(code=code):
                xml = f"""<AIRPORT_STATUS_INFORMATION><Ground_Stop_List>
                    <Program><ARPT>{code}</ARPT><Reason>Weather</Reason></Program>
                    </Ground_Stop_List></AIRPORT_STATUS_INFORMATION>"""
                event, = feeds.parse_faa(xml)
                self.assertEqual(event["id"], "ground_stop:DJT")
                self.assertEqual(event["airport"], "DJT")
                legacy, = build_status.parse_faa(xml)
                self.assertEqual(legacy["code"], "DJT")
                self.assertEqual(legacy["tz"], "America/New_York")
                self.assertEqual(airports.full_name(code), legacy["name"])
                self.assertEqual(wx.icao(code), "KPBI")

    def test_ground_stop_reaches_state_cards_and_home(self):
        xml = """<AIRPORT_STATUS_INFORMATION><Ground_Stop_List>
            <Program><ARPT>KDJT</ARPT><Reason>Weather</Reason></Program>
            </Ground_Stop_List></AIRPORT_STATUS_INFORMATION>"""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            build_web.build(data_dir, {}, faa_text=xml, skip_slow=True, nws_map={"KPBI": ["Test advisory"]})
            live_state = json.loads((data_dir / "state.json").read_text())
            event, = live_state["events"]
            self.assertEqual(event["airport"], "DJT")
            self.assertEqual(event["status"], "CONFIRMED")
            self.assertEqual((event["lat"], event["lon"]), (26.6832, -80.0956))
            self.assertEqual(tracks.select_airports([dict(event, airport="PBI")]), ["DJT"])
            self.assertEqual(holding.hub_positions(["KPBI"])["DJT"], (26.6832, -80.0956))
            self.assertEqual(state.diff([dict(event, id="ground_stop:PBI", airport="PBI")], [event]), [])
            cards = json.loads((data_dir / "airports.json").read_text())["airports"]
            self.assertEqual(cards["DJT"]["level"], "stop")
            self.assertNotIn("PBI", cards)
            template = (Path(__file__).resolve().parents[1] / "index.html").read_text()
            html = prerender_home.prerender(template, data_dir, datetime.now(timezone.utc))
            events = html.split('id="events"', 1)[1].split("</section>", 1)[0]
            self.assertIn('href="/airports/DJT"', events)
            self.assertIn("Ground stop", events)

    def test_historical_snapshot_preserves_both_identifiers_under_djt(self):
        archive_rows = [
            {"airport": "DJT", "hour_utc": "2026-11-18T12:00Z", "delay": True},
            {"airport": "PBI", "hour_utc": "2026-11-18T12:00Z", "ground_stop": True},
            {"airport": "PBI", "hour_utc": "2026-11-18T13:00Z", "ground_stop": True},
        ]
        now = datetime(2026, 11, 18, 13, tzinfo=timezone.utc)
        with patch.object(archive_snapshot.al, "iter_rows", return_value=archive_rows):
            snapshot = archive_snapshot.build(hours=2, now=now)
        self.assertEqual(snapshot["airports"], {"DJT": "ds"})
        self.assertEqual(snapshot["rows"], 2)

    def test_weather_station_aliases(self):
        now = 1_800_000_000
        for station in ("PBI", "DJT", "KPBI", "KDJT"):
            with self.subTest(station=station):
                payload = wx.build([{"icaoId": station, "obsTime": now - 60, "fltCat": "VFR"}], [], now)
                self.assertEqual(list(payload["hubs"]), ["DJT"])
