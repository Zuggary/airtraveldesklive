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
from urllib.parse import urlsplit

CHANNEL = "airtraveldesklive"
URL = "https://decapi.me/twitch/uptime/" + CHANNEL
UA = "airtraveldesklive-status/1.0 (+https://www.airtraveldesklive.com/sources)"
YOUTUBE_URL = "https://www.youtube.com/@AirTravelDeskLive/live"
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


def parse_youtube_live(html: Optional[str]) -> Optional[bool]:
    """Read the exact marker from a recognizable YouTube HTML page."""
    if not html or not re.match(r"\s*(?:<!doctype\s+html\s*>\s*)?<html\b", html, re.I):
        return None
    if '"isLiveNow":true' in html:
        return True
    if "ytInitialData" in html or "ytInitialPlayerResponse" in html:
        return False
    return None


def fetch_youtube() -> Optional[str]:
    try:
        req = urllib.request.Request(YOUTUBE_URL, headers={"User-Agent": YOUTUBE_UA})
        with urllib.request.urlopen(req, timeout=15) as response:
            final_url = urlsplit(response.geturl())
            page = final_url.path.lower().rstrip("/")
            channel = "/@airtraveldesklive"
            if (response.status != 200 or final_url.hostname != "www.youtube.com"
                    or page not in (channel, channel + "/live", channel + "/featured", channel + "/streams", "/watch")):
                return None
            body = response.read().decode("utf-8")
            import re as _re
            _m = _re.search(r'rel="canonical" href="([^"]+)', body); _t = _re.search(r"<title>([^<]{0,80})", body); _b = body.find('"liveBroadcastDetails"')
            print("build_live: youtube page final=%s bytes=%d live_marker=%s player=%s canonical=%s title=%r isLive=%s lbd=%r" % (final_url.geturl(), len(body), '"isLiveNow":true' in body, 'ytInitialPlayerResponse' in body, _m and _m.group(1), _t and _t.group(1), '"isLive":true' in body, body[_b:_b + 160] if _b >= 0 else None))
            return body
    except Exception as exc:  # noqa: BLE001 - any failure means unknown
        print("build_live: YouTube check failed: %s" % exc, file=sys.stderr)
        return None


def build(text: Optional[str], now: Optional[datetime] = None, *, youtube_html: Optional[str] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    twitch_live = parse_uptime(text)
    return {
        "live": twitch_live,
        "twitch_live": twitch_live,
        "youtube_live": parse_youtube_live(youtube_html),
        "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    a = ap.parse_args(argv)
    doc = build(fetch(), youtube_html=fetch_youtube())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live.json").write_text(json.dumps(doc), encoding="utf-8")
    print("build_live: twitch_live=%s youtube_live=%s" % (doc["twitch_live"], doc["youtube_live"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
