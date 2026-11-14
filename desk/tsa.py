"""Fetch and parse TSA checkpoint volumes. Standard library only (html.parser)."""
from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional

from desk.feeds import USER_AGENT

BASE_URL = "https://www.tsa.gov/travel/passenger-volumes"
MAX_AGE_SEC = 6 * 3600.0
FIX_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: Optional[list[str]] = None
        self._cell: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def parse_volumes(html: str) -> dict[date, int]:
    """Return {date: people screened} from the date/number table."""
    p = _TableParser()
    p.feed(html)
    out: dict[date, int] = {}
    for row in p.rows:
        if len(row) < 2:
            continue
        try:
            d = datetime.strptime(row[0], "%m/%d/%Y").date()
            n = int(row[1].replace(",", ""))
        except ValueError:
            continue
        out[d] = n
    return out


def build_summary(this_year: dict[date, int], last_year: dict[date, int], fetched_utc: str) -> dict[str, Any]:
    """Latest day against the same weekday one year earlier (date minus 364 days)."""
    if not this_year:
        raise ValueError("no TSA rows parsed")
    latest = max(this_year)
    ly = latest - timedelta(days=364)
    both = {**last_year, **this_year}
    return {
        "latest_date": latest.isoformat(),
        "latest_count": this_year[latest],
        "ly_date": ly.isoformat(),
        "ly_count": both.get(ly),
        "fetched_utc": fetched_utc,
    }


def thanksgiving(year: int) -> date:
    """4th Thursday of November."""
    d = date(year, 11, 1)
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=21)


def build_full(all_days: dict[date, int], today: date, fetched_utc: str) -> dict[str, Any]:
    """Full tsa.json payload from every parsed day (all years merged).

    Keeps the flat keys of build_summary and adds latest/ly objects, last7, record and thanksgiving.
    """
    if not all_days:
        raise ValueError("no TSA rows parsed")
    latest = max(all_days)
    base = build_summary(all_days, {}, fetched_utc)
    ly = latest - timedelta(days=364)
    out: dict[str, Any] = dict(base)
    out["latest"] = {"date": latest.isoformat(), "count": all_days[latest]}
    out["ly"] = {"date": ly.isoformat(), "count": all_days.get(ly)}
    last7 = []
    for k in range(6, -1, -1):
        d = latest - timedelta(days=k)
        ld = d - timedelta(days=364)
        last7.append({"date": d.isoformat(), "count": all_days.get(d), "ly_date": ld.isoformat(), "ly_count": all_days.get(ld)})
    out["last7"] = last7
    complete = all(r["count"] is not None and r["ly_count"] is not None for r in last7)
    out["total7"] = sum(r["count"] for r in last7) if complete else None
    out["ly_total7"] = sum(r["ly_count"] for r in last7) if complete else None
    out["pct7"] = round((out["total7"] - out["ly_total7"]) / out["ly_total7"] * 100, 2) if complete else None
    rd = max(all_days, key=lambda d: (all_days[d], d))
    years = sorted({d.year for d in all_days})
    out["record"] = {"date": rd.isoformat(), "count": all_days[rd], "years_scanned": years}
    out["latest_pct_of_record"] = round(all_days[latest] / all_days[rd] * 100, 2)
    # Thanksgiving: this year's, or next year's once this year's week is over.
    tg = thanksgiving(today.year)
    if (today - tg).days > 4:
        tg = thanksgiving(today.year + 1)
    ref = thanksgiving(tg.year - 1)
    week = []
    for k in range(-4, 5):  # Sunday before .. Monday after
        d = ref + timedelta(days=k)
        if d in all_days:
            week.append({"date": d.isoformat(), "count": all_days[d]})
    busiest = max(week, key=lambda r: (r["count"], r["date"]))["date"] if week else None
    out["thanksgiving"] = {
        "date_this_year": tg.isoformat(),
        "days_to": (tg - today).days,
        "last_year_date": ref.isoformat(),
        "last_year_week": week,
        "busiest_date": busiest,
    }
    return out


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_fresh(out_dir: Path | str, now_ts: float, max_age: float = MAX_AGE_SEC) -> bool:
    try:
        meta = json.loads((Path(out_dir) / "tsa.json").read_text(encoding="utf-8"))
        fetched = datetime.strptime(meta["fetched_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (OSError, ValueError, KeyError):
        return False
    return 0 <= (now_ts - fetched) < max_age


def fetch_page(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


PAST_MAX_AGE_SEC = 30 * 86400.0
FIRST_YEAR = 2019
CACHE_SUB = "tsa-cache"


def _read_cached(path: Path, now: float, max_age: float) -> Optional[str]:
    try:
        if 0 <= now - path.stat().st_mtime < max_age:
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return None


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _today_et(now: float) -> date:
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(now, ZoneInfo("America/New_York")).date()


def gather_days(out: Path, now: float, replay: bool, get: Callable[[str], str]) -> dict[date, int]:
    """Current page (always fetched) plus year pages FIRST_YEAR..last year (cached 30 days)."""
    year = datetime.fromtimestamp(now, timezone.utc).year
    days: dict[date, int] = {}
    pages: list[tuple[str, Optional[Path]]] = []
    if replay:
        for y in range(FIRST_YEAR, year + 1):
            f = FIX_DIR / f"tsa-{y}.html"
            if f.is_file():
                days.update(parse_volumes(f.read_text(encoding="utf-8")))
        if not days:
            raise ValueError("no TSA fixtures")
        return days
    for y in range(FIRST_YEAR, year):
        path = out / CACHE_SUB / f"tsa-{y}.html"
        html = _read_cached(path, now, PAST_MAX_AGE_SEC)
        if html is None:
            try:
                html = get(f"{BASE_URL}/{y}")
                if parse_volumes(html):
                    _write_atomic(path, html.encode("utf-8"))
            except Exception:
                try:
                    html = path.read_text(encoding="utf-8")  # stale copy is better than a gap
                except OSError:
                    continue
        days.update(parse_volumes(html))
    # Current page last, so it wins where a year page overlaps.
    days.update(parse_volumes(get(BASE_URL)))
    return days


def maybe_fetch(
    out_dir: Path | str,
    now_ts: Optional[float] = None,
    replay: bool = False,
    fetcher: Optional[Callable[[str], str]] = None,
    attempts: Optional[dict[str, float]] = None,
) -> str:
    """Refresh tsa.json at most once per 6 hours. Returns 'skip' or 'ok'; raises on error."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = time.time() if now_ts is None else now_ts
    if is_fresh(out, now):
        return "skip"
    if attempts is not None:
        last = attempts.get("tsa")
        if last is not None and 0 <= now - last < 900.0:
            return "skip"
        attempts["tsa"] = now
    days = gather_days(out, now, replay, fetcher or fetch_page)
    summary = build_full(days, _today_et(now), _iso(now))
    _write_atomic(out / "tsa.json", json.dumps(summary, indent=2).encode("utf-8"))
    return "ok"
