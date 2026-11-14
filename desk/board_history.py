"""Rolling board history for the website: one reading per UTC hour, the last 24 hours, in data/board-history.json.

The 5-minute job keeps no disk between runs except the Actions cache, so it reads the previously published file
(like state.json) and adds the current hour if that hour has no reading yet. The trend arrow on the board compares
now with the reading from the hour that holds "now minus 60 minutes". No such reading: no arrow.
Source for every reading: FAA NAS status.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

HOUR_FMT = "%Y-%m-%dT%H:00Z"
KEEP_HOURS = 24
SOURCE = "FAA NAS status"


def hour_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(HOUR_FMT)


def hour_ago(prev: Optional[dict[str, Any]], now: datetime) -> Optional[dict[str, dict[str, Any]]]:
    """{code: {level, avg_min}} from the reading one hour ago, or None."""
    want = hour_utc(now - timedelta(hours=1))
    for p in (prev or {}).get("points") or []:
        if p.get("hour_utc") == want and isinstance(p.get("board"), dict):
            return p["board"]
    return None


def add_hour(prev: Optional[dict[str, Any]], board: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Add this hour's reading when missing. Keeps the last 24 hours."""
    hr = hour_utc(now)
    points = [p for p in ((prev or {}).get("points") or []) if isinstance(p, dict) and p.get("hour_utc")]
    if not any(p["hour_utc"] == hr for p in points) and board:
        points.append({
            "hour_utc": hr, "t_utc": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "board": {t["code"]: {"level": t.get("status", "green"), "avg_min": t.get("avg_min")} for t in board},
        })
    points.sort(key=lambda p: p["hour_utc"])
    return {"source": SOURCE, "points": points[-KEEP_HOURS:]}
