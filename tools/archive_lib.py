#!/usr/bin/env python3
"""History archive: storage core and read-only query API (AN23 Phase 3 item 1).

The archive is one JSONL file per month (YYYY-MM.jsonl), UTC times, one row per
airport per hour (key "hour_utc|CODE") plus one "national" row per hour
(key "hour_utc|NATIONAL"). It does not depend on the stream desk.

Everything here states past facts with counts and the period covered. Nothing
here predicts anything.

CLI: python tools/archive_lib.py stats
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

DEFAULT_DIR = Path.home() / "factory-scratch" / "an-archive"
NATIONAL = "NATIONAL"
STALE_MIN = 30

FLAG_FIELDS = ("ground_stop", "ground_delay", "delay", "closure")


def archive_dir(path: Optional[os.PathLike] = None) -> Path:
    if path:
        return Path(path)
    env = os.environ.get("AN_ARCHIVE_DIR")
    return Path(env).expanduser() if env else DEFAULT_DIR


# ---------- time helpers ----------

def parse_ts(text: Any) -> Optional[datetime]:
    """Parse '2026-11-14T09:50:00Z', '2026-11-14T09:00Z' or an offset form into aware UTC. None if not parsable."""
    if isinstance(text, datetime):
        return text if text.tzinfo else text.replace(tzinfo=timezone.utc)
    if not isinstance(text, str) or not text:
        return None
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hour_key(dt: Any) -> str:
    """Floor to the hour: '2026-11-14T09:00Z'."""
    d = parse_ts(dt)
    if d is None:
        raise ValueError(f"bad time: {dt!r}")
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00Z")


def month_of(hour: str) -> str:
    return hour[:7]


def row_key(hour: str, code: str) -> str:
    return f"{hour}|{code}"


def data_ts(row: dict) -> str:
    """The newest source time a row holds (sortable ISO text, '' when none)."""
    vals = [str(row.get(k) or "") for k in ("faa_updated_utc", "wx_obs_utc")]
    return max(vals)


def is_newer(new: dict, old: dict) -> bool:
    """True when `new` carries strictly newer source data than `old`."""
    return data_ts(new) > data_ts(old)


# ---------- storage ----------

@contextmanager
def archive_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    fh = open(directory / ".lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def carry_flags(new: dict, old: Optional[dict]) -> dict:
    """An hour holds one row. When newer data replaces earlier data from the same hour, a FAA flag seen earlier
    in that hour stays on (so a ground stop that ended at :30 still counts for the hour). Stale old rows carry nothing.
    Carried flag names are listed in 'flags_from_earlier'."""
    if not old or old.get("stale") or new.get("type") == "national":
        return new
    carried = [f for f in FLAG_FIELDS if old.get(f) is True and new.get(f) is False]
    if not carried:
        return new
    out = dict(new)
    for f in carried:
        out[f] = True
    out["flags_from_earlier"] = sorted(set(carried) | set(old.get("flags_from_earlier") or []))
    if not out.get("reason") and old.get("reason"):
        out["reason"] = old["reason"]
    return out


def month_file(directory: Path, month: str) -> Path:
    return directory / f"{month}.jsonl"


def month_files(directory: Path) -> list:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("????-??.jsonl") if p.is_file())


def read_month(path: Path) -> dict:
    """key -> row. Bad lines are skipped, never fatal."""
    rows: dict = {}
    try:
        fh = open(path, "r", encoding="utf-8")
    except OSError:
        return rows
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("k"):
                rows[row["k"]] = row
    return rows


def write_month_atomic(path: Path, rows: dict) -> None:
    """Write all rows to a temp file in the same folder, fsync, then rename over `path`.
    If anything fails before the rename, the old file stays and the temp file is removed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for k in sorted(rows):
                fh.write(json.dumps(rows[k], separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def upsert_rows(new_rows: Iterable[dict], directory: Optional[os.PathLike] = None,
                accept: Optional[Callable[[dict, Optional[dict]], bool]] = None) -> dict:
    """Merge rows into the monthly files. `accept(new, old_or_None)` decides; the default adds
    new keys and replaces an old row only when the new row holds strictly newer source data.
    Returns counts: added, updated, kept (existing row left alone)."""
    d = archive_dir(directory)
    accept = accept or (lambda new, old: old is None or is_newer(new, old))
    by_month: dict = {}
    for r in new_rows:
        by_month.setdefault(month_of(r["hour_utc"]), []).append(r)
    counts = {"added": 0, "updated": 0, "kept": 0}
    with archive_lock(d):
        for month, batch in sorted(by_month.items()):
            path = month_file(d, month)
            rows = read_month(path)
            changed = False
            for r in batch:
                old = rows.get(r["k"])
                if accept(r, old):
                    rows[r["k"]] = carry_flags(r, old)
                    counts["added" if old is None else "updated"] += 1
                    changed = True
                else:
                    counts["kept"] += 1
            if changed:
                write_month_atomic(path, rows)
    return counts


# ---------- queries (read only) ----------

def _range_hours(start: Any, end: Any) -> tuple:
    def conv(v: Any, is_end: bool) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, date) and not isinstance(v, datetime):
            v = datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
        if isinstance(v, str) and len(v) == 7:  # 'YYYY-MM'
            y, m = int(v[:4]), int(v[5:7])
            v = datetime(y, m, 1, tzinfo=timezone.utc)
        elif isinstance(v, str) and len(v) == 10:  # 'YYYY-MM-DD'
            v = parse_ts(v + "T00:00:00Z")
        return hour_key(v)
    return conv(start, False), conv(end, True)


def iter_rows(start: Any = None, end: Any = None, airports: Optional[Iterable[str]] = None,
              directory: Optional[os.PathLike] = None, kind: str = "airport") -> Iterator[dict]:
    """Rows with start <= hour < end, in hour order. start/end: ISO text, 'YYYY-MM', 'YYYY-MM-DD', date or datetime
    (None = open). `kind` is 'airport' (default), 'national' or 'all'."""
    d = archive_dir(directory)
    lo, hi = _range_hours(start, end)
    want = {a.upper() for a in airports} if airports else None
    for path in month_files(d):
        month = path.stem
        if lo and month < lo[:7]:
            continue
        if hi and month > hi[:7]:
            continue
        rows = read_month(path)
        for k in sorted(rows):
            r = rows[k]
            h = r.get("hour_utc", "")
            if lo and h < lo:
                continue
            if hi and h >= hi:
                continue
            is_nat = r.get("type") == "national"
            if kind == "airport" and is_nat:
                continue
            if kind == "national" and not is_nat:
                continue
            if want is not None and r.get("airport") not in want:
                continue
            yield r


def hour_counts(directory: Optional[os.PathLike] = None) -> dict:
    """hour_utc -> number of airport rows archived for that hour."""
    c: Counter = Counter()
    for r in iter_rows(directory=directory):
        c[r["hour_utc"]] += 1
    return dict(sorted(c.items()))


def is_any_delay(r: dict) -> bool:
    return any(r.get(f) for f in FLAG_FIELDS)


def _month_bounds(month_range: Any) -> tuple:
    if month_range is None:
        return None, None
    if isinstance(month_range, str):
        lo = hi = month_range
    else:
        lo, hi = month_range
    y, m = int(hi[:4]), int(hi[5:7])
    nxt = f"{y + (m // 12):04d}-{(m % 12) + 1:02d}"
    return lo, nxt


def delay_share(airport: str, month_range: Any = None, directory: Optional[os.PathLike] = None) -> dict:
    """Past fact: of the archived hours for `airport` in the months, how many had each FAA flag.
    month_range: 'YYYY-MM' or ('YYYY-MM', 'YYYY-MM') inclusive. Stale rows are counted apart, not in the shares."""
    lo, hi = _month_bounds(month_range)
    rows = list(iter_rows(lo, hi, [airport], directory))
    fresh = [r for r in rows if not r.get("stale")]
    hours = len({r["hour_utc"] for r in fresh})
    c = {f: sum(1 for r in fresh if r.get(f)) for f in FLAG_FIELDS}
    n_any = sum(1 for r in fresh if is_any_delay(r))
    out = {
        "airport": airport.upper(),
        "archived_hours": hours,
        "stale_rows_excluded": len(rows) - len(fresh),
        "hours_with_ground_stop": c["ground_stop"],
        "hours_with_ground_delay": c["ground_delay"],
        "hours_with_delay": c["delay"],
        "hours_with_closure": c["closure"],
        "hours_with_any_flag": n_any,
        "share_any_flag": round(n_any / hours, 4) if hours else None,
        "period": period_of(fresh),
        "source": "own archive of FAA NAS status as published by this site",
    }
    return out


def period_of(rows: list) -> Optional[dict]:
    hs = sorted(r["hour_utc"] for r in rows)
    return {"first_hour_utc": hs[0], "last_hour_utc": hs[-1]} if hs else None


def category_by_month(airport: str, directory: Optional[os.PathLike] = None) -> dict:
    """Past fact: counts of weather flight categories per calendar month ('01'..'12') for the airport,
    with the period covered. 'most_common' names the most frequent category archived; it is a count, not a forecast."""
    rows = [r for r in iter_rows(airports=[airport], directory=directory) if r.get("cat") and not r.get("stale")]
    out: dict = {}
    for mm in sorted({r["hour_utc"][5:7] for r in rows}):
        sel = [r for r in rows if r["hour_utc"][5:7] == mm]
        cnt = Counter(r["cat"] for r in sel)
        out[mm] = {
            "hours": len({r["hour_utc"] for r in sel}),
            "counts": dict(sorted(cnt.items())),
            "most_common": sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[0][0],
            "period": period_of(sel),
        }
    return out


def past_facts(airport: str, month_range: Any = None, directory: Optional[os.PathLike] = None) -> dict:
    """Bundle for a page: delay shares, weather categories by month, period. Counts only."""
    return {"delay": delay_share(airport, month_range, directory),
            "category_by_month": category_by_month(airport, directory)}


def archive_stats(directory: Optional[os.PathLike] = None) -> dict:
    d = archive_dir(directory)
    airports_rows = 0
    national_rows = 0
    stale = 0
    sources: Counter = Counter()
    hours: set = set()
    codes: set = set()
    files = month_files(d)
    for path in files:
        for r in read_month(path).values():
            if r.get("type") == "national":
                national_rows += 1
            else:
                airports_rows += 1
                codes.add(r.get("airport"))
            hours.add(r["hour_utc"])
            sources[r.get("source", "?")] += 1
            if r.get("stale"):
                stale += 1
    hs = sorted(hours)
    gaps: list = []
    if hs:
        t = parse_ts(hs[0])
        end = parse_ts(hs[-1])
        have = set(hs)
        while t < end:
            k = hour_key(t)
            if k not in have:
                gaps.append(k)
            t += timedelta(hours=1)
    return {
        "dir": str(d),
        "files": [p.name for p in files],
        "rows": airports_rows + national_rows,
        "airport_rows": airports_rows,
        "national_rows": national_rows,
        "airports": len(codes),
        "hours_with_data": len(hs),
        "first_hour": hs[0] if hs else None,
        "last_hour": hs[-1] if hs else None,
        "hours_with_gaps": len(gaps),
        "gap_hours_first20": gaps[:20],
        "stale_rows": stale,
        "sources": dict(sources),
    }


def main(argv: list) -> int:
    if len(argv) >= 2 and argv[1] == "stats":
        print(json.dumps(archive_stats(), indent=2))
        return 0
    print("usage: python tools/archive_lib.py stats", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
