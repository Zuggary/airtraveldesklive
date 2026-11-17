"""Build data/live.json: is the Twitch channel live right now? One server-side check per run (the 5-minute status workflow), so no visitor calls a
third party. Source: decapi.me/twitch/uptime/<channel> (free, no key, no account). The result is {"live": true|false|null, "checked_utc": "..."}:
null means the check failed or the answer was not understood, and the page then shows no green. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CHANNEL = "airtraveldesklive"
URL = "https://decapi.me/twitch/uptime/" + CHANNEL
UA = "airtraveldesklive-status/1.0 (+https://www.airtraveldesklive.com/sources)"


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


def build(text: Optional[str], now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {"live": parse_uptime(text) if text is not None else None, "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "channel": CHANNEL}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    a = ap.parse_args(argv)
    doc = build(fetch())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "live.json").write_text(json.dumps(doc), encoding="utf-8")
    print("build_live: live=%s" % doc["live"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
