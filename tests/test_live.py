"""Test the live status builder with synthetic, offline responses."""
import json, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_live  # noqa: E402

VIDEO_IDS = ["Example_A-1", "Example_B-2", "Example_C-3", "Example_D-4"]
FEED = (
    '<feed xmlns="http://www.w3.org/2005/Atom" '
    'xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
    + "".join(f"<entry><yt:videoId>{video_id}</yt:videoId></entry>"
              for video_id in [VIDEO_IDS[0], "bad?video01", "too-short", *VIDEO_IDS[1:]])
    + "</feed>"
)
LIVE = (
    '<html><script>var ytInitialPlayerResponse = {"endTimestamp":"outside",'
    '"liveBroadcastDetails":{"isLiveNow":true}};</script></html>'
)
ENDED = LIVE.replace('"isLiveNow":true', '"isLiveNow":true,"endTimestamp":"2026-01-01T00:00:00Z"')
OFFLINE = '<!DOCTYPE html><html><script>var ytInitialPlayerResponse = {};</script></html>'
UNRECOGNIZED = '<html><script>var ytInitialData = {"isLiveNow":true};</script></html>'


class LiveTest(unittest.TestCase):
    def test_parse(self):
        self.assertIs(build_live.parse_uptime("4 minutes, 51 seconds"), True)
        self.assertIs(build_live.parse_uptime("1 hour, 2 minutes, 3 seconds"), True)
        self.assertIs(build_live.parse_uptime("airtraveldesklive is offline"), False)
        for bad in ("", None, "Error: rate limited", "<html>", "x" * 500):
            self.assertIsNone(build_live.parse_uptime(bad))

    def test_parse_youtube_feed(self):
        self.assertEqual(build_live.parse_youtube_feed(FEED), VIDEO_IDS[:3])

    def test_parse_youtube_watch_page(self):
        self.assertIs(build_live.parse_youtube_live(LIVE), True)
        self.assertIs(build_live.parse_youtube_live(ENDED), False)
        self.assertIs(build_live.parse_youtube_live(OFFLINE), False)
        for bad in (None, "", UNRECOGNIZED, LIVE.replace("true}}", "true")):
            self.assertIsNone(build_live.parse_youtube_live(bad))

    def test_build_shape(self):
        now = datetime(2026, 11, 17, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(build_live.build(None, now), {
            "live": None, "twitch_live": None, "youtube_live": None, "checked_utc": "2026-11-17T01:00:00Z",
        })
        self.assertEqual(build_live.build("3 minutes, 1 second", now, youtube_live=False), {
            "live": True, "twitch_live": True, "youtube_live": False, "checked_utc": "2026-11-17T01:00:00Z",
        })

    @staticmethod
    def response(body, url=build_live.YOUTUBE_FEED_URL, status=200):
        context = MagicMock()
        response = context.__enter__.return_value
        response.status = status
        response.geturl.return_value = url
        response.read.return_value = body
        return context

    def test_main_writes_json_even_when_one_or_both_checks_fail(self):
        twitch = self.response(b"airtraveldesklive is offline")
        feed = self.response(FEED.encode())
        youtube = self.response(LIVE.encode(), build_live.YOUTUBE_WATCH_URL + VIDEO_IDS[0])
        for results, expected in (
            ((TimeoutError("Twitch timeout"), feed, youtube), (None, True)),
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
                youtube_calls = urlopen.call_args_list[1:]
                expected_urls = [build_live.YOUTUBE_FEED_URL]
                if expected[1] is True:
                    expected_urls.append(build_live.YOUTUBE_WATCH_URL + VIDEO_IDS[0])
                self.assertEqual([call.args[0].full_url for call in youtube_calls], expected_urls)
                for call in youtube_calls:
                    request = call.args[0]
                    self.assertEqual(request.get_method(), "GET")
                    self.assertEqual(request.get_header("User-agent"), build_live.YOUTUBE_UA)
                    self.assertEqual(call.kwargs["timeout"], 15)

    def test_youtube_checks_watch_pages_in_order(self):
        for pages, expected in (
            ((ENDED, LIVE), True),
            ((ENDED, OFFLINE, OFFLINE), False),
            ((UNRECOGNIZED, ENDED, OFFLINE), None),
            ((UNRECOGNIZED, LIVE), True),
            ((TimeoutError("watch timeout"), ENDED, OFFLINE), None),
        ):
            responses = [self.response(FEED.encode())]
            urls = [build_live.YOUTUBE_WATCH_URL + video_id for video_id in VIDEO_IDS[:len(pages)]]
            for page, url in zip(pages, urls):
                responses.append(self.response(page.encode(), url) if isinstance(page, str) else page)
            with self.subTest(expected=expected), patch.object(
                build_live.urllib.request, "urlopen", side_effect=responses
            ) as urlopen:
                self.assertIs(build_live.fetch_youtube(), expected)
                self.assertEqual(
                    [call.args[0].full_url for call in urlopen.call_args_list],
                    [build_live.YOUTUBE_FEED_URL, *urls],
                )

    def test_youtube_rejects_unexpected_feed_responses(self):
        for response in (
            self.response(FEED.encode(), status=206),
            self.response(FEED.encode(), "https://consent.youtube.com/"),
            self.response(b"\xff"),
            self.response(b"<feed"),
            self.response(b"<html/>"),
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
