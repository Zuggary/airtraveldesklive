#!/usr/bin/env python3
"""Backfill the archive from the stream desk's logs (read only): board.jsonl, wx.jsonl, faa-hourly.jsonl, tsa.jsonl.

Rows use the live row format with source 'desk-log'. An hour/airport already archived by the live
fetch is skipped; an older desk-log row is replaced only by newer data.

Usage: python tools/archive_backfill.py [--history DIR]
Env:   AN_ARCHIVE_DIR, AN_HISTORY_DIR (default ~/factory-scratch/an-history)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_lib as lib  # noqa: E402

DEFAULT_HISTORY = Path.home() / "factory-scratch" / "an-history"
LEVEL_WORD = {"green": "clear", "amber": "delay", "red": "stop"}
FAA_KINDS = ("ground_stop", "ground_delay", "delay", "closure")
TSA_FRESH_H = 36


def history_dir(path: Optional[os.PathLike] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("AN_HISTORY_DIR")
    return Path(env).expanduser() if env else DEFAULT_HISTORY


def read_jsonl(path: Path) -> list:
    out = []
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("hour_utc"):
                out.append(r)
    return out


def _latest_per(rows: list, keyfn) -> dict:
    """Keep the row with the newest t_utc for each key."""
    best: dict = {}
    for r in rows:
        k = keyfn(r)
        if k not in best or str(r.get("t_utc") or "") >= str(best[k].get("t_utc") or ""):
            best[k] = r
    return best


def build_rows(history: Path) -> list:
    board = _latest_per(read_jsonl(history / "board.jsonl"), lambda r: (r["hour_utc"], r.get("code")))
    wx = _latest_per(read_jsonl(history / "wx.jsonl"), lambda r: (r["hour_utc"], r.get("code")))
    faa = _latest_per(read_jsonl(history / "faa-hourly.jsonl"), lambda r: r["hour_utc"])
    tsa_rows = [r for r in read_jsonl_any(history / "tsa.jsonl")]

    rows: dict = {}

    def row_for(hour: str, code: str) -> dict:
        k = lib.row_key(hour, code)
        if k not in rows:
            rows[k] = {"k": k, "type": "airport", "hour_utc": hour, "airport": code, "source": "desk-log"}
        return rows[k]

    for (hour, code), b in board.items():
        if not code:
            continue
        r = row_for(hour, code)
        r["faa_level"] = LEVEL_WORD.get(b.get("level"))
        r["faa_status"] = b.get("level")
        if b.get("avg_min") is not None:
            r["delay_min"] = b["avg_min"]
        r["faa_updated_utc"] = b.get("t_utc")
        lvl = r["faa_level"]
        r.setdefault("ground_stop", False)
        r.setdefault("ground_delay", False)
        r.setdefault("delay", lvl == "delay")
        r.setdefault("closure", False)
    for (hour, code), w in wx.items():
        if not code:
            continue
        r = row_for(hour, code)
        for src, dst in (("cat", "cat"), ("wind_kt", "wind_kt"), ("gust_kt", "gust_kt"), ("vis_sm", "vis_sm"),
                         ("ceiling_ft", "ceiling_ft"), ("temp_f", "temp_f"), ("obs_utc", "wx_obs_utc")):
            if w.get(src) is not None:
                r[dst] = w[src]
        r["run_utc"] = w.get("t_utc")
    # faa-hourly: counts per kind and the airports involved. Assign a kind only when it is unambiguous.
    for hour, f in faa.items():
        listed = [c for c in (f.get("airports") or []) if isinstance(c, str)]
        nonzero = [k for k in FAA_KINDS if f.get(k)]
        for code in listed:
            r = row_for(hour, code)
            r["faa_updated_utc"] = max(str(r.get("faa_updated_utc") or ""), str(f.get("t_utc") or "")) or None
            if len(nonzero) == 1:
                for k in FAA_KINDS:
                    r[k] = (k == nonzero[0])
                r["faa_level"] = "stop" if nonzero[0] in ("ground_stop", "closure") else "delay"
            else:
                r["faa_event_kind"] = "unknown"   # several kinds that hour; the log does not say which airport had which
    # national row per hour
    hours = sorted({r["hour_utc"] for r in rows.values()} | set(faa))
    for hour in hours:
        f = faa.get(hour) or {}
        arows = [r for r in rows.values() if r["hour_utc"] == hour and r["type"] == "airport"]
        nat = {
            "k": lib.row_key(hour, lib.NATIONAL), "type": "national", "hour_utc": hour, "airport": lib.NATIONAL,
            "n_airports": len(arows),
            "n_ground_stop": f.get("ground_stop"), "n_ground_delay": f.get("ground_delay"),
            "n_delay": f.get("delay"), "n_closure": f.get("closure"),
            "faa_updated_utc": f.get("t_utc"), "source": "desk-log",
        }
        if not f:  # no faa-hourly record: count from the board rows only for the 'red' ones
            nat["n_ground_stop"] = nat["n_ground_delay"] = nat["n_delay"] = nat["n_closure"] = None
        hdt = lib.parse_ts(hour)
        for t in tsa_rows:
            age = (hdt - lib.parse_ts(t.get("t_utc"))) if lib.parse_ts(t.get("t_utc")) else None
            if age is not None and timedelta(0) <= age <= timedelta(hours=TSA_FRESH_H) and t.get("count") is not None:
                nat["tsa_count"], nat["tsa_date"], nat["tsa_fetched_utc"] = t["count"], t.get("date"), t.get("t_utc")
        rows[nat["k"]] = {k: v for k, v in nat.items() if v is not None}
    out = []
    for r in rows.values():
        out.append({k: v for k, v in r.items() if v is not None and v != ""})
    return out


def read_jsonl_any(path: Path) -> list:
    """Like read_jsonl but for files whose rows have no hour_utc (tsa.jsonl)."""
    out = []
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
    return out


def run(history: Optional[os.PathLike] = None, directory: Optional[os.PathLike] = None) -> dict:
    hist = history_dir(history)
    rows = build_rows(hist)

    def accept(new: dict, old: Optional[dict]) -> bool:
        if old is None:
            return True
        if old.get("source") == "live":
            return False
        return lib.is_newer(new, old)

    counts = lib.upsert_rows(rows, directory, accept=accept)
    arows = [r for r in rows if r["type"] == "airport"]
    return {
        "ok": True, "history_dir": str(hist),
        "rows_built": len(rows), "hours": len({r["hour_utc"] for r in rows}),
        "airports": len({r["airport"] for r in arows}), "airport_rows": len(arows), **counts,
    }


def main(argv: list) -> int:
    hist = argv[argv.index("--history") + 1] if "--history" in argv else None
    res = run(hist)
    print(f"archive_backfill {json.dumps(res, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
