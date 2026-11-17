"""Zach, 17 Nov: "TEB here.. What is TEB?" Cards for airports outside the 100 on the board showed only the code.

Every airport code in the FAA feed must resolve to a real name (OurAirports table in data/airport-names.json); no network.
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk import airports, feeds  # noqa: E402
from desk.ticker import Ticker  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
NOT_AIRPORTS = {"SUA"}  # the FAA lists special-use airspace under ARPT; it is not an airport and keeps its code


class AirportNames(unittest.TestCase):
    def test_teb_has_a_name(self):
        self.assertEqual(airports.display("TEB"), "Teterboro Airport")
        self.assertEqual(airports.spoken("TEB"), "Teterboro Airport")
        self.assertEqual(airports.city_state("TEB"), "Teterboro, NJ")
        self.assertEqual(airports.label("TEB"), "TEB (Teterboro Airport)")

    def test_the_100_keep_their_short_labels(self):
        self.assertEqual(airports.label("JFK"), "JFK")
        self.assertEqual(airports.display("JFK"), "John F. Kennedy International")
        self.assertEqual(airports.spoken("ATL"), "Atlanta Hartsfield-Jackson")

    def test_icao_form_and_unknown_codes(self):
        self.assertEqual(airports.display("KTEB"), "Teterboro Airport")
        self.assertEqual(airports.display("QQQ"), "QQQ")
        self.assertEqual(airports.spoken("QQQ"), "Q Q Q airport")
        self.assertEqual(airports.label("QQQ"), "QQQ")

    def test_every_faa_code_in_the_fixtures_resolves(self):
        seen = set()
        for name in ("faa-1.xml", "faa-2.xml", "faa-teb-synthetic.xml"):
            for ev in feeds.parse_faa((FIX / name).read_text(encoding="utf-8")):
                seen.add(str(ev["airport"]).upper())
        self.assertTrue({"TEB", "HPN", "MMU"} <= seen)
        for code in sorted(seen - NOT_AIRPORTS):
            self.assertIsNotNone(airports.full_name(code), f"no name for FAA code {code}")
            self.assertNotEqual(airports.display(code), code, f"display() of {code} is still the bare code")

    def test_ticker_names_airports_outside_the_100(self):
        events = feeds.parse_faa((FIX / "faa-teb-synthetic.xml").read_text(encoding="utf-8"))
        now = datetime(2026, 11, 17, 19, 0, tzinfo=timezone.utc)
        items = Ticker().update(now.timestamp(), [], events, {}, {}, first_poll=False)
        texts = [it["text"] for it in items]
        self.assertTrue(any("TEB (Teterboro Airport)" in t for t in texts), texts)

    def test_data_file_is_sane(self):
        d = json.loads((ROOT / "data" / "airport-names.json").read_text(encoding="utf-8"))
        self.assertGreater(d["count"], 10000)
        self.assertIn("OurAirports", d["source"])


if __name__ == "__main__":
    unittest.main()
