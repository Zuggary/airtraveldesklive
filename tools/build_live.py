"""Build data/live.json from key-free, server-side Twitch and YouTube checks."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

CHANNEL = "airtraveldesklive"
URL = "https://decapi.me/twitch/uptime/" + CHANNEL
UA = "airtraveldesklive-status/1.0 (+https://www.airtraveldesklive.com/sources)"
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UCtEAjmjCJdR-pHgcZtIFI9w"
YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v="
YOUTUBE_FEED_NAMESPACES = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}
YOUTUBE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def parse_uptime(text: str) -> Optional[bool]:
    """True for an uptime like '4 minutes, 51 seconds', False for '<channel> is offline', None for anything else."""
    t = (text or "").strip().lower()
    if not t or len(t) > 200:
        return None
    if "offline" in t:
        return False
    if re.fullmatch(r"(\d+ (second|minute|hour|day|week|month|year)s?(, | and )?)+", t):
        return True
    return None


def fetch(url: str = URL, timeout: float = 10.0) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(2000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - any failure means unknown
        print("build_live: check failed: %s" % exc, file=sys.stderr)
        return None


def parse_youtube_feed(body: str) -> list[str]:
    """Take up to three valid video IDs in YouTube's newest-first feed order."""
    root = ElementTree.fromstring(body)
    if root.tag != "{%s}feed" % YOUTUBE_FEED_NAMESPACES["atom"]:
        raise ValueError("expected a YouTube Atom feed")
    ids = [node.text for node in root.findall("atom:entry/yt:videoId", YOUTUBE_FEED_NAMESPACES)]
    return [video_id for video_id in ids if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)][:3]


def parse_youtube_live(html: Optional[str]) -> Optional[bool]:
    """Check a recognizable watch page for a current broadcast."""
    if (not html or "ytInitialPlayerResponse" not in html
            or not re.match(r"\s*(?:<!doctype\s+html\s*>\s*)?<html\b", html, re.I)):
        return None

    ended = False
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"liveBroadcastDetails"\s*:\s*', html):
        try:
            details, _ = decoder.raw_decode(html, match.end())
        except ValueError:
            return None
        if not isinstance(details, dict):
            return None
        ended |= "endTimestamp" in details
    return '"isLiveNow":true' in html and not ended


def fetch_youtube_page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": YOUTUBE_UA})
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("unexpected YouTube response for %s" % url)
        return response.read().decode("utf-8")


def fetch_youtube() -> Optional[bool]:
    ids = None
    flags = {}
    try:
        ids = parse_youtube_feed(fetch_youtube_page(YOUTUBE_FEED_URL))
        for video_id in ids:
            try:
                flags[video_id] = parse_youtube_live(fetch_youtube_page(YOUTUBE_WATCH_URL + video_id))
            except Exception as exc:  # noqa: BLE001 - any failure means unknown
                flags[video_id] = None
                print("build_live: YouTube watch check failed: %s" % exc, file=sys.stderr)
            if flags[video_id] is True:
                return True
        return None if None in flags.values() else False
    except Exception as exc:  # noqa: BLE001 - any failure means unknown
        print("build_live: YouTube feed check failed: %s" % exc, file=sys.stderr)
        return None
    finally:
        print("build_live: youtube feed_ids=%s watch_live=%s" % (ids, flags))


def build(text: Optional[str], now: Optional[datetime] = None, *, youtube_live: Optional[bool] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    twitch_live = parse_uptime(text)
    return {
        "live": twitch_live,
        "twitch_live": twitch_live,
        "youtube_live": youtube_live,
        "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    a = ap.parse_args(argv)
    doc = build(fetch(), youtube_live=fetch_youtube())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live.json").write_text(json.dumps(doc), encoding="utf-8")
    print("build_live: twitch_live=%s youtube_live=%s" % (doc["twitch_live"], doc["youtube_live"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
