#!/usr/bin/env python3
"""Write data/history-summary.json from the hourly archive (AN32).

The archive lives outside the repo (~/factory-scratch/an-archive). The site build has no access to it, so this
script copies a small summary into the repo: for each airport, one letter per hour for the last N hours.
  c = a reading with no FAA program   d = delay or ground delay   s = ground stop or closure   - = no reading
It states past facts only. Run it on the machine that holds the archive, then commit the file.

Usage: python tools/archive_snapshot.py [--hours 72] [--out data/history-summary.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from tools import archive_lib as al
except ImportError:  # run as a script
    import archive_lib as al  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent


def letter(row: dict) -> str:
    if row.get("ground_stop") or row.get("closure"):
        return "s"
    if row.get("ground_delay") or row.get("delay"):
        return "d"
    return "c"


def build(hours: int = 72, directory=None, now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    keys = [al.hour_key(now - timedelta(hours=i)) for i in range(hours - 1, -1, -1)]
    start, end = keys[0], al.hour_key(now + timedelta(hours=1))
    cells: dict[str, dict[str, str]] = {}
    total = 0
    for r in al.iter_rows(start=start, end=end, directory=directory):
        cells.setdefault(r["airport"], {})[r["hour_utc"]] = letter(r)
        total += 1
    airports = {code: "".join(by_hour.get(k, "-") for k in keys) for code, by_hour in sorted(cells.items())}
    seen = sorted({k for by in cells.values() for k in by})
    return {
        "source": "Air Travel Desk hourly archive of FAA NAS status",
        "generated_utc": al.iso(datetime.now(timezone.utc)),
        "hours": keys,
        "first_reading_utc": seen[0] if seen else "",
        "last_reading_utc": seen[-1] if seen else "",
        "rows": total,
        "airports": airports,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--out", default=str(ROOT / "data" / "history-summary.json"))
    ap.add_argument("--archive", default=None)
    a = ap.parse_args(argv)
    out = build(a.hours, a.archive)
    Path(a.out).write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"archive_snapshot: {len(out['airports'])} airports, {out['rows']} readings, {out['first_reading_utc']} to {out['last_reading_utc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
