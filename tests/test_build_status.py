"""Unit tests for tools/build_status.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import build_status  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FAA_2_FIXTURE = FIXTURES_DIR / "faa-2.xml"
NWS_JFK_FIXTURE = FIXTURES_DIR / "nws-JFK-synthetic.json"


class TestBuildStatus(unittest.TestCase):
    def test_busiest_30_order_and_timezones(self) -> None:
        expected_codes = [
            "ATL", "DFW", "DEN", "ORD", "LAX", "JFK", "LAS", "MCO", "MIA", "CLT",
            "SEA", "PHX", "EWR", "SFO", "IAH", "BOS", "FLL", "MSP", "LGA", "DTW",
            "PHL", "SLC", "BWI", "IAD", "SAN", "DCA", "TPA", "BNA", "AUS", "MDW",
        ]
        self.assertEqual([c for c, _, _ in build_status.BUSIEST_30], expected_codes)
        for code, name, tz in build_status.BUSIEST_30:
            self.assertTrue(name, f"Missing display name for {code}")
            ZoneInfo(tz)

    def test_is_weather(self) -> None:
        self.assertTrue(build_status.is_weather("thunderstorms"))
        self.assertTrue(build_status.is_weather("Wind / Gusts"))
        self.assertTrue(build_status.is_weather("Low Visibility"))
        self.assertFalse(build_status.is_weather("airport volume"))
        self.assertFalse(build_status.is_weather("OTHER: NATIONAL STOP"))
        self.assertFalse(build_status.is_weather(""))

    def test_faa_2_and_nws_jfk_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "status.json"
            payload = build_status.build_status(
                output_path=out_path,
                fixture_faa=FAA_2_FIXTURE,
                fixture_nws=NWS_JFK_FIXTURE,
            )
            self.assertTrue(out_path.is_file())
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, written)

        self.assertEqual(written["sources"], ["FAA", "NWS"])
        self.assertNotIn("stale", written)
        self.assertEqual(len(written["board"]), 30)

        levels = {item["code"]: item["level"] for item in written["board"]}
        self.assertEqual(levels["JFK"], "stop")
        self.assertEqual(levels["SFO"], "delay")
        self.assertEqual(levels["LGA"], "delay")
        self.assertEqual(levels["SAN"], "delay")
        self.assertEqual(levels["ATL"], "delay")
        self.assertEqual(levels["BOS"], "clear")
        # Partial closures in faa-2.xml (LAX, FLL, DCA, LAS) must be dropped.
        for code in ("LAX", "FLL", "DCA", "LAS"):
            self.assertEqual(levels[code], "clear")

        events_by_code = {ev["code"]: ev for ev in written["events"]}
        self.assertEqual(set(events_by_code.keys()), {"JFK", "SAN", "SFO", "LGA", "ATL"})

        jfk = events_by_code["JFK"]
        self.assertEqual(jfk["kind"], "ground_stop")
        self.assertEqual(jfk["name"], "John F. Kennedy International")
        self.assertEqual(jfk["status"], "CONFIRMED")
        self.assertEqual(jfk["alert"], "Severe Thunderstorm Warning")
        self.assertEqual(jfk["sources"], ["FAA", "NWS"])
        self.assertEqual(jfk["end_time"], "8:30 pm EST.")

        san = events_by_code["SAN"]
        self.assertEqual(san["kind"], "ground_delay")
        self.assertEqual(san["status"], "OFFICIAL")
        self.assertEqual(san["sources"], ["FAA"])
        self.assertEqual(san["avg"], "34 minutes")
        self.assertEqual(san["max"], "1 hour and 21 minutes")

        atl = events_by_code["ATL"]
        self.assertEqual(atl["kind"], "delay")
        self.assertEqual(atl["direction"], "Departure")
        self.assertEqual(atl["trend"], "Increasing")
        self.assertEqual(atl["status"], "OFFICIAL")

    def test_full_closure_included_and_partial_dropped(self) -> None:
        xml_text = """
        <AIRPORT_STATUS_INFORMATION>
          <Delay_type>
            <Name>Airport Closures</Name>
            <Airport_Closure_List>
              <Airport>
                <ARPT>BOS</ARPT>
                <Reason>!BOS 11/001 BOS AD AP CLSD 2611140000-2611140400</Reason>
                <Reopen>Nov 14 at 04:00 UTC.</Reopen>
              </Airport>
              <Airport>
                <ARPT>ORD</ARPT>
                <Reason>!ORD 11/002 ORD AD AP CLSD TO GA ACFT</Reason>
                <Reopen>Nov 14 at 05:00 UTC.</Reopen>
              </Airport>
            </Airport_Closure_List>
          </Delay_type>
        </AIRPORT_STATUS_INFORMATION>
        """
        events = build_status.parse_faa(xml_text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["code"], "BOS")
        self.assertEqual(events[0]["kind"], "closure")
        self.assertEqual(events[0]["end_time"], "Nov 14 at 04:00 UTC.")
        board = {item["code"]: item["level"] for item in build_status.build_board(events)}
        self.assertEqual(board["BOS"], "stop")
        self.assertEqual(board["ORD"], "clear")

    def test_feed_error_preserves_previous_events_and_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "status.json"
            first = build_status.build_status(
                output_path=out_path,
                fixture_faa=FAA_2_FIXTURE,
                fixture_nws=NWS_JFK_FIXTURE,
            )
            with mock.patch.object(
                build_status,
                "fetch_url",
                side_effect=urllib.error.URLError("network down"),
            ):
                fallback = build_status.build_status(output_path=out_path)

            self.assertTrue(fallback["stale"])
            self.assertIn("network down", fallback["error"])
            self.assertEqual(fallback["events"], first["events"])
            self.assertEqual(fallback["board"], first["board"])
            on_disk = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(on_disk["stale"])
            self.assertEqual(on_disk["events"], first["events"])

    def test_feed_error_without_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "status.json"
            with mock.patch.object(
                build_status,
                "fetch_url",
                side_effect=RuntimeError("boom"),
            ):
                payload = build_status.build_status(output_path=out_path)

            self.assertTrue(payload["stale"])
            self.assertIn("boom", payload["error"])
            self.assertEqual(payload["events"], [])
            self.assertEqual(len(payload["board"]), 30)
            self.assertTrue(all(b["level"] == "clear" for b in payload["board"]))

    def test_cli_with_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "status.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "build_status.py"),
                    "--fixture-faa",
                    str(FAA_2_FIXTURE),
                    "--fixture-nws",
                    str(NWS_JFK_FIXTURE),
                    "--output",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            data = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["board"]), 30)
            self.assertEqual(data["events"][0]["code"], "JFK")
            self.assertEqual(data["events"][0]["status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
