"""AN52: data/live.json for the Watch live button: parser, builder (no network), workflow step, copy list, and the page never calls a third party."""
import json, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_live  # noqa: E402


class LiveTest(unittest.TestCase):
    def test_parse(self):
        self.assertIs(build_live.parse_uptime("4 minutes, 51 seconds"), True)
        self.assertIs(build_live.parse_uptime("1 hour, 2 minutes, 3 seconds"), True)
        self.assertIs(build_live.parse_uptime("airtraveldesklive is offline"), False)
        for bad in ("", None, "Error: rate limited", "<html>", "x" * 500):
            self.assertIsNone(build_live.parse_uptime(bad))

    def test_build_marks_a_failed_check_unknown(self):
        now = datetime(2026, 11, 17, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(build_live.build(None, now), {"live": None, "checked_utc": "2026-11-17T01:00:00Z", "channel": "airtraveldesklive"})
        self.assertTrue(build_live.build("3 minutes, 1 second", now)["live"])

    def test_workflow_runs_the_check_and_ships_the_file(self):
        y = (ROOT / ".github/workflows/status.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/build_live.py --out data", y)
        self.assertIn("live.json", y.split("alert.json")[1])

    def test_visitors_only_read_our_own_file(self):
        js = (ROOT / "watch.js").read_text(encoding="utf-8")
        self.assertIn("/data/live.json", js)
        self.assertNotIn("decapi", js)


if __name__ == "__main__":
    unittest.main()
