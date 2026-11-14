#!/usr/bin/env python3
"""Append one archive row per airport per hour from this site's OWN published data files.

Reads https://www.airtraveldesklive.com/data/{airports,state,wx,tsa}.json once per run
(own site only, polite GET, 10 s timeout, User-Agent names the site). No other host is contacted.
Rows go to the monthly archive files via archive_lib (see there for the storage rules).

Usage: python tools/archive_hourly.py [--dry-run]
Env:   AN_ARCHIVE_DIR (default ~/factory-scratch/an-archive)
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_lib as lib  # noqa: E402

BASE = "https://www.airtraveldesklive.com/data/"
USER_AGENT = "AirTravelDeskLive-archive/1.0 (+https://www.airtraveldesklive.com; reads its own published data)"
TIMEOUT = 10
PAUSE = 0.5          # seconds between the (at most four) GETs
TSA_FRESH_H = 36     # a TSA number is "fresh" when tsa.json was fetched within this many hours
FILES = ("airports", "state", "wx", "tsa")


def fetch_json(name: str, timeout: int = TIMEOUT) -> Optional[dict]:
    """GET one of our own data files. Returns None for 404 (file absent); other errors raise."""
    url = f"{BASE}{name}.json"
    if not url.startswith(BASE):
        raise ValueError("own site only")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return data if isinstance(data, dict) else None


def _minutes(text: Any) -> Optional[int]:
    if not isinstance(text, str) or not text:
        return None
    h = re.search(r"(\d+)\s*hours?", text, re.IGNORECASE)
    m = re.search(r"(\d+)\s*minutes?", text, re.IGNORECASE)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def _age_min(ts: Any, now: datetime) -> Optional[float]:
    d = lib.parse_ts(ts)
    return (now - d).total_seconds() / 60.0 if d else None


def _clean(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None and v != ""}


def build_rows(files: dict, run_dt: datetime) -> list:
    """Turn the fetched files into archive rows. `files` maps airports/state/wx/tsa to parsed JSON (or None)."""
    airports_j = files.get("airports") or {}
    state_j = files.get("state") or {}
    wx_j = files.get("wx") or {}
    tsa_j = files.get("tsa") or {}
    hour = lib.hour_key(run_dt)
    run_utc = lib.iso(run_dt)

    faa_updated = airports_j.get("updated_utc") or state_j.get("updated_utc")
    faa_age = _age_min(faa_updated, run_dt)
    faa_stale = faa_age is None or faa_age > lib.STALE_MIN
    wx_fetched = wx_j.get("fetched_utc")
    wx_age = _age_min(wx_fetched, run_dt)
    wx_stale = bool(wx_j) and (wx_age is None or wx_age > lib.STALE_MIN)

    board = {b.get("code"): b for b in (state_j.get("board") or []) if isinstance(b, dict)}
    hubs = wx_j.get("hubs") or {}
    cards = airports_j.get("airports") or {}
    codes = sorted(set(cards) | set(board) | set(hubs))

    rows = []
    totals = {"ground_stop": 0, "ground_delay": 0, "delay": 0, "closure": 0}
    for code in codes:
        card = cards.get(code) or {}
        b = board.get(code) or {}
        kinds = {str(e.get("kind")) for e in (card.get("events") or []) if isinstance(e, dict)}
        flags = {f: (f in kinds) for f in lib.FLAG_FIELDS}
        for f, on in flags.items():
            totals[f] += 1 if on else 0
        mins = b.get("avg_min")
        if mins is None:
            vals = [_minutes((e.get("avg") or e.get("max") or "")) for e in (card.get("events") or []) if isinstance(e, dict)]
            vals = [v for v in vals if v is not None]
            mins = max(vals) if vals else None
        w = hubs.get(code) or card.get("wx") or {}
        stale = faa_stale or (bool(hubs) and wx_stale)
        row = {
            "k": lib.row_key(hour, code), "type": "airport", "hour_utc": hour, "airport": code,
            "faa_level": card.get("level") or None,       # clear / delay / stop, as the site publishes it
            "faa_status": b.get("status") or b.get("level") or None,
            "delay_min": mins,
            "reason": card.get("reason") or None,
            "ground_stop": flags["ground_stop"], "ground_delay": flags["ground_delay"],
            "delay": flags["delay"], "closure": flags["closure"],
            "cat": w.get("cat"), "wind_kt": w.get("wind_kt"), "gust_kt": w.get("gust_kt"),
            "vis_sm": w.get("vis_sm"), "ceiling_ft": w.get("ceiling_ft"), "temp_f": w.get("temp_f"),
            "faa_updated_utc": faa_updated, "wx_obs_utc": w.get("obs_utc"),
            "run_utc": run_utc, "source": "live",
        }
        row = _clean(row)
        if stale:
            row["stale"] = True
            row["stale_why"] = ",".join(x for x, on in (("faa", faa_stale), ("wx", bool(hubs) and wx_stale)) if on)
        rows.append(row)

    if rows:
        nat = {
            "k": lib.row_key(hour, lib.NATIONAL), "type": "national", "hour_utc": hour, "airport": lib.NATIONAL,
            "n_airports": len(rows),
            "n_ground_stop": totals["ground_stop"], "n_ground_delay": totals["ground_delay"],
            "n_delay": totals["delay"], "n_closure": totals["closure"],
            "faa_updated_utc": faa_updated, "run_utc": run_utc, "source": "live",
        }
        tsa_age = _age_min(tsa_j.get("fetched_utc"), run_dt) if tsa_j else None
        tsa_age_h = tsa_age / 60.0 if tsa_age is not None else None
        if tsa_j and tsa_age_h is not None and tsa_age_h <= TSA_FRESH_H and tsa_j.get("latest_count") is not None:
            nat["tsa_count"] = tsa_j.get("latest_count")
            nat["tsa_date"] = tsa_j.get("latest_date")
            nat["tsa_fetched_utc"] = tsa_j.get("fetched_utc")
        nat = _clean(nat)
        if faa_stale:
            nat["stale"] = True
            nat["stale_why"] = "faa"
        rows.append(nat)
    return rows


def run(directory=None, fetcher: Optional[Callable[[str], Optional[dict]]] = None,
        now: Optional[datetime] = None, pause: float = PAUSE, dry_run: bool = False) -> dict:
    fetch = fetcher or fetch_json
    run_dt = now or datetime.now(timezone.utc)
    files: dict = {}
    errors = []
    for i, name in enumerate(FILES):
        if i and pause:
            time.sleep(pause)
        try:
            files[name] = fetch(name)
        except Exception as e:  # network or parse; one file missing is not fatal
            files[name] = None
            errors.append(f"{name}: {type(e).__name__}")
    if not files.get("airports") and not files.get("state"):
        return {"ok": False, "error": "no airports.json or state.json", "fetch_errors": errors}
    rows = build_rows(files, run_dt)
    if dry_run:
        return {"ok": True, "dry_run": True, "rows": len(rows), "fetch_errors": errors}
    counts = lib.upsert_rows(rows, directory)
    return {"ok": True, "hour_utc": lib.hour_key(run_dt), "rows_built": len(rows),
            "stale": sum(1 for r in rows if r.get("stale")), "fetch_errors": errors, **counts}


def main(argv: list) -> int:
    res = run(dry_run="--dry-run" in argv)
    print(f"{lib.iso(datetime.now(timezone.utc))} archive_hourly {json.dumps(res, sort_keys=True)}")
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
