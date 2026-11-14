"""Read the hourly FAA log written by tools/history_logger.py. Stdlib only.

Rows can repeat an hour_utc: the last row for an hour wins. Rows with an "error" key are skipped.
Returns {now_count, week_ago_count, hour_utc} when the same hour 7 days earlier exists, else None.
"count" = ground stops + ground delays + delays + closures logged that hour.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_PATH = Path.home() / "factory-scratch" / "an-history" / "faa-hourly.jsonl"
KINDS = ("ground_stop", "ground_delay", "delay", "closure")
HOUR_FMT = "%Y-%m-%dT%H:00Z"


def _count(row: dict[str, Any]) -> int:
    return sum(int(row.get(k) or 0) for k in KINDS)


def load_hours(path: Path | str) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            row = json.loads(line)
            if row.get("error") or not row.get("hour_utc"):
                continue
            out[row["hour_utc"]] = _count(row)
        except (ValueError, AttributeError, TypeError):
            continue
    return out


def compare(path: Path | str, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Latest logged hour against the same hour 7 days earlier."""
    hours = load_hours(path)
    if not hours:
        return None
    latest = max(hours)
    if now is not None:
        # Ignore a log that stopped: the newest row must be within 3 hours of now.
        try:
            t = datetime.strptime(latest, HOUR_FMT).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        if now - t > timedelta(hours=3):
            return None
    week = (datetime.strptime(latest, HOUR_FMT) - timedelta(days=7)).strftime(HOUR_FMT)
    if week not in hours:
        return None
    return {"now_count": hours[latest], "week_ago_count": hours[week], "hour_utc": latest}


def path_from_env(replay: bool = False) -> Optional[Path]:
    env = os.environ.get("AN_HISTORY")
    if env:
        return Path(env)
    return None if replay else DEFAULT_PATH
