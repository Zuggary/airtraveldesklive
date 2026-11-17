"""Test the live status builder with synthetic, offline responses."""
import json, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_live  # noqa: E402

LIVE = '<html><script>var ytInitialPlayerResponse = {"isLiveNow":true};</script></html>'
OFFLINE = '<!DOCTYPE html><html><script>var ytInitialData = {"isLiveNow":false};</script></html>'


class LiveTest(unittest.TestCase):
    def test_parse(self):
        self.assertIs(build_live.parse_uptime("4 minutes, 51 seconds"), True)
        self.assertIs(build_live.parse_uptime("1 hour, 2 minutes, 3 seconds"), True)
        self.assertIs(build_live.parse_uptime("airtraveldesklive is offline"), False)
        for bad in ("", None, "Error: rate limited", "<html>", "x" * 500):
            self.assertIsNone(build_live.parse_uptime(bad))

    def test_parse_youtube(self):
        self.assertIs(build_live.parse_youtube_live(LIVE), True)
        self.assertIs(build_live.parse_youtube_live(OFFLINE), False)
        self.assertIs(build_live.parse_youtube_live(OFFLINE.replace('{"isLiveNow":false}', '{}')), False)
        for bad in (None, "", '{"isLiveNow":true}', "<html><title>Service unavailable</title></html>"):
            self.assertIsNone(build_live.parse_youtube_live(bad))

    def test_build_shape(self):
        now = datetime(2026, 11, 17, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(build_live.build(None, now), {
            "live": None, "twitch_live": None, "youtube_live": None, "checked_utc": "2026-11-17T01:00:00Z",
        })
        self.assertEqual(build_live.build("3 minutes, 1 second", now, youtube_html=OFFLINE), {
            "live": True, "twitch_live": True, "youtube_live": False, "checked_utc": "2026-11-17T01:00:00Z",
        })

    @staticmethod
    def response(body, url=build_live.YOUTUBE_URL, status=200):
        context = MagicMock()
        response = context.__enter__.return_value
        response.status = status
        response.geturl.return_value = url
        response.read.return_value = body
        return context

    def test_main_writes_json_even_when_one_or_both_checks_fail(self):
        twitch = self.response(b"airtraveldesklive is offline")
        youtube = self.response(LIVE.encode(), "https://www.youtube.com/watch?v=synthetic")
        for results, expected in (
            ((TimeoutError("Twitch timeout"), youtube), (None, True)),
            ((twitch, TimeoutError("YouTube timeout")), (False, None)),
            ((OSError("Twitch unavailable"), OSError("YouTube unavailable")), (None, None)),
        ):
            with self.subTest(expected=expected), TemporaryDirectory(dir=ROOT) as out:
                with patch.object(build_live.urllib.request, "urlopen", side_effect=results) as urlopen:
                    self.assertEqual(build_live.main(["--out", out]), 0)
                saved = json.loads((Path(out) / "live.json").read_text())
                self.assertEqual(set(saved), {"live", "twitch_live", "youtube_live", "checked_utc"})
                self.assertIs(saved["live"], expected[0])
                self.assertIs(saved["twitch_live"], expected[0])
                self.assertIs(saved["youtube_live"], expected[1])
                request = urlopen.call_args.args[0]
                self.assertEqual(request.full_url, build_live.YOUTUBE_URL)
                self.assertEqual(request.get_method(), "GET")
                self.assertIn("Mozilla/5.0", request.get_header("User-agent"))
                self.assertEqual(urlopen.call_args.kwargs["timeout"], 15)

    def test_youtube_rejects_unexpected_responses(self):
        for response in (
            self.response(LIVE.encode(), status=206),
            self.response(LIVE.encode(), "https://consent.youtube.com/"),
            self.response(b"\xff"),
        ):
            with patch.object(build_live.urllib.request, "urlopen", return_value=response):
                self.assertIsNone(build_live.fetch_youtube())

    def test_workflow_runs_the_check_and_ships_the_file(self):
        y = (ROOT / ".github/workflows/status.yml").read_text(encoding="utf-8")
        self.assertIn("python tools/build_live.py --out data", y)
        self.assertIn("live.json", y.split("alert.json")[1])

    def test_youtube_player_does_not_use_twitch_uptime(self):
        js = (ROOT / "watch.js").read_text(encoding="utf-8")
        self.assertIn('win.fetch("/data/live.json', js)
        self.assertIn('applyLive("unknown")', js)
        self.assertNotIn("decapi", js)


if __name__ == "__main__":
    unittest.main()
