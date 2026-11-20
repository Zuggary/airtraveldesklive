#!/usr/bin/env python3
"""Build interactive data stories under stories/ (currently /stories/thanksgiving).

Self-updating static story builder (stdlib only).
- Ensures data/tsa-history.json is up to date from TSA daily checkpoint volumes
  (using desk.tsa.parse_volumes and local cached year files in data/tsa-cache/,
  or an explicit --tsa-fixture-dir / --no-fetch fallback for offline tests).
- Reads FAA hourly archive readings from readings/history-summary.json (or a newer
  data/history-summary.json if present) and readings/state.json.
- Computes all story findings, renders static accessible HTML + dual responsive
  inline SVGs (375 px mobile and 1440 px desktop) + accessible HTML tables, and
  embeds both #story-data (for progressive JS interaction) and #trace (machine-
  readable ledger linking every rendered number to its source file and field).

Usage:
  python3 tools/build_stories.py [--data data] [--readings readings] [--out stories]
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk import airports as desk_airports  # noqa: E402
from desk import feeds as desk_feeds  # noqa: E402
from desk import tsa as desk_tsa  # noqa: E402
from tools import build_airport_pages as bap  # noqa: E402

SITE_URL = "https://www.airtraveldesklive.com"
TSA_URL = desk_tsa.BASE_URL
TSA_SOURCE = "TSA checkpoint travel numbers"
TSA_LICENCE = "U.S. government work"
TSA_TERMS = "https://www.usa.gov/government-works"
FAA_SOURCE = "Air Travel Desk hourly archive of FAA NAS status"
FAA_URL = "https://nasstatus.faa.gov/"
FAA_LICENCE = "U.S. government work (FAA feed)"
TSA_MAX_AGE_SEC = 6 * 3600.0
ET_ZONE = ZoneInfo("America/New_York")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
COMPARE_YEARS = [2025, 2024, 2023, 2019]
MOBILE_SHORT_CITY = {
    "SFO": "San Fran",
    "SAN": "San Diego",
    "MIA": "Miami",
    "LGA": "LaGuardia",
    "FLL": "Ft Laud",
    "AUS": "Austin",
    "PHX": "Phoenix",
    "LAS": "Las Vegas",
    "LAX": "Los Ang",
    "MDW": "Midway",
    "DCA": "Reagan",
    "MCO": "Orlando",
    "ORD": "O'Hare",
    "SNA": "John Wayne",
}

SITEMAP_BEGIN = "<!-- stories:begin -->"
SITEMAP_END = "<!-- stories:end -->"


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(iso: Any) -> Optional[datetime]:
    s = str(iso or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _fetch_tsa_html(url: str, timeout: int = 25) -> str:
    """Fetch TSA volumes page via urllib; on macOS LibreSSL AIA failures fall back to curl."""
    req = urllib.request.Request(url, headers={"User-Agent": desk_feeds.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError) and shutil.which("curl"):
            res = subprocess.run(
                ["curl", "-fsSL", "--max-time", str(timeout), "-A", desk_feeds.USER_AGENT, url],
                capture_output=True,
                text=True,
                check=True,
            )
            return res.stdout
        raise


def _parse_fixture_dir(fixture_dir: Path) -> dict[date, int]:
    days: dict[date, int] = {}
    files = sorted(fixture_dir.iterdir())
    matched = [
        p for p in files
        if p.is_file() and re.fullmatch(r"(?:tsa|tsa-story)-(\d{4})\.html", p.name)
    ]
    if not matched:
        raise FileNotFoundError(f"No tsa-YYYY.html or tsa-story-YYYY.html files in {fixture_dir}")
    for path in matched:
        days.update(desk_tsa.parse_volumes(path.read_text(encoding="utf-8")))
    if not days:
        raise ValueError(f"No TSA rows parsed from {fixture_dir}")
    return days


def _build_tsa_payload(all_days: dict[date, int], fetched_utc: str) -> dict[str, Any]:
    if not all_days:
        raise ValueError("No TSA daily rows available")
    sorted_days = sorted(all_days.items())
    latest_d, latest_n = sorted_days[-1]
    record_d = max(all_days, key=lambda d: (all_days[d], d))
    years = sorted({d.year for d in all_days})
    return {
        "source": TSA_SOURCE,
        "url": TSA_URL,
        "licence": TSA_LICENCE,
        "fetched_utc": fetched_utc,
        "latest_date": latest_d.isoformat(),
        "latest_count": latest_n,
        "record_date": record_d.isoformat(),
        "record_count": all_days[record_d],
        "years": years,
        "days": {d.isoformat(): n for d, n in sorted_days},
    }


def _collect_cached_tsa(data_dir: Path, readings_dir: Path) -> tuple[dict[date, int], str]:
    days: dict[date, int] = {}
    cache_dir = data_dir / desk_tsa.CACHE_SUB
    if cache_dir.is_dir():
        for path in sorted(cache_dir.glob("tsa-*.html")):
            days.update(desk_tsa.parse_volumes(path.read_text(encoding="utf-8")))
    best_fetched = ""
    for candidate in (data_dir / "tsa.json", readings_dir / "tsa.json"):
        doc = _read_json(candidate)
        if not doc:
            continue
        f_utc = str(doc.get("fetched_utc") or "")
        if f_utc and (not best_fetched or f_utc > best_fetched):
            best_fetched = f_utc
        for row in doc.get("last7") or []:
            if isinstance(row, dict):
                if row.get("date") and row.get("count") is not None:
                    days[date.fromisoformat(row["date"])] = int(row["count"])
                if row.get("ly_date") and row.get("ly_count") is not None:
                    days[date.fromisoformat(row["ly_date"])] = int(row["ly_count"])
        tg = doc.get("thanksgiving") or {}
        for key in ("this_year_week", "last_year_week"):
            for row in tg.get(key) or []:
                if isinstance(row, dict) and row.get("date") and row.get("count") is not None:
                    days[date.fromisoformat(row["date"])] = int(row["count"])
        if doc.get("latest_date") and doc.get("latest_count") is not None:
            days[date.fromisoformat(doc["latest_date"])] = int(doc["latest_count"])
        if doc.get("ly_date") and doc.get("ly_count") is not None:
            days[date.fromisoformat(doc["ly_date"])] = int(doc["ly_count"])
    return days, best_fetched


def ensure_tsa_history(
    *,
    data_dir: Path,
    readings_dir: Path,
    now_dt: datetime,
    no_fetch: bool = False,
    force_fetch: bool = False,
    fixture_dir: Optional[Path] = None,
    fetcher: Optional[Callable[[str], str]] = None,
) -> tuple[dict[str, Any], str]:
    """Ensure data/tsa-history.json exists and return (payload, relative_path_label)."""
    out_path = data_dir / "tsa-history.json"
    rel_label = _rel_file_label(out_path)

    if fixture_dir is not None:
        days = _parse_fixture_dir(fixture_dir)
        payload = _build_tsa_payload(days, _iso_utc(now_dt))
        _write_atomic(out_path, json.dumps(payload, indent=2) + "\n")
        return payload, rel_label

    existing = _read_json(out_path)
    existing_fetched = _parse_utc(existing.get("fetched_utc"))
    fresh = bool(
        existing
        and existing.get("days")
        and existing_fetched is not None
        and 0 <= (now_dt - existing_fetched).total_seconds() < TSA_MAX_AGE_SEC
    )

    if no_fetch:
        if existing and existing.get("days"):
            return existing, rel_label
        days, best_fetched = _collect_cached_tsa(data_dir, readings_dir)
        payload = _build_tsa_payload(days, best_fetched or _iso_utc(now_dt))
        _write_atomic(out_path, json.dumps(payload, indent=2) + "\n")
        return payload, rel_label

    if fresh and not force_fetch:
        return existing, rel_label

    get_html = fetcher or _fetch_tsa_html
    target_year = now_dt.astimezone(ET_ZONE).year
    days: dict[date, int] = {}
    cache_dir = data_dir / desk_tsa.CACHE_SUB
    now_ts = now_dt.timestamp()
    for y in range(desk_tsa.FIRST_YEAR, target_year):
        cpath = cache_dir / f"tsa-{y}.html"
        html_text: Optional[str] = None
        if cpath.is_file():
            try:
                if 0 <= now_ts - cpath.stat().st_mtime < desk_tsa.PAST_MAX_AGE_SEC:
                    html_text = cpath.read_text(encoding="utf-8")
            except OSError:
                html_text = None
        if html_text is None:
            try:
                fetched_y = get_html(f"{TSA_URL}/{y}")
                if desk_tsa.parse_volumes(fetched_y):
                    _write_atomic(cpath, fetched_y)
                    html_text = fetched_y
            except Exception:
                if cpath.is_file():
                    html_text = cpath.read_text(encoding="utf-8")
        if html_text:
            days.update(desk_tsa.parse_volumes(html_text))

    fetch_ok = False
    try:
        cur_html = get_html(TSA_URL)
        parsed_cur = desk_tsa.parse_volumes(cur_html)
        if parsed_cur:
            days.update(parsed_cur)
            fetch_ok = True
    except Exception as exc:
        print(f"tsa fetch failed, using stored copy ({type(exc).__name__}: {exc})", file=sys.stderr)

    if fetch_ok:
        payload = _build_tsa_payload(days, _iso_utc(now_dt))
        _write_atomic(out_path, json.dumps(payload, indent=2) + "\n")
        return payload, rel_label

    if existing and existing.get("days"):
        return existing, rel_label
    cached_days, best_fetched = _collect_cached_tsa(data_dir, readings_dir)
    if cached_days:
        days.update(cached_days)
    payload = _build_tsa_payload(days, best_fetched or _iso_utc(now_dt))
    _write_atomic(out_path, json.dumps(payload, indent=2) + "\n")
    return payload, rel_label


def _rel_file_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def _choose_faa_files(data_dir: Path, readings_dir: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    """Use readings/history-summary.json (or data/history-summary.json if it covers >= hours and is newer)."""
    r_hist_p = readings_dir / "history-summary.json"
    d_hist_p = data_dir / "history-summary.json"
    r_hist = _read_json(r_hist_p)
    d_hist = _read_json(d_hist_p)
    use_data_hist = False
    if d_hist and d_hist.get("hours"):
        if not r_hist or (
            len(d_hist.get("hours") or []) >= len(r_hist.get("hours") or [])
            and str(d_hist.get("last_reading_utc") or "") > str(r_hist.get("last_reading_utc") or "")
        ):
            use_data_hist = True
    hist_p, hist = (d_hist_p, d_hist) if use_data_hist else (r_hist_p, r_hist)

    r_state_p = readings_dir / "state.json"
    d_state_p = data_dir / "state.json"
    r_state = _read_json(r_state_p)
    d_state = _read_json(d_state_p)
    state_p, state = (r_state_p, r_state) if r_state else (d_state_p, d_state)
    return hist_p, hist, state_p, state


def _fmt_month_day(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}"


def _fmt_month_day_year(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def _count_word(n: int) -> str:
    return {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
    }.get(n, str(n))


def _fmt_et_short(iso_utc: str) -> str:
    dt = _parse_utc(iso_utc)
    if dt is None:
        return ""
    loc = dt.astimezone(ET_ZONE)
    hour = loc.hour % 12 or 12
    ampm = "AM" if loc.hour < 12 else "PM"
    return f"{MONTHS[loc.month - 1]} {loc.day}, {hour}:{loc.minute:02d} {ampm} {loc.tzname() or 'EST'}"


def _fmt_local_hour(iso_utc: str, tz_name: str) -> str:
    dt = _parse_utc(iso_utc)
    if dt is None:
        return ""
    try:
        loc = dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        loc = dt
    hour = loc.hour % 12 or 12
    ampm = "AM" if loc.hour < 12 else "PM"
    return f"{DOW_SHORT[loc.weekday()]} {MONTHS[loc.month - 1]} {loc.day}, {hour}:00 {ampm} {loc.tzname() or 'UTC'}"


class TraceLedger:
    """Tracks every rendered number, date, offset, and percentage for #trace validation."""

    def __init__(
        self,
        *,
        tsa: dict[str, Any],
        tsa_file: str,
        faa_hist: dict[str, Any],
        faa_hist_file: str,
        faa_state: dict[str, Any],
        faa_state_file: str,
    ) -> None:
        self.tsa = tsa
        self.tsa_file = tsa_file
        self.tsa_as_of = str(tsa.get("fetched_utc") or "")
        self.faa_hist = faa_hist
        self.faa_hist_file = faa_hist_file
        self.faa_as_of = str(faa_hist.get("generated_utc") or "")
        self.faa_state = faa_state
        self.faa_state_file = faa_state_file
        self.entries: dict[str, dict[str, Any]] = {}
        self.counter = 0

    def _add(self, key_hint: str, entry: dict[str, Any]) -> str:
        eid = key_hint
        if eid in self.entries:
            existing = self.entries[eid]
            if existing.get("rendered") == entry.get("rendered") and existing.get("value") == entry.get("value"):
                return eid
            self.counter += 1
            eid = f"{key_hint}_{self.counter}"
        self.entries[eid] = entry
        return eid

    def tsa_direct(self, iso_date: str, rendered: Optional[str] = None) -> str:
        val = int(self.tsa["days"][iso_date])
        text = rendered if rendered is not None else f"{val:,}"
        self._add(
            f"tsa_{iso_date}",
            {
                "rendered": text,
                "value": val,
                "op": "direct",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "field": f"days.{iso_date}",
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_millions(self, iso_date: str, suffix: str = " million") -> str:
        raw = int(self.tsa["days"][iso_date])
        val = round(raw / 1_000_000, 2)
        num_str = f"{val:.2f}"
        self._add(
            f"tsa_m_{iso_date}",
            {
                "rendered": num_str,
                "value": val,
                "op": "millions",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "inputs": [f"days.{iso_date}"],
                "args": {"decimals": 2},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return num_str + suffix

    def tsa_sum(self, key: str, dates: list[str], *, as_millions: bool = False, suffix: str = "") -> str:
        inputs = [f"days.{d}" for d in dates]
        total = sum(int(self.tsa["days"][d]) for d in dates)
        if as_millions:
            val = round(total / 1_000_000, 2)
            num_str = f"{val:.2f}"
            self._add(
                f"tsa_sum_m_{key}",
                {
                    "rendered": num_str,
                    "value": val,
                    "op": "millions",
                    "source": TSA_SOURCE,
                    "file": self.tsa_file,
                    "inputs": inputs,
                    "args": {"decimals": 2},
                    "url": TSA_URL,
                    "as_of": self.tsa_as_of,
                },
            )
            return num_str + suffix
        text = f"{total:,}"
        self._add(
            f"tsa_sum_{key}",
            {
                "rendered": text,
                "value": total,
                "op": "sum",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "inputs": inputs,
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text + suffix

    def tsa_diff(self, key: str, dates_a: list[str], dates_b: list[str], signed: bool = True) -> str:
        sum_a = sum(int(self.tsa["days"][d]) for d in dates_a)
        sum_b = sum(int(self.tsa["days"][d]) for d in dates_b)
        diff = sum_a - sum_b
        sign = "+" if signed and diff > 0 else ""
        text = f"{sign}{diff:,}"
        self._add(
            f"tsa_diff_{key}",
            {
                "rendered": text,
                "value": diff,
                "op": "diff",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "args": {"a": [f"days.{d}" for d in dates_a], "b": [f"days.{d}" for d in dates_b]},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_pct(self, key: str, dates_a: list[str], dates_b: list[str], *, signed: bool = True, use_abs: bool = False) -> str:
        sum_a = sum(int(self.tsa["days"][d]) for d in dates_a)
        sum_b = sum(int(self.tsa["days"][d]) for d in dates_b)
        pct = round(((sum_a - sum_b) / sum_b) * 100.0, 1)
        shown = abs(pct) if use_abs else pct
        sign = "+" if signed and not use_abs and shown > 0 else ""
        text = f"{sign}{shown:.1f}%"
        self._add(
            f"tsa_pct_{key}",
            {
                "rendered": text,
                "value": shown,
                "op": "pct_change",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "args": {
                    "a": [f"days.{d}" for d in dates_a],
                    "b": [f"days.{d}" for d in dates_b],
                    "decimals": 1,
                    "abs": use_abs,
                },
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_year(self, yr: int) -> str:
        text = str(yr)
        self._add(
            f"tsa_year_{yr}",
            {
                "rendered": text,
                "value": yr,
                "op": "year_in_history",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "field": "years",
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_date(self, d: date, fmt: str = "short", *, target_year: int) -> str:
        if fmt == "full":
            text = _fmt_month_day_year(d)
        elif fmt == "day":
            text = str(d.day)
        elif fmt == "iso":
            text = d.isoformat()
        elif fmt == "dow_short":
            text = f"{DOW_SHORT[d.weekday()]} {MONTHS[d.month - 1]} {d.day}"
        elif fmt == "dow_full":
            text = f"{DOW_SHORT[d.weekday()]} {MONTHS[d.month - 1]} {d.day}, {d.year}"
        else:
            text = _fmt_month_day(d)
        self._add(
            f"tsa_date_{fmt}_{d.isoformat()}",
            {
                "rendered": text,
                "value": d.isoformat(),
                "op": "corridor_date",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "args": {"date": d.isoformat(), "target_year": target_year, "fmt": fmt},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_offset(self, k: int) -> str:
        text = "T0" if k == 0 else f"T{k:+d}"
        self._add(
            f"tsa_off_{k}",
            {
                "rendered": text,
                "value": k,
                "op": "corridor_offset",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "args": {"offset": k},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_window_count(self, key: str, kind: str, val: int, target_year: int) -> str:
        text = str(val)
        self._add(
            f"tsa_win_{key}",
            {
                "rendered": text,
                "value": val,
                "op": "corridor_meta",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "args": {"kind": kind, "target_year": target_year},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_tick(self, tick_m: float, target_year: int, cmp_years: list[int]) -> str:
        text = "0" if tick_m == 0 else f"{tick_m:.1f}M"
        self._add(
            f"tsa_tick_{tick_m:.1f}",
            {
                "rendered": text,
                "value": tick_m,
                "op": "scale_tick",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "args": {"tick_m": tick_m, "target_year": target_year, "cmp_years": cmp_years},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def tsa_timestamp(self, kind: str = "iso") -> str:
        dt = _parse_utc(self.tsa_as_of)
        if kind == "iso" or dt is None:
            text = self.tsa_as_of
        elif kind == "et_short":
            text = _fmt_et_short(self.tsa_as_of)
        else:
            text = _fmt_month_day_year(dt.astimezone(ET_ZONE).date())
        self._add(
            f"tsa_ts_{kind}",
            {
                "rendered": text,
                "value": self.tsa_as_of,
                "op": "timestamp_view",
                "source": TSA_SOURCE,
                "file": self.tsa_file,
                "field": "fetched_utc",
                "args": {"kind": kind},
                "url": TSA_URL,
                "as_of": self.tsa_as_of,
            },
        )
        return text

    def faa_meta_num(self, key: str, kind: str, val: int) -> str:
        text = f"{val:,}"
        self._add(
            f"faa_{key}",
            {
                "rendered": text,
                "value": val,
                "op": "hist_canonical_counts",
                "source": FAA_SOURCE,
                "file": self.faa_hist_file,
                "args": {"kind": kind, "state_file": self.faa_state_file},
                "url": FAA_URL,
                "as_of": self.faa_as_of,
            },
        )
        return text

    def faa_ap_stat(self, code: str, kind: str, val: Any, rendered: Optional[str] = None) -> str:
        text = rendered if rendered is not None else (f"{val:.1f}%" if kind == "share_pct" else str(val))
        self._add(
            f"faa_ap_{code}_{kind}",
            {
                "rendered": text,
                "value": val,
                "op": "hist_airport",
                "source": FAA_SOURCE,
                "file": self.faa_hist_file,
                "args": {"code": code, "kind": kind},
                "url": FAA_URL,
                "as_of": self.faa_as_of,
            },
        )
        return text

    def faa_tick(self, tick: int) -> str:
        text = str(tick)
        self._add(
            f"faa_tick_{tick}",
            {
                "rendered": text,
                "value": tick,
                "op": "hist_tick",
                "source": FAA_SOURCE,
                "file": self.faa_hist_file,
                "field": "hours",
                "args": {"tick": tick},
                "url": FAA_URL,
                "as_of": self.faa_as_of,
            },
        )
        return text

    def faa_timestamp(self, field: str, iso_val: str, kind: str = "iso") -> str:
        dt = _parse_utc(iso_val)
        if kind == "iso" or dt is None:
            text = iso_val
        elif kind == "et_short":
            text = _fmt_et_short(iso_val)
        elif kind == "date_short":
            text = _fmt_month_day(dt.astimezone(ET_ZONE).date())
        elif kind == "date_full":
            text = _fmt_month_day_year(dt.astimezone(ET_ZONE).date())
        else:
            text = iso_val
        self._add(
            f"faa_ts_{field}_{kind}",
            {
                "rendered": text,
                "value": iso_val,
                "op": "timestamp_view",
                "source": FAA_SOURCE,
                "file": self.faa_hist_file,
                "field": field,
                "args": {"kind": kind},
                "url": FAA_URL,
                "as_of": self.faa_as_of,
            },
        )
        return text


def _target_thanksgiving_year(tsa: dict[str, Any], now_dt: datetime) -> int:
    latest_iso = str(tsa.get("latest_date") or "")
    ref_day = date.fromisoformat(latest_iso) if latest_iso else now_dt.astimezone(ET_ZONE).date()
    tg = desk_tsa.thanksgiving(ref_day.year)
    if (ref_day - tg).days > 4:
        return ref_day.year + 1
    return ref_day.year


def _merge_faa_rows(hist: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    hours = list(hist.get("hours") or [])
    n_hours = len(hours)
    merged = bap._history_rows(hist.get("airports") or {}, n_hours)

    # Identify airports whose entire archive window is "s" AND state.json lists a closure event.
    closure_codes: set[str] = set()
    for ev in state.get("events") or []:
        if isinstance(ev, dict) and ev.get("kind") == "closure":
            c = desk_airports.canonical_code(ev.get("airport"))
            if c:
                closure_codes.add(c)

    rows: list[dict[str, Any]] = []
    clear_codes: list[str] = []
    for code, strip in sorted(merged.items()):
        d_cnt = strip.count("d")
        s_cnt = strip.count("s")
        c_cnt = strip.count("c")
        m_cnt = strip.count("-")
        nc_cnt = d_cnt + s_cnt
        is_closure_listing = (nc_cnt == n_hours and s_cnt == n_hours and code in closure_codes)
        first_idx = next((i for i, ch in enumerate(strip) if ch in ("d", "s")), None)
        tz = desk_airports.TZ.get(code, "America/New_York")
        first_utc = hours[first_idx] if first_idx is not None else ""
        first_local = _fmt_local_hour(first_utc, tz) if first_utc else ""
        if nc_cnt == 0:
            clear_codes.append(code)
            continue
        rows.append({
            "code": code,
            "name": desk_airports.display(code),
            "short": desk_airports.SHORT.get(code, code),
            "city": desk_airports.CITY.get(code, ""),
            "tz": tz,
            "strip": strip,
            "d": d_cnt,
            "s": s_cnt,
            "c": c_cnt,
            "missing": m_cnt,
            "non_clear": nc_cnt,
            "share_pct": round((nc_cnt / n_hours) * 100.0, 1) if n_hours else 0.0,
            "is_closure_listing": is_closure_listing,
            "first_idx": first_idx,
            "first_utc": first_utc,
            "first_local": first_local,
        })

    op_rows = [r for r in rows if not r["is_closure_listing"]]
    closure_rows = [r for r in rows if r["is_closure_listing"]]
    op_rows.sort(key=lambda r: (-r["non_clear"], -r["s"], r["code"]))
    closure_rows.sort(key=lambda r: r["code"])

    hour_list: list[dict[str, Any]] = []
    for i, hr in enumerate(hours):
        op_active = sum(1 for r in op_rows if r["strip"][i] in ("d", "s"))
        all_active = sum(1 for r in rows if r["strip"][i] in ("d", "s"))
        hour_list.append({
            "idx": i,
            "utc": hr,
            "et": _fmt_et_short(hr),
            "op_active": op_active,
            "all_active": all_active,
        })
    peak_hr = max(hour_list, key=lambda h: (h["op_active"], -h["idx"])) if hour_list else {"idx": 0, "utc": "", "et": "", "op_active": 0, "all_active": 0}

    clear_missing_counts = [
        merged[c].count("-") for c in clear_codes
    ]
    clear_missing_min = min(clear_missing_counts) if clear_missing_counts else 0
    clear_missing_max = max(clear_missing_counts) if clear_missing_counts else 0

    return {
        "hours": hour_list,
        "n_hours": n_hours,
        "days_span": round(n_hours / 24.0, 1) if n_hours else 0.0,
        "canonical_total": len(merged),
        "op_rows": op_rows,
        "closure_rows": closure_rows,
        "all_rows": op_rows + closure_rows,
        "clear_count": len(clear_codes),
        "clear_codes": clear_codes,
        "clear_missing_min": clear_missing_min,
        "clear_missing_max": clear_missing_max,
        "stops_op_count": sum(1 for r in op_rows if r["s"] > 0),
        "peak_hr": peak_hr,
        "rows_total": int(hist.get("rows") or sum(len(s.replace("-", "")) for s in merged.values())),
        "first_reading_utc": str(hist.get("first_reading_utc") or (hours[0] if hours else "")),
        "last_reading_utc": str(hist.get("last_reading_utc") or (hours[-1] if hours else "")),
        "generated_utc": str(hist.get("generated_utc") or ""),
    }


def _header() -> str:
    return "\n".join([
        '  <a class="skip-link" href="#main-content">Skip to main content</a>',
        '  <header class="site-header">',
        '    <div class="header-in">',
        '      <a class="brand" href="/">',
        '        <img class="brand-logo" src="/brand/logo.svg" width="30" height="30" alt="">',
        '        <span class="brand-title">Air Travel Desk</span>',
        '      </a>',
        '      <nav class="header-nav" aria-label="Site navigation">',
        '        <a class="chip nav-wide" href="/">Live board</a>',
        '        <a class="chip" href="/airports/">Airports</a>',
        '        <a class="chip nav-wide" href="/airlines/">Airlines</a>',
        '        <a class="chip" href="/stuck">Stuck?</a>',
        '        <a class="chip" href="/help/">Help</a>',
        '        <a class="chip nav-wide" href="/about">About</a>',
        '      </nav>',
        '      ' + bap.THEME_BUTTON,
        '    </div>',
        '  </header>',
    ])


def _footer() -> str:
    return "\n".join([
        '  <footer class="site-footer">',
        '    <p class="container small"><a href="https://www.youtube.com/@AirTravelDeskLive/live">Watch on YouTube</a> · <a href="https://www.twitch.tv/airtraveldesklive">Also on Twitch</a></p>',
        '    <div class="container foot-grid">',
        '      <div class="foot-col">',
        '        <h2>Air Travel Desk</h2>',
        '        <p>Updated automatically from public data. Not affiliated with any airline or government agency.</p>',
        '        <p>Contact: <a class="tap" href="mailto:hello@airtraveldesklive.com">hello@airtraveldesklive.com</a></p>',
        '      </div>',
        '      <nav class="foot-links" aria-label="Footer">',
        '        <a class="tap" href="/airports/">Airports</a>',
        '        <a class="tap" href="/airlines/">Airline commitments</a>',
        '        <a class="tap" href="/stuck">I\'m stuck guide</a>',
        '        <a class="tap" href="/stories/">Data stories</a>',
        '        <a class="tap" href="/about">About</a>',
        '        <a class="tap" href="/help/">Help</a>',
        '        <a class="tap" href="/sources">Data and sources</a>',
        '        <a class="tap" href="/privacy">Privacy</a>',
        '      </nav>',
        '    </div>',
        '    <div class="container fine">',
        '      <p>Data: TSA checkpoint travel numbers, FAA NAS status archive. <a class="tap" href="/sources">Every source and its age</a>.</p>',
        '    </div>',
        '  </footer>',
    ])


def _strip_tags_text(fragment: str) -> str:
    txt = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", txt).strip()


def verify_story_numbers(
    html_doc: str,
    *,
    tsa: dict[str, Any],
    faa: dict[str, Any],
    target_year: int,
) -> None:
    """Validate every 'vs' baseline comparison and every tally sum against source data."""
    m_main = re.search(r"<main\b[^>]*>(.*?)</main>", html_doc, re.S)
    if not m_main:
        raise ValueError("Story HTML missing <main>")
    main_raw = m_main.group(1)
    main_clean = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>|<!--.*?-->", " ", main_raw, flags=re.S)

    details_blocks = re.findall(r"<details\b[^>]*>.*?</details>", main_clean, flags=re.S)
    prose_html = re.sub(r"<details\b[^>]*>.*?</details>", " ", main_clean, flags=re.S)

    # 1) Build TSA reference tables from tsa["days"]
    days_map = {str(k): int(v) for k, v in (tsa.get("days") or {}).items()}
    years_in_tsa = sorted({int(y) for y in (tsa.get("years") or [])} | {int(k[:4]) for k in days_map})
    valid_vals_by_yr: dict[int, set[int]] = {y: set() for y in years_in_tsa}
    aligned_pairs: dict[tuple[int, int], set[tuple[int, int]]] = {}
    same_year_pairs: dict[int, set[tuple[int, int]]] = {}

    for y in years_in_tsa:
        y_dates = sorted(k for k in days_map if k.startswith(f"{y}-"))
        y_objs = [date.fromisoformat(d) for d in y_dates]
        for i, d_obj in enumerate(y_objs):
            valid_vals_by_yr[y].add(days_map[y_dates[i]])
            for j in range(i + 2, min(len(y_dates) + 1, i + 32)):
                if (y_objs[j - 1] - d_obj).days == j - i - 1:
                    valid_vals_by_yr[y].add(sum(days_map[y_dates[k]] for k in range(i, j)))
        tg_y = desk_tsa.thanksgiving(y)
        corr_y = [days_map[(tg_y + timedelta(days=k)).isoformat()] for k in range(-11, 5) if (tg_y + timedelta(days=k)).isoformat() in days_map]
        s_pairs = same_year_pairs.setdefault(y, set())
        for a_val in corr_y:
            for b_val in corr_y:
                s_pairs.add((a_val, b_val))

    tg_target = desk_tsa.thanksgiving(target_year)
    t_dates = sorted(k for k in days_map if k.startswith(f"{target_year}-"))
    t_objs = [date.fromisoformat(d) for d in t_dates]
    for y_cmp in years_in_tsa:
        if y_cmp >= target_year:
            continue
        delta_days = (tg_target - desk_tsa.thanksgiving(y_cmp)).days
        p_set = aligned_pairs.setdefault((target_year, y_cmp), set())
        for i, d_obj in enumerate(t_objs):
            for j in range(i + 1, min(len(t_dates) + 1, i + 32)):
                if (t_objs[j - 1] - d_obj).days != j - i - 1:
                    break
                cmp_slice = [(t_objs[k] - timedelta(days=delta_days)).isoformat() for k in range(i, j)]
                if all(cd in days_map for cd in cmp_slice):
                    sa = sum(days_map[t_dates[k]] for k in range(i, j))
                    sb = sum(days_map[cd] for cd in cmp_slice)
                    p_set.add((sa, sb))

    # 2) Extract prose blocks (<h1..6>, <p>, <li>, <output>) and check every "vs" comparison
    blocks = [_strip_tags_text(inner) for _, inner in re.findall(r"<(h[1-6]|p|li|output)\b[^>]*>(.*?)</\1>", prose_html, flags=re.S)]
    all_aligned = set().union(*aligned_pairs.values()) if aligned_pairs else set()
    all_same_yr = set().union(*same_year_pairs.values()) if same_year_pairs else set()

    for txt in blocks:
        if not txt:
            continue
        # Reject ambiguous/inverted single-number parenthetical after "vs YYYY"
        for m in re.finditer(r"([+-]?\d+(?:\.\d+)?%)\s+vs\.?\s+((?:19|20)\d{2})\s*\(\s*([\d,]+)\s*\)", txt, flags=re.I):
            raise ValueError(f"Ambiguous 'vs {m.group(2)}' comparison without explicit baseline: {m.group(0)!r}")

        # Verify explicit "<A> ... vs <B> in <YYYY> (<pct>%)"
        ro_matched_spans: list[tuple[int, int]] = []
        for m in re.finditer(
            r"([\d,]{4,})\s+in\s+((?:19|20)\d{2})\s*\(\s*([+-]?[\d,]+)\s*,\s*([+-]?\d+(?:\.\d+)?)%\s+vs\.?\s+((?:19|20)\d{2})\s*\)",
            txt,
            flags=re.I,
        ):
            ro_matched_spans.append(m.span())
            val_a = int(m.group(1).replace(",", ""))
            yr_a = int(m.group(2))
            diff_v = int(m.group(3).replace(",", ""))
            pct_v = float(m.group(4))
            yr_b = int(m.group(5))
            val_b = val_a - diff_v
            if (val_a, val_b) not in aligned_pairs.get((yr_a, yr_b), set()):
                raise ValueError(f"Readout vs baseline mismatch for {yr_a} vs {yr_b}: {m.group(0)!r}")
            exp_pct = round((diff_v / val_b) * 100.0, 1)
            if exp_pct != pct_v:
                raise ValueError(f"Readout percentage mismatch: {pct_v}% != {exp_pct}% in {m.group(0)!r}")

        for m in re.finditer(
            r"([\d,]{4,})\b[^.;()]{0,70}?\bvs\.?\s+([\d,]{4,})\s+in\s+((?:19|20)\d{2})(?:\s*\(\s*([+-]?\d+(?:\.\d+)?)%\s*\))?",
            txt,
            flags=re.I,
        ):
            val_a = int(m.group(1).replace(",", ""))
            val_b = int(m.group(2).replace(",", ""))
            yr_b = int(m.group(3))
            if (val_a, val_b) not in aligned_pairs.get((target_year, yr_b), set()):
                raise ValueError(f"TSA vs baseline mismatch for {target_year} vs {yr_b}: {m.group(0)!r}")
            if m.group(4) is not None:
                pct_v = float(m.group(4))
                exp_pct = round(((val_a - val_b) / val_b) * 100.0, 1)
                if exp_pct != pct_v:
                    raise ValueError(f"TSA vs percentage mismatch: {pct_v}% != {exp_pct}% in {m.group(0)!r}")

        for m in re.finditer(
            r"([\d,]{4,})\s+vs\.?\s+([\d,]{4,})(?!\s+in\s+(?:19|20)\d{2})(?:\s*\(\s*([+-]?\d+(?:\.\d+)?)%\s*\))?",
            txt,
            flags=re.I,
        ):
            val_a = int(m.group(1).replace(",", ""))
            val_b = int(m.group(2).replace(",", ""))
            if (val_a, val_b) not in all_aligned and (val_a, val_b) not in all_same_yr:
                raise ValueError(f"Unverified vs pair {m.group(0)!r} in {txt!r}")
            if m.group(3) is not None:
                pct_v = float(m.group(3))
                exp_pct = round(((val_a - val_b) / val_b) * 100.0, 1)
                if exp_pct != pct_v:
                    raise ValueError(f"TSA vs percentage mismatch: {pct_v}% != {exp_pct}% in {m.group(0)!r}")

    # 3) Verify Table 1 TSA <details> rows
    for blk in details_blocks:
        if "Daily TSA checkpoint counts" not in blk:
            continue
        hdr_yrs = [int(y) for y in re.findall(r'<th scope="col" class="num">((?:19|20)\d{2})</th>', blk)]
        for tr in re.findall(r"<tbody>(.*?)</tbody>", blk, flags=re.S):
            for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", tr, flags=re.S):
                tds = [_strip_tags_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)]
                if len(tds) < 3:
                    continue
                if re.fullmatch(r"[\d,]+", tds[0]) and re.fullmatch(r"[\d,]+", tds[1]):
                    va = int(tds[0].replace(",", ""))
                    vb = int(tds[1].replace(",", ""))
                    if (va, vb) not in aligned_pairs.get((target_year, hdr_yrs[1]), set()):
                        raise ValueError(f"Table 1 TSA pair mismatch: {va} vs {vb}")
                    m_diff = re.fullmatch(r"([+-]?[\d,]+)\s*\(\s*([+-]?\d+(?:\.\d+)?)%\s*\)", tds[-1])
                    if not m_diff:
                        raise ValueError(f"Table 1 missing diff/pct cell: {tds[-1]!r}")
                    dv = int(m_diff.group(1).replace(",", ""))
                    pv = float(m_diff.group(2))
                    if dv != va - vb or round((dv / vb) * 100.0, 1) != pv:
                        raise ValueError(f"Table 1 diff/pct mismatch: {tds[-1]!r} vs {va}-{vb}")

    # 4) Verify FAA underlying tallies and every rendered airport/check tally
    canon = int(faa["canonical_total"])
    n_hours = int(faa["n_hours"])
    if len(faa["op_rows"]) + len(faa["closure_rows"]) + int(faa["clear_count"]) != canon:
        raise ValueError("FAA canonical airport partition does not sum to canonical_total")
    for r in faa["all_rows"]:
        if r["d"] + r["s"] != r["non_clear"]:
            raise ValueError(f"FAA airport {r['code']} delay+stop != non_clear")
        if r["non_clear"] + r["c"] + r["missing"] != n_hours:
            raise ValueError(f"FAA airport {r['code']} status+missing != n_hours")

    clos_codes = [r["code"] for r in faa["closure_rows"]]
    for txt in blocks:
        if not txt:
            continue
        # Airport partition tallies in any block citing "X of <canon>"
        if re.search(rf"\b\d+\s+of\s+{canon}\b", txt) and ("clear" in txt.lower() or "closed" in txt.lower() or "closure" in txt.lower()):
            m_op_of = re.search(rf"\b(\d+)\s+of\s+{canon}\b(?!\s+(?:monitored\s+(?:US\s+)?)?airports\s+stayed\s+clear)", txt, flags=re.I)
            m_op_had = re.search(r"\b(\d+)\s+(?:airports\s+)?had\s+(?:flight-delay|operational|delays)", txt, flags=re.I)
            m_clear = re.search(rf"\b(\d+)\s+(?:of\s+{canon}\s+(?:monitored\s+(?:US\s+)?)?airports\s+)?(?:stayed\s+)?clear\b", txt, flags=re.I)
            m_closed = re.search(r"\b(\d+)\s+(?:closed|carried\s+a\s+closure|closure\s+listing)", txt, flags=re.I)
            parts: list[int] = []
            if m_op_of:
                parts.append(int(m_op_of.group(1)))
            elif m_op_had:
                parts.append(int(m_op_had.group(1)))
            if m_clear:
                parts.append(int(m_clear.group(1)))
            if m_closed:
                parts.append(int(m_closed.group(1)))
            if len(parts) < 2 or sum(parts) != canon:
                raise ValueError(f"FAA tally {parts} does not sum to {canon} in {txt!r}")
            for cc in clos_codes:
                if cc not in txt:
                    raise ValueError(f"FAA tally sentence missing closure airport code {cc!r}: {txt!r}")

        # Hourly check breakdown in readout
        m_chk = re.search(r"\b(\d+)\s+non-clear\s+hourly\s+checks.*?\b(\d+)\s+delay,\s*(\d+)\s+stop", txt, flags=re.I)
        if m_chk:
            nc_v, d_v, s_v = int(m_chk.group(1)), int(m_chk.group(2)), int(m_chk.group(3))
            if d_v + s_v != nc_v:
                raise ValueError(f"FAA check breakdown {d_v} + {s_v} != {nc_v} in {txt!r}")

    # 5) Verify Table 2 FAA <details> rows sum to canonical_total and n_hours
    for blk in details_blocks:
        if "FAA NAS status hourly checks" not in blk:
            continue
        ap_sum = 0
        for tbody in re.findall(r"<tbody>(.*?)</tbody>", blk, flags=re.S):
            for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, flags=re.S):
                th_txt = _strip_tags_text((re.search(r"<th[^>]*>(.*?)</th>", row_html, flags=re.S) or ("", ""))[1]) if re.search(r"<th[^>]*>(.*?)</th>", row_html, flags=re.S) else ""
                tds = [_strip_tags_text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)]
                if len(tds) < 6:
                    continue
                d_v, s_v, nc_v, _, c_v = int(tds[0]), int(tds[1]), int(tds[2]), tds[3], int(tds[4])
                if d_v + s_v != nc_v:
                    raise ValueError(f"Table 2 FAA row {th_txt!r}: {d_v}+{s_v} != {nc_v}")
                m_rem = re.search(r"Remaining\s+(\d+)\s+airports", th_txt)
                if m_rem:
                    ap_sum += int(m_rem.group(1))
                    if nc_v != 0 or c_v != n_hours:
                        raise ValueError(f"Table 2 clear row invalid counts: {tds}")
                else:
                    ap_sum += 1
                    m_v = int(tds[5])
                    if nc_v + c_v + m_v != n_hours:
                        raise ValueError(f"Table 2 FAA row {th_txt!r}: {nc_v}+{c_v}+{m_v} != {n_hours}")
        if ap_sum != canon:
            raise ValueError(f"Table 2 FAA airport count {ap_sum} != {canon}")


_MONTH_RE = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_TS_ET_RANGE_RE = re.compile(
    rf"\b({_MONTH_RE}\s+\d{{1,2}},\s*\d{{1,2}}:\d{{2}}\s*(?:AM|PM)\s+[A-Z]{{2,4}})\s+(?:to|[-\u2013\u2014])\s+"
    rf"({_MONTH_RE}\s+\d{{1,2}},\s*\d{{1,2}}:\d{{2}}\s*(?:AM|PM)\s+[A-Z]{{2,4}})\b"
)
_DATE_RANGE_TWO_RE = re.compile(
    rf"\b({_MONTH_RE})\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\s+(?:to|[-\u2013\u2014])\s+"
    rf"({_MONTH_RE})\s+(\d{{1,2}})(?:,\s*(\d{{4}}))?\b"
)
_DATE_RANGE_SHORT_RE = re.compile(
    rf"\b({_MONTH_RE})\s+(\d{{1,2}})\s*[-\u2013\u2014]\s*(\d{{1,2}})(?:,\s*(\d{{4}}))?\b"
)


def _parse_month_day_date(mon_name: str, day_str: str, yr: int) -> date:
    m_num = MONTHS.index(mon_name[:3].capitalize()) + 1
    return date(yr, m_num, int(day_str))


def _extract_id_section(html_doc: str, section_id: str) -> str:
    m = re.search(rf'<section\b[^>]*\bid="{re.escape(section_id)}"[^>]*>(.*?)</section>', html_doc, re.S)
    return m.group(1) if m else ""


def _extract_svg_by_id(html_doc: str, svg_id: str) -> str:
    m = re.search(rf'<svg\b[^>]*\bid="{re.escape(svg_id)}"[^>]*>(.*?)</svg>', html_doc, re.S)
    return m.group(1) if m else ""


def verify_story_date_windows(
    html_doc: str,
    *,
    tsa: dict[str, Any],
    faa_hist: dict[str, Any],
    target_year: int,
) -> None:
    """Validate that headline comparison scope and every rendered date window match the source data files."""
    hours = list(faa_hist.get("hours") or [])
    if not hours:
        raise ValueError("FAA history missing hours list")
    first_dt = _parse_utc(hours[0])
    last_dt = _parse_utc(hours[-1])
    if first_dt is None or last_dt is None:
        raise ValueError("Invalid FAA hours boundary timestamp")
    if faa_hist.get("first_reading_utc") and _parse_utc(faa_hist["first_reading_utc"]) != first_dt:
        raise ValueError("FAA first_reading_utc does not match hours[0]")
    if faa_hist.get("last_reading_utc") and _parse_utc(faa_hist["last_reading_utc"]) != last_dt:
        raise ValueError("FAA last_reading_utc does not match hours[-1]")

    faa_start_et = _fmt_et_short(hours[0])
    faa_end_et = _fmt_et_short(hours[-1])

    days_map = {str(k): int(v) for k, v in (tsa.get("days") or {}).items()}
    if not days_map:
        raise ValueError("TSA history missing days")
    max_tsa_iso = max(days_map)
    if str(tsa.get("latest_date") or "") != max_tsa_iso:
        raise ValueError(f"TSA latest_date {tsa.get('latest_date')!r} != max(days) {max_tsa_iso!r}")

    latest_d = date.fromisoformat(max_tsa_iso)
    trail7_dates = [
        latest_d - timedelta(days=k)
        for k in range(6, -1, -1)
        if (latest_d - timedelta(days=k)).isoformat() in days_map
    ]
    trail7_start, trail7_end = trail7_dates[0], trail7_dates[-1]

    tg_now = desk_tsa.thanksgiving(target_year)
    corr_dates = [tg_now + timedelta(days=k) for k in range(-11, 5)]
    corr_start, corr_end = corr_dates[0], corr_dates[-1]
    core_dates = [tg_now + timedelta(days=k) for k in range(-4, 5)]
    core_start, core_end = core_dates[0], core_dates[-1]
    counted_corr = [d for d in corr_dates if d.isoformat() in days_map]
    uncounted_corr = [d for d in corr_dates if d.isoformat() not in days_map]
    counted_core = [d for d in core_dates if d.isoformat() in days_map]
    counted_corr_offsets = [(d - tg_now).days for d in counted_corr]
    years_in_tsa = sorted({int(y) for y in (tsa.get("years") or [])} | {int(k[:4]) for k in days_map})

    # 1) Verify H1, <title>, and <meta name="description"> declare an exact comparison window matching TSA data
    m_h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_doc, re.S)
    m_title = re.search(r"<title>(.*?)</title>", html_doc, re.S)
    m_desc = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html_doc, re.S)
    if not m_h1 or not m_title or not m_desc:
        raise ValueError("Story HTML missing h1, title, or meta description")
    h1_txt = _strip_tags_text(m_h1.group(1))
    title_txt = _strip_tags_text(m_title.group(1))
    desc_txt = html.unescape(m_desc.group(1)).strip()

    if re.search(r"\b(?:19|20)\d{2}\s+is\s+[+-]?\d+(?:\.\d+)?%\s+on\s+(?:19|20)\d{2}\b", h1_txt):
        raise ValueError(f"Unscoped year-over-year H1 without explicit window: {h1_txt!r}")

    if len(counted_core) == 0:
        n_word = _count_word(len(trail7_dates))
        scope_pat = re.compile(
            rf"\b{re.escape(n_word)}\s+days\s+ending\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*"
            rf"({_MONTH_RE})\s+(\d{{1,2}}),\s*(\d{{4}})\s+versus\s+the\s+same\s+{re.escape(n_word)}\s+days\s+in\s+(\d{{4}})\b",
            flags=re.I,
        )
        for lbl, txt in (("h1", h1_txt), ("title", title_txt), ("meta description", desc_txt)):
            ms = scope_pat.search(txt)
            if not ms:
                raise ValueError(f"Headline/metadata ({lbl}) missing explicit {n_word}-day comparison scope: {txt!r}")
            end_d = _parse_month_day_date(ms.group(1), ms.group(2), int(ms.group(3)))
            if end_d != trail7_end:
                raise ValueError(f"Headline/metadata ({lbl}) end date {end_d} != TSA latest date {trail7_end}")
    else:
        exp_start, exp_end = counted_core[0], counted_core[-1]
        for lbl, txt in (("h1", h1_txt), ("title", title_txt), ("meta description", desc_txt)):
            mr = _DATE_RANGE_TWO_RE.search(txt)
            if not mr:
                raise ValueError(f"Holiday headline/metadata ({lbl}) missing explicit date range: {txt!r}")
            yr2 = int(mr.group(6) or target_year)
            yr1 = int(mr.group(3) or yr2)
            d1 = _parse_month_day_date(mr.group(1), mr.group(2), yr1)
            d2 = _parse_month_day_date(mr.group(4), mr.group(5), yr2)
            if (d1, d2) != (exp_start, exp_end):
                raise ValueError(f"Holiday headline/metadata ({lbl}) window {(d1, d2)} != {(exp_start, exp_end)}")

    # 2) Verify #delays (FAA section) prose, tables, and both SVG timelines match exact EST/EDT endpoints
    delays_sec = _extract_id_section(html_doc, "delays")
    if not delays_sec:
        raise ValueError("Story HTML missing #delays section")
    for svg_id in ("delay-svg-desktop", "delay-svg-mobile"):
        svg_body = _extract_svg_by_id(delays_sec, svg_id)
        if not svg_body:
            raise ValueError(f"Missing #{svg_id} inside #delays")
        ticks = [_strip_tags_text(x) for x in re.findall(r'<text\b[^>]*class="[^"]*\bsv-date-tick\b[^"]*"[^>]*>(.*?)</text>', svg_body, flags=re.S)]
        if len(ticks) < 2 or ticks[0] != faa_start_et or ticks[-1] != faa_end_et:
            raise ValueError(f"#{svg_id} timeline endpoints {ticks!r} != {[faa_start_et, faa_end_et]!r}")

    delays_non_svg = re.sub(r"<script.*?</script>|<style.*?</style>|<svg.*?</svg>|<!--.*?-->", " ", delays_sec, flags=re.S)
    delays_text = _strip_tags_text(delays_non_svg)
    ts_ranges = _TS_ET_RANGE_RE.findall(delays_text)
    if not ts_ranges:
        raise ValueError("FAA #delays section missing exact timestamped window")
    for s_ts, e_ts in ts_ranges:
        if (s_ts, e_ts) != (faa_start_et, faa_end_et):
            raise ValueError(f"FAA #delays timestamp window {(s_ts, e_ts)!r} != {(faa_start_et, faa_end_et)!r}")
    delays_stripped = _TS_ET_RANGE_RE.sub(" ", delays_text)
    for bad_pat in (_DATE_RANGE_TWO_RE, _DATE_RANGE_SHORT_RE):
        bad_m = bad_pat.search(delays_stripped)
        if bad_m:
            raise ValueError(f"Inconsistent/unqualified date range {bad_m.group(0)!r} inside #delays; expected exact window {faa_start_et} to {faa_end_et}")

    # 3) Verify EVERY date range in <main> outside #delays matches its dataset's exact start & end
    m_main = re.search(r"<main\b[^>]*>(.*?)</main>", html_doc, re.S)
    if not m_main:
        raise ValueError("Story HTML missing <main>")
    main_html = m_main.group(1)
    main_no_delays = re.sub(r'<section\b[^>]*\bid="delays"[^>]*>.*?</section>', " ", main_html, flags=re.S)
    main_no_scripts = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ", main_no_delays, flags=re.S)

    blocks = [
        _strip_tags_text(inner)
        for _, inner in re.findall(r"<(h[1-6]|p|li|output|summary|caption|text)\b[^>]*>(.*?)</\1>", main_no_scripts, flags=re.S)
    ]

    def _check_tsa_range(d1: date, d2: date, ctx_before: str, ctx_after: str, full_blk: str, raw_match: str) -> None:
        local = f"{ctx_before} {ctx_after}".lower()
        fb = full_blk.lower()
        if "awaiting tsa" in ctx_after.lower() or "awaiting tsa" in local:
            if not uncounted_corr:
                raise ValueError(f"Unexpected awaiting-TSA range {raw_match!r} when all corridor days are counted")
            exp = (uncounted_corr[0], uncounted_corr[-1])
        elif "7 days" in ctx_before.lower() or ("7 days" in local and "corridor" not in local):
            exp = (trail7_start, trail7_end)
        elif re.search(r"first\s+\d+\s+corridor\s+days", ctx_before.lower()):
            if not counted_corr:
                raise ValueError(f"Unexpected counted-corridor range {raw_match!r} with 0 counted days")
            exp = (counted_corr[0], counted_corr[-1])
        elif re.search(r"\bof\s+\d+\s+holiday\s+days\b", local) or re.search(r"\bof\s+\d+\s+holiday\s+days\b", fb):
            if not counted_core:
                raise ValueError(f"Unexpected counted-core range {raw_match!r} with 0 core days")
            exp = (counted_core[0], counted_core[-1])
        elif "core" in ctx_before.lower() or "thanksgiving week" in ctx_before.lower() or "holiday week" in ctx_before.lower():
            exp = (core_start, core_end)
        elif (
            "16-day" in ctx_before.lower()
            or "16 days" in ctx_before.lower()
            or "corridor" in ctx_before.lower()
            or "aligned by days to thanksgiving" in ctx_before.lower()
            or "daily tsa checkpoint counts" in ctx_before.lower()
        ):
            exp = (corr_start, corr_end)
        else:
            raise ValueError(f"Unclassified date range {raw_match!r} in block {full_blk!r}")
        if (d1, d2) != exp:
            raise ValueError(f"Date range {raw_match!r} resolved to {(d1, d2)}, expected {exp} in {full_blk!r}")

    for blk in blocks:
        if not blk:
            continue
        # Reject any stray timestamped range outside #delays
        for m in _TS_ET_RANGE_RE.finditer(blk):
            if (m.group(1), m.group(2)) != (faa_start_et, faa_end_et):
                raise ValueError(f"Timestamp range {(m.group(1), m.group(2))!r} outside #delays does not match FAA window")
        cleaned = _TS_ET_RANGE_RE.sub(" ", blk)

        last_end = 0
        for m in _DATE_RANGE_TWO_RE.finditer(cleaned):
            yr2 = int(m.group(6) or target_year)
            yr1 = int(m.group(3) or yr2)
            d1 = _parse_month_day_date(m.group(1), m.group(2), yr1)
            d2 = _parse_month_day_date(m.group(4), m.group(5), yr2)
            if d1 > d2 and not m.group(3):
                d1 = _parse_month_day_date(m.group(1), m.group(2), yr2 - 1)
            slice_before = cleaned[last_end:m.start()]
            ctx_before = slice_before.split(";")[-1]
            ctx_after = cleaned[m.end():].split(";")[0]
            _check_tsa_range(d1, d2, ctx_before, ctx_after, blk, m.group(0))
            last_end = m.end()

        for m in _DATE_RANGE_SHORT_RE.finditer(cleaned):
            yr = int(m.group(4) or target_year)
            d1 = _parse_month_day_date(m.group(1), m.group(2), yr)
            d2 = _parse_month_day_date(m.group(1), m.group(3), yr)
            ctx_before = cleaned[:m.start()].split(";")[-1]
            ctx_after = cleaned[m.end():].split(";")[0]
            _check_tsa_range(d1, d2, ctx_before, ctx_after, blk, m.group(0))

        # Check corridor offset ranges (e.g. T-11 to T+4, T-4 to T+4, Pre-week ramp T-11 to T-9)
        for m in re.finditer(r"\bT(0|[+-]\d+)\s+to\s+T(0|[+-]\d+)\b", cleaned):
            k1, k2 = int(m.group(1)), int(m.group(2))
            ctx = cleaned[:m.start()].lower()
            if "pre-week ramp" in ctx:
                exp_k2 = counted_corr_offsets[-1] if (len(counted_core) == 0 and counted_corr_offsets) else -5
                if (k1, k2) != (-11, exp_k2):
                    raise ValueError(f"Pre-week ramp offset range {(k1, k2)} != {(-11, exp_k2)} in {blk!r}")
            elif (k1, k2) not in ((-11, 4), (-4, 4)):
                raise ValueError(f"Unexpected offset range {(k1, k2)} in {blk!r}")

        # Check year spans (e.g. 2019 to 2025)
        for m in re.finditer(r"\b((?:19|20)\d{2})\s+to\s+((?:19|20)\d{2})\b", cleaned):
            y1, y2 = int(m.group(1)), int(m.group(2))
            if y1 not in years_in_tsa or y2 not in years_in_tsa or y1 >= y2:
                raise ValueError(f"Invalid year range {m.group(0)!r} against TSA years {years_in_tsa}")



def build_thanksgiving_story(
    *,
    tsa: dict[str, Any],
    tsa_file: str,
    faa_hist: dict[str, Any],
    faa_hist_file: str,
    faa_state: dict[str, Any],
    faa_state_file: str,
    now_dt: datetime,
) -> tuple[str, dict[str, Any]]:
    """Build the complete static HTML for /stories/thanksgiving plus its trace metadata."""
    ledger = TraceLedger(
        tsa=tsa,
        tsa_file=tsa_file,
        faa_hist=faa_hist,
        faa_hist_file=faa_hist_file,
        faa_state=faa_state,
        faa_state_file=faa_state_file,
    )
    days_map: dict[str, int] = {k: int(v) for k, v in (tsa.get("days") or {}).items()}
    years_present: list[int] = sorted(int(y) for y in (tsa.get("years") or []))
    target_year = _target_thanksgiving_year(tsa, now_dt)
    tg_now = desk_tsa.thanksgiving(target_year)

    cmp_years = [y for y in COMPARE_YEARS if y in years_present and y < target_year]
    if not cmp_years:
        cmp_years = [y for y in sorted(years_present, reverse=True) if y < target_year]
    default_cmp = cmp_years[0] if cmp_years else target_year - 1

    # Corridor: T-11 through T+4 (16 days)
    offsets = list(range(-11, 5))
    corridor: list[dict[str, Any]] = []
    for k in offsets:
        d_now = tg_now + timedelta(days=k)
        iso_now = d_now.isoformat()
        c_now = days_map.get(iso_now)
        yr_entries: dict[str, dict[str, Any]] = {}
        for y in cmp_years:
            d_y = desk_tsa.thanksgiving(y) + timedelta(days=k)
            iso_y = d_y.isoformat()
            yr_entries[str(y)] = {
                "date": iso_y,
                "label": _fmt_month_day_year(d_y),
                "short": _fmt_month_day(d_y),
                "count": days_map.get(iso_y),
            }
        corridor.append({
            "idx": len(corridor),
            "k": k,
            "offset_label": "T0" if k == 0 else f"T{k:+d}",
            "date": iso_now,
            "date_obj": d_now,
            "dow": DOW_SHORT[d_now.weekday()],
            "day": d_now.day,
            "short": _fmt_month_day(d_now),
            "label": f"{DOW_SHORT[d_now.weekday()]} {_fmt_month_day_year(d_now)}",
            "in_core": -4 <= k <= 4,
            "is_thanksgiving": k == 0,
            "count": c_now,
            "years": yr_entries,
        })

    counted_corridor = [r for r in corridor if r["count"] is not None]
    core_rows = [r for r in corridor if r["in_core"]]
    counted_core = [r for r in core_rows if r["count"] is not None]
    default_day_idx = counted_corridor[-1]["idx"] if counted_corridor else 7

    # Trailing 7 counted days from latest TSA reading
    latest_iso = str(tsa["latest_date"])
    latest_d = date.fromisoformat(latest_iso)
    trail7_now_dates = [(latest_d - timedelta(days=k)).isoformat() for k in range(6, -1, -1) if (latest_d - timedelta(days=k)).isoformat() in days_map]
    trail7_cmp: dict[str, dict[str, Any]] = {}
    for y in cmp_years:
        delta_days = (tg_now - desk_tsa.thanksgiving(y)).days
        y_dates = [(date.fromisoformat(d) - timedelta(days=delta_days)).isoformat() for d in trail7_now_dates]
        if all(yd in days_map for yd in y_dates):
            trail7_cmp[str(y)] = {
                "dates": y_dates,
                "total": sum(days_map[yd] for yd in y_dates),
            }

    cmp_str = str(default_cmp)
    cmp_meta: dict[str, dict[str, Any]] = {}
    for y in cmp_years:
        core_y = [r["years"][str(y)] for r in core_rows if r["years"][str(y)]["count"] is not None]
        peak_y = max(core_y, key=lambda x: x["count"]) if core_y else None
        both_core = [r for r in counted_core if r["years"][str(y)]["count"] is not None]
        cmp_meta[str(y)] = {
            "core_total": sum(x["count"] for x in core_y) if len(core_y) == len(core_rows) else None,
            "peak_date": peak_y["date"] if peak_y else None,
            "peak_label": peak_y["label"] if peak_y else "",
            "peak_count": peak_y["count"] if peak_y else None,
            "counted_sum": sum(r["count"] for r in both_core) if both_core else None,
            "cmp_counted_sum": sum(r["years"][str(y)]["count"] for r in both_core) if both_core else None,
        }

    # Pre-register calendar metadata & years so every label is traced
    y_now_t = ledger.tsa_year(target_year)
    y_cmp_t = ledger.tsa_year(default_cmp)
    for y in cmp_years:
        ledger.tsa_year(y)
    if years_present:
        ledger.tsa_year(years_present[0])
        ledger.tsa_year(years_present[-1])

    rec_date = str(tsa["record_date"])
    rec_d = date.fromisoformat(rec_date)
    rec_m_str = ledger.tsa_millions(rec_date, suffix="")
    rec_int_str = ledger.tsa_direct(rec_date)

    n_core_counted = len(counted_core)
    n_corr_counted = len(counted_corridor)
    ledger.tsa_window_count("core_counted", "counted_core", n_core_counted, target_year)
    ledger.tsa_window_count("core_total", "core_len", len(core_rows), target_year)
    ledger.tsa_window_count("corridor_counted", "counted_corridor", n_corr_counted, target_year)
    ledger.tsa_window_count("corridor_len", "corridor_len", len(corridor), target_year)
    ledger.tsa_window_count("trail_len", "trail_len", len(trail7_now_dates), target_year)
    ledger.tsa_window_count("years_len", "years_len", len(years_present), target_year)

    # Compute dynamic headline (H1 concise <= 80 chars; full sentence for <title>/meta)
    trail7_cmp_dates = (trail7_cmp.get(cmp_str) or {}).get("dates") or []
    corr_now_dates = [r["date"] for r in counted_corridor if r["years"][cmp_str]["count"] is not None]
    corr_cmp_dates = [r["years"][cmp_str]["date"] for r in counted_corridor if r["years"][cmp_str]["count"] is not None]
    corr_cmp_map: dict[str, dict[str, Any]] = {}
    for y in cmp_years:
        both_c = [r for r in counted_corridor if r["years"][str(y)]["count"] is not None]
        if both_c:
            corr_cmp_map[str(y)] = {
                "total": sum(r["years"][str(y)]["count"] for r in both_c),
            }

    rec_m_h1 = ledger.tsa_millions(rec_date, suffix="M")
    rec_full_str = ledger.tsa_date(rec_d, "full", target_year=target_year)
    core_start_short = ledger.tsa_date(core_rows[0]["date_obj"], "short", target_year=target_year)
    core_end_short = ledger.tsa_date(core_rows[-1]["date_obj"], "short", target_year=target_year)
    core_end_full = ledger.tsa_date(core_rows[-1]["date_obj"], "full", target_year=target_year)
    corr_start_short = ledger.tsa_date(corridor[0]["date_obj"], "short", target_year=target_year)
    corr_end_short = ledger.tsa_date(corridor[-1]["date_obj"], "short", target_year=target_year)
    corr_end_full = ledger.tsa_date(corridor[-1]["date_obj"], "full", target_year=target_year)
    corr_len_dek = ledger.tsa_window_count("dek_corr_len", "corridor_len", len(corridor), target_year)

    if n_core_counted == 0 and trail7_cmp_dates:
        t7_pct_num = round(((sum(days_map[d] for d in trail7_now_dates) - sum(days_map[d] for d in trail7_cmp_dates)) / sum(days_map[d] for d in trail7_cmp_dates)) * 100.0, 1)
        direction_word = "ahead" if t7_pct_num >= 0 else "behind"
        t7_signed_pct = ledger.tsa_pct("h1_trail7_signed", trail7_now_dates, trail7_cmp_dates, signed=True)
        t7_abs_pct = ledger.tsa_pct("h1_trail7_abs", trail7_now_dates, trail7_cmp_dates, signed=False, use_abs=True)
        trail_end_dow_full = ledger.tsa_date(latest_d, "dow_full", target_year=target_year)
        n_trail_word = _count_word(len(trail7_now_dates))
        cmp_win_start = min(date.fromisoformat(x) for x in trail7_cmp_dates)
        cmp_win_end = max(date.fromisoformat(x) for x in trail7_cmp_dates)
        cmp_win_fmt = "short" if cmp_win_start.month != cmp_win_end.month else "day"
        cmp_win_txt = (
            f"{ledger.tsa_date(cmp_win_start, 'short', target_year=target_year)} to "
            f"{ledger.tsa_date(cmp_win_end, cmp_win_fmt, target_year=target_year)}"
        )
        headline_html = (
            f"US air travel is {t7_signed_pct} in the {n_trail_word} days ending {trail_end_dow_full} "
            f"versus the same {n_trail_word} days in {y_cmp_t} ({cmp_win_txt}); TSA's record remains {rec_m_h1}, set {rec_full_str}"
        )
        full_headline_text = (
            f"US air travel is running {t7_abs_pct} {direction_word} in the {n_trail_word} days ending {trail_end_dow_full} "
            f"versus the same {n_trail_word} days in {y_cmp_t} ({cmp_win_txt}); TSA's single-day record remains {rec_m_str} million, set {rec_full_str}"
        )
        dek_html = (
            f"Daily TSA screenings across the {corr_len_dek}-day corridor ({corr_start_short} to {corr_end_full}), "
            f"paired with hourly FAA delay checks."
        )
    elif 1 <= n_core_counted < 7:
        both_now = [r["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        both_cmp = [r["years"][cmp_str]["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        core_pct_num = round(((sum(days_map[d] for d in both_now) - sum(days_map[d] for d in both_cmp)) / sum(days_map[d] for d in both_cmp)) * 100.0, 1)
        up_down = "up" if core_pct_num >= 0 else "down"
        core_signed_pct = ledger.tsa_pct("h1_core_signed", both_now, both_cmp, signed=True)
        core_abs_pct = ledger.tsa_pct("h1_core_abs", both_now, both_cmp, signed=False, use_abs=True)
        h1_cc = ledger.tsa_window_count('h1_cc', 'counted_core', n_core_counted, target_year)
        h1_cl = ledger.tsa_window_count('h1_cl', 'core_len', len(core_rows), target_year)
        core_counted_first_short = ledger.tsa_date(counted_core[0]["date_obj"], "short", target_year=target_year)
        core_counted_last_full = ledger.tsa_date(counted_core[-1]["date_obj"], "full", target_year=target_year)
        n_core_word = _count_word(n_core_counted)
        day_unit = "day" if n_core_counted == 1 else "days"
        headline_html = (
            f"Early Thanksgiving week reading: {y_now_t} is {core_signed_pct} from {core_counted_first_short} to {core_counted_last_full} "
            f"({h1_cc} of {h1_cl} holiday days) versus the same {n_core_word} {day_unit} in {y_cmp_t}"
        )
        full_headline_text = (
            f"Early Thanksgiving week reading: {y_now_t} checkpoint volume is {up_down} {core_abs_pct} "
            f"from {core_counted_first_short} to {core_counted_last_full} ({h1_cc} of {h1_cl} holiday days) "
            f"versus the same {n_core_word} {day_unit} in {y_cmp_t}"
        )
        dek_html = (
            f"Weekday-aligned TSA checkpoint counts across the {corr_len_dek}-day corridor ({corr_start_short} to {corr_end_full}), "
            f"plus hourly FAA delay readings. Marked early until {ledger.tsa_window_count('dek_t7', 'trail_len', 7, target_year)} holiday days post."
        )
    elif 7 <= n_core_counted < len(core_rows):
        both_now = [r["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        both_cmp = [r["years"][cmp_str]["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        core_pct_num = round(((sum(days_map[d] for d in both_now) - sum(days_map[d] for d in both_cmp)) / sum(days_map[d] for d in both_cmp)) * 100.0, 1)
        direction_word = "ahead" if core_pct_num >= 0 else "behind"
        core_signed_pct = ledger.tsa_pct("h1_core_signed", both_now, both_cmp, signed=True)
        core_abs_pct = ledger.tsa_pct("h1_core_abs", both_now, both_cmp, signed=False, use_abs=True)
        h1_cc = ledger.tsa_window_count('h1_cc', 'counted_core', n_core_counted, target_year)
        h1_cl = ledger.tsa_window_count('h1_cl', 'core_len', len(core_rows), target_year)
        core_counted_first_short = ledger.tsa_date(counted_core[0]["date_obj"], "short", target_year=target_year)
        core_counted_last_full = ledger.tsa_date(counted_core[-1]["date_obj"], "full", target_year=target_year)
        n_core_word = _count_word(n_core_counted)
        headline_html = (
            f"Thanksgiving week air travel is {core_signed_pct} from {core_counted_first_short} to {core_counted_last_full} "
            f"({h1_cc} of {h1_cl} holiday days) versus the same {n_core_word} days in {y_cmp_t}"
        )
        full_headline_text = (
            f"Thanksgiving week air travel is running {core_abs_pct} {direction_word} "
            f"from {core_counted_first_short} to {core_counted_last_full} ({h1_cc} of {h1_cl} holiday days) "
            f"versus the same {n_core_word} days in {y_cmp_t}"
        )
        dek_html = (
            f"Weekday-aligned TSA checkpoint counts through {ledger.tsa_date(counted_core[-1]['date_obj'], 'dow_full', target_year=target_year)}, "
            f"paired with hourly FAA delay and ground-stop checks."
        )
    else:
        both_now = [r["date"] for r in counted_core]
        both_cmp = [r["years"][cmp_str]["date"] for r in counted_core]
        core_pct_num = round(((sum(days_map[d] for d in both_now) - sum(days_map[d] for d in both_cmp)) / sum(days_map[d] for d in both_cmp)) * 100.0, 1)
        up_down = "up" if core_pct_num >= 0 else "down"
        core_signed_pct = ledger.tsa_pct("h1_core_signed", both_now, both_cmp, signed=True)
        core_abs_pct = ledger.tsa_pct("h1_core_abs", both_now, both_cmp, signed=False, use_abs=True)
        peak_now = max(counted_core, key=lambda r: int(r["count"]))
        tot_m_h1 = ledger.tsa_sum('h1_tot', both_now, as_millions=True)
        peak_dow_s = ledger.tsa_date(peak_now['date_obj'], 'dow_short', target_year=target_year)
        peak_m_h1 = ledger.tsa_millions(peak_now['date'], suffix='')
        headline_html = (
            f"Thanksgiving week screened {tot_m_h1}M travelers from {core_start_short} to {core_end_full} "
            f"({core_signed_pct} versus {y_cmp_t}'s holiday week)"
        )
        full_headline_text = (
            f"Thanksgiving week screened {tot_m_h1} million travelers from {core_start_short} to {core_end_full}, "
            f"{up_down} {core_abs_pct} versus {y_cmp_t}'s holiday week, peaking on {peak_dow_s} at {peak_m_h1} million"
        )
        dek_html = (
            f"All {ledger.tsa_window_count('dek_cl', 'core_len', len(core_rows), target_year)} core holiday days "
            f"({core_start_short} to {core_end_full}) are posted, peaking on {peak_dow_s} at "
            f"{ledger.tsa_direct(peak_now['date'])} flyers."
        )

    # Key figures strip metrics
    latest_cmp_iso = (latest_d - timedelta(days=(tg_now - desk_tsa.thanksgiving(default_cmp)).days)).isoformat()
    latest_m_str = ledger.tsa_millions(latest_iso, suffix="M")
    latest_int_str = ledger.tsa_direct(latest_iso)
    latest_pct_str = ledger.tsa_pct("metric_latest", [latest_iso], [latest_cmp_iso])
    latest_ly_int = ledger.tsa_direct(latest_cmp_iso)

    t7_m_str = ledger.tsa_sum("metric_t7_m", trail7_now_dates, as_millions=True, suffix="M")
    t7_pct_str = ledger.tsa_pct("metric_t7_pct", trail7_now_dates, trail7_cmp_dates) if trail7_cmp_dates else "—"
    t7_now_int = ledger.tsa_sum("metric_t7_int", trail7_now_dates)
    t7_ly_int = ledger.tsa_sum("metric_t7_ly_int", trail7_cmp_dates) if trail7_cmp_dates else "—"

    # FAA data merge & traces
    faa = _merge_faa_rows(faa_hist, faa_state)
    faa_n_hours = ledger.faa_meta_num("n_hours", "hours_len", faa["n_hours"])
    faa_days_val = faa["days_span"]
    faa_days_str = str(int(faa_days_val)) if faa_days_val == int(faa_days_val) else f"{faa_days_val:.1f}"
    ledger.entries["faa_days_span"] = {
        "rendered": faa_days_str,
        "value": int(faa_days_val) if faa_days_val == int(faa_days_val) else faa_days_val,
        "op": "hist_hours_days",
        "source": FAA_SOURCE,
        "file": faa_hist_file,
        "field": "hours",
        "url": FAA_URL,
        "as_of": str(faa_hist.get("generated_utc") or ""),
    }
    faa_canon_str = ledger.faa_meta_num("canon_total", "canonical_total", faa["canonical_total"])
    faa_op_str = ledger.faa_meta_num("disrupted_op", "disrupted", len(faa["op_rows"]))
    faa_clos_str = ledger.faa_meta_num("closure_cnt", "closures", len(faa["closure_rows"]))
    faa_clear_str = ledger.faa_meta_num("clear_cnt", "clear", faa["clear_count"])
    faa_stops_str = ledger.faa_meta_num("stops_cnt", "stops", faa["stops_op_count"])
    faa_peak_op_str = ledger.faa_meta_num("peak_op", "peak_excl_sna", faa["peak_hr"]["op_active"])

    top_op = faa["op_rows"][0] if faa["op_rows"] else None
    top_op_desc = (
        f"{top_op['code']} leads at {ledger.faa_ap_stat(top_op['code'], 'non_clear', top_op['non_clear'])} of {faa_n_hours} checks"
        if top_op else "0 operational disruptions"
    )

    # Narrative step texts (4 steps on left column)
    wed_row = next(r for r in corridor if r["k"] == -1)
    tg_row = next(r for r in corridor if r["k"] == 0)
    sun_row = next(r for r in corridor if r["k"] == 3)
    wed_ly_iso = wed_row["years"][cmp_str]["date"]
    tg_ly_iso = tg_row["years"][cmp_str]["date"]
    sun_ly_iso = sun_row["years"][cmp_str]["date"]

    step1_idx = default_day_idx
    if len(counted_corridor) >= 2:
        paired_corr = [r for r in counted_corridor if r["years"][cmp_str]["count"]]
        best_r = max(
            paired_corr,
            key=lambda r: (r["count"] - r["years"][cmp_str]["count"]) / r["years"][cmp_str]["count"],
        ) if paired_corr else counted_corridor[0]
        first_r = counted_corridor[0]
        best_ly_iso = best_r["years"][cmp_str]["date"]
        first_ly_iso = first_r["years"][cmp_str]["date"]
        best_dow_s = ledger.tsa_date(best_r["date_obj"], "dow_short", target_year=target_year)
        first_dow_s = ledger.tsa_date(first_r["date_obj"], "dow_short", target_year=target_year)
        if best_r["date"] != first_r["date"] and best_r["years"][cmp_str]["count"] is not None and first_r["years"][cmp_str]["count"] is not None:
            step1_body = (
                f"{best_dow_s} posted the sharpest early gain: {ledger.tsa_direct(best_r['date'])} flyers cleared checkpoints "
                f"this year vs {ledger.tsa_direct(best_ly_iso)} in {y_cmp_t} "
                f"({ledger.tsa_pct('s1_best_pct', [best_r['date']], [best_ly_iso])}), after {first_dow_s} opened at "
                f"{ledger.tsa_direct(first_r['date'])} vs {ledger.tsa_direct(first_ly_iso)} "
                f"({ledger.tsa_pct('s1_first_pct', [first_r['date']], [first_ly_iso])})."
            )
        else:
            step1_body = (
                f"Early reading ({ledger.tsa_window_count('s1_cc', 'counted_corridor', len(corr_now_dates), target_year)} days counted): "
                f"{ledger.tsa_sum('s1_now', corr_now_dates)} travelers this year vs {ledger.tsa_sum('s1_ly', corr_cmp_dates)} in {y_cmp_t} "
                f"({ledger.tsa_pct('s1_pct', corr_now_dates, corr_cmp_dates)})."
            )
    elif corr_now_dates:
        step1_body = (
            f"Early reading: {ledger.tsa_sum('s1_now', corr_now_dates)} travelers this year vs "
            f"{ledger.tsa_sum('s1_ly', corr_cmp_dates)} in {y_cmp_t} ({ledger.tsa_pct('s1_pct', corr_now_dates, corr_cmp_dates)})."
        )
    else:
        step1_body = f"No {y_now_t} days in this corridor are published yet; {y_cmp_t} serves as the baseline."

    wed_now_iso = wed_row["date"]
    if wed_row["count"] is not None:
        step2_body = (
            f"On the Wednesday before Thanksgiving ({ledger.tsa_date(wed_row['date_obj'], 'full', target_year=target_year)}), "
            f"checkpoints screened {ledger.tsa_direct(wed_now_iso)} people this year vs {ledger.tsa_direct(wed_ly_iso)} in {y_cmp_t} "
            f"({ledger.tsa_pct('s2_pct', [wed_now_iso], [wed_ly_iso])})."
        )
    else:
        step2_body = (
            f"Last year, {ledger.tsa_direct(wed_ly_iso)} passengers cleared security on the Wednesday before Thanksgiving "
            f"({ledger.tsa_date(date.fromisoformat(wed_ly_iso), 'full', target_year=target_year)}). "
            f"Check back after {ledger.tsa_date(wed_row['date_obj'], 'short', target_year=target_year)} for {y_now_t}'s count."
        )

    tg_now_iso = tg_row["date"]
    if tg_row["count"] is not None:
        step3_body = (
            f"Screenings dropped {ledger.tsa_pct('s3_drop_now', [tg_now_iso], [wed_now_iso], signed=False, use_abs=True)} from Wednesday on Thanksgiving Day "
            f"to {ledger.tsa_direct(tg_now_iso)} this year vs {ledger.tsa_direct(tg_ly_iso)} in {y_cmp_t} ({ledger.tsa_pct('s3_yoy', [tg_now_iso], [tg_ly_iso])})."
        )
    else:
        step3_body = (
            f"Holiday travel plunges while families gather: in {y_cmp_t}, volume fell {ledger.tsa_pct('s3_drop_ly', [tg_ly_iso], [wed_ly_iso], signed=False, use_abs=True)} "
            f"from Wednesday to {ledger.tsa_direct(tg_ly_iso)} on Thanksgiving Day ({ledger.tsa_date(date.fromisoformat(tg_ly_iso), 'full', target_year=target_year)})."
        )

    sun_now_iso = sun_row["date"]
    if sun_row["count"] is not None:
        step4_body = (
            f"The Sunday return rush ({ledger.tsa_date(sun_row['date_obj'], 'full', target_year=target_year)}) screened "
            f"{ledger.tsa_direct(sun_now_iso)} travelers this year vs {ledger.tsa_direct(sun_ly_iso)} in {y_cmp_t} "
            f"({ledger.tsa_pct('s4_yoy', [sun_now_iso], [sun_ly_iso])})."
        )
    else:
        if 2024 in cmp_years and sun_row["years"].get("2024", {}).get("count") is not None:
            sun_24_iso = sun_row["years"]["2024"]["date"]
            step4_body = (
                f"Return Sunday is the steepest test of the week: last year's {ledger.tsa_offset(3)} crowd rose "
                f"{ledger.tsa_pct('s4_sun_wed', [sun_ly_iso], [wed_ly_iso])} above pre-Thanksgiving Wednesday "
                f"({ledger.tsa_direct(sun_ly_iso)} vs {ledger.tsa_direct(wed_ly_iso)}), and {ledger.tsa_year(2024)} also peaked on {ledger.tsa_offset(3)} at {ledger.tsa_direct(sun_24_iso)}."
            )
        else:
            step4_body = (
                f"Return Sunday is the steepest test of the week: in {y_cmp_t}, {ledger.tsa_offset(3)} rose "
                f"{ledger.tsa_pct('s4_sun_wed', [sun_ly_iso], [wed_ly_iso])} above pre-Thanksgiving Wednesday "
                f"({ledger.tsa_direct(sun_ly_iso)} vs {ledger.tsa_direct(wed_ly_iso)}), setting the single-day high across {ledger.tsa_year(years_present[0])} to {ledger.tsa_year(years_present[-1])}."
            )

    # Chart 1 Y scale
    all_corridor_vals: list[int] = []
    for r in corridor:
        if r["count"] is not None:
            all_corridor_vals.append(r["count"])
        for yv in r["years"].values():
            if yv["count"] is not None:
                all_corridor_vals.append(yv["count"])
    max_raw = max(all_corridor_vals or [3_000_000])
    max_val = int(math.ceil(max_raw / 500_000) * 500_000)
    ticks_m_desktop = [float(t) for t in range(0, int(max_val // 1_000_000) + 1)]
    ticks_m_mobile = (
        [0.0, 1.5, 3.0]
        if max_val >= 3_000_000
        else [0.0, round(max_val / 2_000_000, 1), round(max_val / 1_000_000, 1)]
    )

    # Build Desktop SVG for Chart 1 (viewBox 754px matches 1440px stage inner width -> 1.0x CSS px)
    d_x0, d_x1, d_y0, d_y1 = 48.0, 744.0, 84.0, 318.0
    d_plot_w = d_x1 - d_x0
    d_plot_h = d_y1 - d_y0
    slot_w = d_plot_w / len(corridor)
    band_x = d_x0 + 7 * slot_w
    band_w = 9 * slot_w
    anchor_indices = {0, 4, 7, 11, 14}

    d_svg: list[str] = [
        f'<svg id="rush-svg-desktop" class="story-svg svg-desktop" viewBox="0 0 754 404" '
        f'data-max-val="{max_val}" data-x-left="{int(d_x0)}" data-x-right="{int(d_x1)}" '
        f'data-y-top="{int(d_y0)}" data-y-bot="{int(d_y1)}" '
        f'role="img" aria-labelledby="rush-d-title rush-d-desc">',
        f'  <title id="rush-d-title">Daily TSA checkpoint counts across Thanksgiving corridor, {y_now_t} vs {y_cmp_t}</title>',
        f'  <desc id="rush-d-desc">Paired vertical bars from {ledger.tsa_offset(offsets[0])} to {ledger.tsa_offset(offsets[-1])}. Use the table toggle below for exact figures.</desc>',
        '  <defs>',
        '    <pattern id="pat-ly" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
        '      <rect width="6" height="6" fill="var(--surface-3)"/>',
        '      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--text-muted)" stroke-width="2" stroke-opacity="0.55"/>',
        '    </pattern>',
        '  </defs>',
        f'  <rect class="sv-band" x="{band_x:.1f}" y="34" width="{band_w:.1f}" height="{d_y1 - 34:.1f}" rx="4"/>',
        f'  <text class="sv-muted" x="{band_x + 10:.1f}" y="51">Thanksgiving week ({ledger.tsa_offset(-4)} to {ledger.tsa_offset(4)})</text>',
        f'  <rect class="sv-bar-now" x="{d_x0:.1f}" y="7" width="12" height="12" rx="2"/>',
        f'  <text class="sv-label" x="{d_x0 + 18:.1f}" y="18">{y_now_t} counted</text>',
        f'  <rect class="sv-bar-ly" x="{d_x0 + 140:.1f}" y="7" width="12" height="12" rx="2"/>',
        f'  <text id="rush-d-cmp-legend" class="sv-muted" x="{d_x0 + 158:.1f}" y="18">{y_cmp_t} same weekday</text>',
    ]
    if n_corr_counted < len(corridor):
        first_uncounted = next(r for r in corridor if r["count"] is None)
        last_uncounted = corridor[-1]
        d_svg.append(
            f'  <text class="sv-muted" x="{d_x1:.1f}" y="18" text-anchor="end">'
            f'{ledger.tsa_date(first_uncounted["date_obj"], "short", target_year=target_year)} to '
            f'{ledger.tsa_date(last_uncounted["date_obj"], "full", target_year=target_year)} awaiting TSA</text>'
        )

    for tm in ticks_m_desktop:
        y_tick = d_y1 - ((tm * 1_000_000) / max_val) * d_plot_h
        cls = "sv-zero" if tm == 0 else "sv-grid"
        d_svg.append(f'  <line class="{cls}" x1="{d_x0:.1f}" x2="{d_x1:.1f}" y1="{y_tick:.1f}" y2="{y_tick:.1f}"/>')
        d_svg.append(f'  <text class="sv-axis" x="{d_x0 - 6:.1f}" y="{y_tick + 5:.1f}" text-anchor="end">{ledger.tsa_tick(tm, target_year, cmp_years)}</text>')

    peak_cmp_row = max(
        (r for r in corridor if r["years"][cmp_str]["count"] is not None),
        key=lambda r: int(r["years"][cmp_str]["count"]),
    )
    latest_corr_row = counted_corridor[-1] if counted_corridor else None

    for r in corridor:
        i = r["idx"]
        sx = d_x0 + i * slot_w
        cx = sx + slot_w / 2
        ly_c = r["years"][cmp_str]["count"]
        now_c = r["count"]
        ly_iso = r["years"][cmp_str]["date"]
        now_str = ledger.tsa_direct(r["date"]) if now_c is not None else "awaiting TSA release"
        ly_str = ledger.tsa_direct(ly_iso) if ly_c is not None else "unavailable"
        aria = f"{ledger.tsa_date(r['date_obj'], 'dow_full', target_year=target_year)}, {ledger.tsa_offset(r['k'])}: {y_now_t} {now_str}, {y_cmp_t} {ly_str}"

        d_svg.append(
            f'  <g class="sv-day-hit{" is-selected" if i == default_day_idx else ""}" '
            f'data-day-idx="{i}" data-cx="{cx:.1f}" tabindex="0" role="button" aria-label="{_esc(aria)}">'
        )
        d_svg.append(f'    <rect class="sv-hit-bg" x="{sx + 1:.1f}" y="{d_y0 - 6:.1f}" width="{slot_w - 2:.1f}" height="{d_y1 - d_y0 + 10:.1f}" rx="4"/>')

        if ly_c is not None:
            bh = max(2.0, (ly_c / max_val) * d_plot_h)
            by = d_y1 - bh
            bx = cx - 14.0
            d_svg.append(f'    <rect class="sv-bar-ly" data-d-ly-bar="{i}" x="{bx:.1f}" y="{by:.1f}" width="13" height="{bh:.1f}" rx="1.5"/>')
            d_svg.append(f'    <line data-d-ly-cap="{i}" x1="{bx:.1f}" x2="{bx + 13:.1f}" y1="{by:.1f}" y2="{by:.1f}" stroke="var(--text-muted)" stroke-width="2"/>')

        bx_now = cx + 1.0
        if now_c is not None:
            bh2 = max(2.0, (now_c / max_val) * d_plot_h)
            by2 = d_y1 - bh2
            d_svg.append(f'    <rect class="sv-bar-now" x="{bx_now:.1f}" y="{by2:.1f}" width="13" height="{bh2:.1f}" rx="1.5"/>')
            d_svg.append(f'    <circle cx="{bx_now + 6.5:.1f}" cy="{by2:.1f}" r="3.2" fill="var(--accent)"/>')
        else:
            d_svg.append(f'    <rect class="sv-bar-slot" x="{bx_now:.1f}" y="{d_y1 - 8:.1f}" width="13" height="8" rx="1"/>')

        d_svg.append(f'    <line class="sv-grid" x1="{cx:.1f}" x2="{cx:.1f}" y1="{d_y1:.1f}" y2="{d_y1 + 4:.1f}"/>')
        if i in anchor_indices:
            day_lbl = ledger.tsa_date(r["date_obj"], "short", target_year=target_year)
            anchor = "start" if i == 0 else "middle"
            lbl_x = d_x0 if i == 0 else cx
            d_svg.append(f'    <text class="sv-axis" x="{lbl_x:.1f}" y="338" text-anchor="{anchor}">{_esc(day_lbl)}</text>')
            off_cls = "sv-label" if r["is_thanksgiving"] else "sv-muted"
            d_svg.append(f'    <text class="{off_cls}" x="{lbl_x:.1f}" y="358" text-anchor="{anchor}">{ledger.tsa_offset(r["k"])}</text>')
        d_svg.append('  </g>')

    # Direct key-point annotations: (1) prior-year return peak, (2) Thanksgiving Day lull, (3) latest counted day
    peak_i = peak_cmp_row["idx"]
    peak_bx = d_x0 + peak_i * slot_w + slot_w / 2 - 7.5
    peak_by = d_y1 - (peak_cmp_row["years"][cmp_str]["count"] / max_val) * d_plot_h
    peak_iso = peak_cmp_row["years"][cmp_str]["date"]
    peak_m = ledger.tsa_millions(peak_iso, suffix="M")
    peak_suffix = f" record, {ledger.tsa_date(rec_d, 'short', target_year=target_year)}" if peak_iso == rec_date else ""
    peak_tx = 740.0 if peak_i >= 11 else peak_bx
    peak_anchor = "end" if peak_i >= 11 else "middle"
    peak_ty = max(72.0, peak_by - 15.0)

    lull_i = tg_row["idx"]
    lull_now_c = tg_row["count"]
    lull_ly_c = tg_row["years"][cmp_str]["count"]
    lull_cx = d_x0 + lull_i * slot_w + slot_w / 2
    if lull_now_c is not None:
        lull_bx = lull_cx + 7.5
        lull_by = d_y1 - (lull_now_c / max_val) * d_plot_h
        lull_m = ledger.tsa_millions(tg_row["date"], suffix="M")
    else:
        lull_bx = lull_cx - 7.5
        lull_by = d_y1 - ((lull_ly_c or 0) / max_val) * d_plot_h
        lull_m = ledger.tsa_millions(tg_row["years"][cmp_str]["date"], suffix="M")
    lull_ty = lull_by - 12.0

    d_svg += [
        '  <g id="rush-d-lull-anno">',
        f'    <line id="rush-d-lull-line" x1="{lull_bx:.1f}" x2="{lull_bx:.1f}" y1="{lull_by - 3:.1f}" y2="{lull_ty + 3:.1f}" stroke="var(--text-muted)" stroke-width="1"/>',
        f'    <text id="rush-d-lull-text" class="sv-label" x="{lull_cx + 3.5:.1f}" y="{lull_ty:.1f}" text-anchor="middle"><tspan id="rush-d-lull-k" x="{lull_cx + 3.5:.1f}" dy="-15">{ledger.tsa_offset(0)} lull</tspan><tspan id="rush-d-lull-v" x="{lull_cx + 3.5:.1f}" dy="15">{lull_m}</tspan></text>',
        '  </g>',
        '  <g id="rush-d-peak-anno">',
        f'    <line id="rush-d-peak-line" x1="{peak_bx:.1f}" x2="{peak_bx:.1f}" y1="{peak_by - 3:.1f}" y2="{peak_ty + 4:.1f}" stroke="var(--text-muted)" stroke-width="1"/>',
        f'    <text id="rush-d-peak-text" class="sv-label" x="{peak_tx:.1f}" y="{peak_ty:.1f}" text-anchor="{peak_anchor}">{y_cmp_t} peak: {peak_m}{peak_suffix}</text>',
        '  </g>',
    ]

    if latest_corr_row is not None:
        li = latest_corr_row["idx"]
        lbx = d_x0 + li * slot_w + slot_w / 2 + 7.5
        lby = d_y1 - (latest_corr_row["count"] / max_val) * d_plot_h
        nb_vals = [
            max([v for v in [corridor[j]["count"], corridor[j]["years"][cmp_str]["count"]] if v is not None] or [0])
            for j in range(max(0, li - 1), min(len(corridor), li + 4))
        ]
        nb_min_y = d_y1 - (max(nb_vals or [latest_corr_row["count"]]) / max_val) * d_plot_h
        if abs(li - peak_i) <= 2 and abs(lby - peak_by) < 42:
            now_ty = peak_ty + 22.0
            now_tx = 740.0
            now_anchor = "end"
        else:
            now_ty = max(72.0, min(lby - 15.0, nb_min_y - 18.0))
            now_anchor = "start" if li <= 2 else ("end" if li >= 13 else "middle")
            now_tx = max(d_x0 + 4.0, min(740.0, lbx))
        now_m_s = ledger.tsa_millions(latest_corr_row["date"], suffix="M")
        now_d_s = ledger.tsa_date(latest_corr_row["date_obj"], "short", target_year=target_year)
        ly_match_c = latest_corr_row["years"][cmp_str]["count"]
        if ly_match_c is not None:
            now_p_s = ledger.tsa_pct("d_now_anno_pct", [latest_corr_row["date"]], [latest_corr_row["years"][cmp_str]["date"]], signed=True)
            now_lbl_text = f"{now_d_s}: {now_m_s} ({now_p_s})"
        else:
            now_lbl_text = f"{now_d_s}: {now_m_s}"
        d_svg += [
            '  <g id="rush-d-now-anno">',
            f'    <line id="rush-d-now-line" x1="{lbx:.1f}" x2="{lbx:.1f}" y1="{lby - 4:.1f}" y2="{now_ty + 4:.1f}" stroke="var(--accent)" stroke-width="1.2"/>',
            f'    <text id="rush-d-now-text" class="sv-anno" x="{now_tx:.1f}" y="{now_ty:.1f}" text-anchor="{now_anchor}">{_esc(now_lbl_text)}</text>',
            '  </g>',
        ]

    # Signature Moment sightline cursor (clamped pill keeps tag within plot edges)
    def_day_obj = corridor[default_day_idx]
    def_cx = d_x0 + default_day_idx * slot_w + slot_w / 2
    pill_w = 122.0
    pill_dx = max(d_x0 + pill_w / 2 - def_cx, min(d_x1 - pill_w / 2 - def_cx, 0.0))
    def_pill_lbl = f'{ledger.tsa_date(def_day_obj["date_obj"], "short", target_year=target_year)} · {ledger.tsa_offset(def_day_obj["k"])}'
    d_svg += [
        f'  <g id="rush-cursor" class="sv-cursor" transform="translate({def_cx:.1f}, 0)">',
        f'    <line class="sv-cursor-line" x1="0" x2="0" y1="{d_y0 - 4:.1f}" y2="{d_y1:.1f}"/>',
        f'    <rect id="rush-cursor-tag" class="sv-cursor-tag" x="{pill_dx - pill_w / 2:.1f}" y="367" width="{int(pill_w)}" height="26" rx="4"/>',
        f'    <text id="rush-cursor-tag-text" class="sv-cursor-tag-text" x="{pill_dx:.1f}" y="385" text-anchor="middle">{_esc(def_pill_lbl)}</text>',
        '  </g>',
        '</svg>',
    ]

    # Build Mobile SVG for Chart 1 (viewBox 317px matches 375px stage inner width -> 1.0x CSS px; >=44px rows)
    m_x0, m_x1 = 62.0, 206.0
    m_plot_w = m_x1 - m_x0
    m_y = 54.0
    m_row_h = 44.0
    m_svg_rows: list[str] = []
    for r in corridor:
        i = r["idx"]
        if i == 7:
            m_svg_rows.append(f'  <rect x="0" y="{m_y + 4:.1f}" width="317" height="22" fill="var(--surface)"/>')
            m_svg_rows.append(f'  <line class="sv-grid" x1="2" x2="315" y1="{m_y + 3:.1f}" y2="{m_y + 3:.1f}"/>')
            m_svg_rows.append(f'  <text class="sv-muted" x="4" y="{m_y + 20:.1f}">Thanksgiving week ({ledger.tsa_offset(-4)} to {ledger.tsa_offset(4)})</text>')
            m_y += 28.0
        ly_c = r["years"][cmp_str]["count"]
        now_c = r["count"]
        m_svg_rows.append(f'  <g class="sv-day-hit{" is-selected" if i == default_day_idx else ""}" data-day-idx="{i}" tabindex="0" role="button" aria-label="{_esc(r["label"])}">')
        m_svg_rows.append(f'    <rect class="sv-hit-bg" x="0" y="{m_y:.1f}" width="317" height="{m_row_h:.1f}" rx="4"/>')
        m_svg_rows.append(f'    <text class="sv-label" x="4" y="{m_y + 18:.1f}">{_esc(r["dow"])} {ledger.tsa_date(r["date_obj"], "day", target_year=target_year)}</text>')
        m_svg_rows.append(f'    <text class="sv-muted" x="4" y="{m_y + 36:.1f}">{ledger.tsa_offset(r["k"])}</text>')
        if ly_c is not None:
            w_ly = max(2.0, (ly_c / max_val) * m_plot_w)
            m_svg_rows.append(f'    <rect class="sv-bar-ly" data-m-ly-bar="{i}" x="{m_x0:.1f}" y="{m_y + 7:.1f}" width="{w_ly:.1f}" height="12" rx="1.5"/>')
        if now_c is not None:
            w_now = max(2.0, (now_c / max_val) * m_plot_w)
            m_svg_rows.append(f'    <rect class="sv-bar-now" x="{m_x0:.1f}" y="{m_y + 22:.1f}" width="{w_now:.1f}" height="13" rx="1.5"/>')
            m_str_val = ledger.tsa_millions(r["date"], suffix="M")
            if ly_c is not None:
                p_str = ledger.tsa_pct(f"m_row_{r['date']}", [r["date"]], [r["years"][cmp_str]["date"]], signed=True)
                val_lbl = f"{m_str_val} {p_str}"
            else:
                val_lbl = m_str_val
            val_cls = "sv-anno"
        else:
            m_svg_rows.append(f'    <rect class="sv-bar-slot" x="{m_x0:.1f}" y="{m_y + 22:.1f}" width="20" height="13" rx="1"/>')
            if ly_c is not None and (r["k"] in (-1, 0, 3) or i == default_day_idx):
                val_lbl = f"{y_cmp_t}: {ledger.tsa_millions(r['years'][cmp_str]['date'], suffix='M')}"
            else:
                val_lbl = ""
            val_cls = "sv-muted"
        m_svg_rows.append(f'    <text class="{val_cls}" data-m-val="{i}" x="{m_x1 + 6:.1f}" y="{m_y + 27:.1f}">{_esc(val_lbl)}</text>')
        m_svg_rows.append('  </g>')
        m_y += m_row_h

    m_total_h = int(m_y + 8)
    m_svg: list[str] = [
        f'<svg id="rush-svg-mobile" class="story-svg svg-mobile" viewBox="0 0 317 {m_total_h}" '
        f'data-max-val="{max_val}" data-x-zero="{int(m_x0)}" data-x-max="{int(m_x1)}" '
        f'role="img" aria-labelledby="rush-m-title rush-m-desc">',
        f'  <title id="rush-m-title">Daily TSA checkpoint counts, mobile view</title>',
        f'  <desc id="rush-m-desc">Horizontal paired bars from {ledger.tsa_offset(offsets[0])} to {ledger.tsa_offset(offsets[-1])}.</desc>',
        '  <defs>',
        '    <pattern id="pat-ly-m" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
        '      <rect width="6" height="6" fill="var(--surface-3)"/>',
        '      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--text-muted)" stroke-width="2" stroke-opacity="0.55"/>',
        '    </pattern>',
        '  </defs>',
        f'  <rect class="sv-bar-now" x="2" y="4" width="12" height="12" rx="2"/>',
        f'  <text class="sv-label" x="18" y="15">{y_now_t} counted</text>',
        f'  <rect class="sv-bar-ly" x="132" y="4" width="12" height="12" rx="2" style="fill:url(#pat-ly-m)"/>',
        f'  <text id="rush-m-cmp-legend" class="sv-muted" x="148" y="15">{y_cmp_t} same weekday</text>',
    ]
    for tm in ticks_m_mobile:
        xt = m_x0 + ((tm * 1_000_000) / max_val) * m_plot_w
        cls = "sv-zero" if tm == 0 else "sv-grid"
        m_svg.append(f'  <line class="{cls}" x1="{xt:.1f}" x2="{xt:.1f}" y1="44" y2="{m_total_h - 6}"/>')
        m_svg.append(f'  <text class="sv-axis" x="{xt:.1f}" y="38" text-anchor="middle">{ledger.tsa_tick(tm, target_year, cmp_years)}</text>')
    m_svg.extend(m_svg_rows)
    m_svg.append('</svg>')

    # Build Section 2 SVGs (FAA Hourly Timeline + Ranked Bars; both desktop and mobile carry hourly strips)
    faa_first_et = ledger.faa_timestamp("first_reading_utc", faa["first_reading_utc"], "et_short")
    faa_last_et = ledger.faa_timestamp("last_reading_utc", faa["last_reading_utc"], "et_short")
    et_midnight_indices = [
        i for i, h in enumerate(faa["hours"])
        if (dt := _parse_utc(h["utc"])) is not None and dt.astimezone(ET_ZONE).hour == 0
    ]

    n_h = max(1, faa["n_hours"])
    faa_bar_ticks = [0, round(n_h * 0.5), n_h]

    d2_strip_x, d2_strip_w = 196.0, 468.0
    d2_cw = d2_strip_w / n_h
    d2_bar_x, d2_bar_w = 696.0, 210.0
    d2_y0, d2_row_h = 106.0, 44.0
    d2_rows_end = d2_y0 + len(faa["op_rows"]) * d2_row_h
    d2_foot_y = d2_rows_end + 14.0
    d2_foot_h = 84.0 if faa["closure_rows"] else 18.0
    d2_total_h = int(d2_foot_y + d2_foot_h)

    d2_svg: list[str] = [
        f'<svg id="delay-svg-desktop" class="story-svg svg-desktop" viewBox="0 0 1126 {d2_total_h}" '
        f'data-strip-x="{d2_strip_x:.1f}" data-strip-w="{d2_strip_w:.1f}" data-strip-cw="{d2_cw:.4f}" '
        f'data-row-h="{int(d2_row_h)}" data-rows-y="{int(d2_y0)}" data-foot-h="{int(d2_foot_h)}" '
        f'role="img" aria-labelledby="delay-d-title delay-d-desc">',
        f'  <title id="delay-d-title">FAA hourly delay and stop checks by airport over {faa_n_hours} hours</title>',
        f'  <desc id="delay-d-desc">{faa_n_hours}-hour strip matrix ({_esc(faa_first_et)} to {_esc(faa_last_et)}) and zero-baseline stacked horizontal bars for {faa_op_str} operational airports with delay or stop listings, plus closure listings separated at bottom.</desc>',
        '  <defs>',
        '    <pattern id="pat-stop" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
        '      <rect width="6" height="6" fill="var(--red)"/>',
        '      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--red-ink)" stroke-width="1.6" stroke-opacity="0.75"/>',
        '    </pattern>',
        '  </defs>',
        '  <rect class="sv-bar-delay" x="8" y="6" width="12" height="12" rx="2"/>',
        '  <text class="sv-label" x="25" y="18">FAA flight delay</text>',
        '  <rect class="sv-bar-stop" x="166" y="6" width="12" height="12" rx="2"/>',
        '  <text class="sv-label" x="183" y="18">Ground stop or closure</text>',
        '  <text class="sv-muted" x="8" y="40">Airport</text>',
        f'  <text class="sv-muted" x="{d2_strip_x:.1f}" y="40">Hourly FAA timeline</text>',
        f'  <text class="sv-muted" x="{d2_bar_x:.1f}" y="40">Checks with delays or stops</text>',
        f'  <line class="sv-grid sv-col-grid" x1="{d2_strip_x:.1f}" x2="{d2_strip_x:.1f}" y1="71" y2="{d2_rows_end:.1f}"/>',
        f'  <text class="sv-axis sv-date-tick" x="{d2_strip_x:.1f}" y="64" text-anchor="start">{_esc(faa_first_et)}</text>',
    ]
    for hi_tk in et_midnight_indices:
        xt = d2_strip_x + hi_tk * d2_cw
        d2_svg.append(f'  <line class="sv-grid sv-col-grid" x1="{xt:.1f}" x2="{xt:.1f}" y1="71" y2="{d2_rows_end:.1f}"/>')
    d2_svg.append(f'  <line class="sv-grid sv-col-grid" x1="{d2_strip_x + d2_strip_w:.1f}" x2="{d2_strip_x + d2_strip_w:.1f}" y1="71" y2="{d2_rows_end:.1f}"/>')
    d2_svg.append(f'  <text class="sv-axis sv-date-tick" x="{d2_strip_x + d2_strip_w:.1f}" y="64" text-anchor="end">{_esc(faa_last_et)}</text>')

    for tk in faa_bar_ticks:
        xt = d2_bar_x + (tk / n_h) * d2_bar_w
        cls = "sv-zero" if tk == 0 else "sv-grid"
        anchor = "start" if tk == 0 else ("end" if tk == n_h else "middle")
        d2_svg.append(f'  <line class="{cls} sv-col-grid" x1="{xt:.1f}" x2="{xt:.1f}" y1="71" y2="{d2_rows_end:.1f}"/>')
        d2_svg.append(f'  <text class="sv-axis" x="{xt:.1f}" y="64" text-anchor="{anchor}">{ledger.faa_tick(tk)}</text>')

    def _render_faa_desktop_row(r: dict[str, Any], y: float, is_foot: bool = False) -> list[str]:
        out: list[str] = []
        code = r["code"]
        nc = ledger.faa_ap_stat(code, "non_clear", r["non_clear"])
        dc = ledger.faa_ap_stat(code, "d", r["d"])
        sc = ledger.faa_ap_stat(code, "s", r["s"])
        r_cls = "sv-sna-row" if is_foot else "sv-ap-row"
        hit_cls = "sv-ap-hit" + (" is-selected" if (not is_foot and top_op and code == top_op["code"]) else "")
        out.append(f'  <g class="{r_cls} {hit_cls}" data-ap-code="{_esc(code)}" data-has-stop="{"1" if r["s"] > 0 else "0"}" data-base-y="{y:.1f}" tabindex="0" role="button" aria-label="{_esc(code)} {_esc(r["short"])}: {nc} of {faa_n_hours} checks ({dc} delay, {sc} stop/closure)">')
        out.append(f'    <rect class="sv-hit-bg" x="0" y="{y:.1f}" width="1126" height="{d2_row_h:.1f}" rx="4"/>')
        out.append(f'    <text class="sv-code" x="8" y="{y + 27:.1f}">{_esc(code)}</text>')
        out.append(f'    <text class="sv-label" x="54" y="{y + 26:.1f}">{_esc(r["short"])}</text>')
        out.append(f'    <rect class="sv-bar-clear" x="{d2_strip_x:.1f}" y="{y + 25:.1f}" width="{d2_cw * n_h - 0.8:.1f}" height="4" rx="1"/>')
        for hi, ch in enumerate(r["strip"]):
            if ch == "c":
                continue
            cx = d2_strip_x + hi * d2_cw
            w_cell = max(2.4, d2_cw - 1.1)
            if ch == "d":
                out.append(f'    <rect class="sv-bar-delay" x="{cx:.1f}" y="{y + 11:.1f}" width="{w_cell:.1f}" height="20"/>')
            elif ch == "s":
                out.append(f'    <rect class="sv-bar-stop" x="{cx:.1f}" y="{y + 9:.1f}" width="{w_cell:.1f}" height="24"/>')
            elif ch == "-":
                out.append(f'    <rect x="{cx:.1f}" y="{y + 19:.1f}" width="{w_cell:.1f}" height="8" fill="var(--surface)" stroke="var(--border)" stroke-width="0.8"/>')
        dw = (r["d"] / n_h) * d2_bar_w
        sw = (r["s"] / n_h) * d2_bar_w
        if dw > 0:
            out.append(f'    <rect class="sv-bar-delay" x="{d2_bar_x:.1f}" y="{y + 14:.1f}" width="{max(2.5, dw):.1f}" height="16"/>')
        if sw > 0:
            out.append(f'    <rect class="sv-bar-stop" x="{d2_bar_x + dw:.1f}" y="{y + 14:.1f}" width="{max(2.5, sw):.1f}" height="16"/>')
        if is_foot:
            lbl = f"{nc}/{faa_n_hours} checks (closed)"
        elif r["s"] > 0:
            lbl = f"{nc}/{faa_n_hours} checks ({sc} stop)"
        else:
            lbl = f"{nc} of {faa_n_hours} checks"
        out.append(f'    <text class="sv-label" x="{d2_bar_x + d2_bar_w + 10:.1f}" y="{y + 27:.1f}">{_esc(lbl)}</text>')
        out.append('  </g>')
        return out

    for idx_r, r in enumerate(faa["op_rows"]):
        d2_svg.extend(_render_faa_desktop_row(r, d2_y0 + idx_r * d2_row_h, is_foot=False))

    if faa["closure_rows"]:
        d2_svg.append(f'  <g class="sv-sna-foot" data-base-y="{d2_foot_y:.1f}">')
        d2_svg.append(f'    <line class="sv-grid" x1="8" x2="1118" y1="{d2_foot_y:.1f}" y2="{d2_foot_y:.1f}"/>')
        d2_svg.append(f'    <text class="sv-muted" x="8" y="{d2_foot_y + 18:.1f}">Scheduled / ongoing closure listing (separate from operational delay ranking)</text>')
        for idx_c, r in enumerate(faa["closure_rows"]):
            d2_svg.extend(_render_faa_desktop_row(r, d2_foot_y + 28.0 + idx_c * d2_row_h, is_foot=True))
        d2_svg.append('  </g>')

    pk_idx = faa["peak_hr"]["idx"]
    pk_cx = d2_strip_x + pk_idx * d2_cw + d2_cw / 2
    d2_pill_w = 144.0
    d2_pill_dx = max(d2_strip_x + d2_pill_w / 2 - pk_cx, min(d2_strip_x + d2_strip_w - d2_pill_w / 2 - pk_cx, 0.0))
    d2_svg += [
        f'  <g id="delay-hour-cursor" class="sv-cursor" transform="translate({pk_cx:.1f}, 0)">',
        f'    <line id="delay-hour-cursor-line" class="sv-cursor-line" x1="0" x2="0" y1="100" y2="{d2_rows_end:.1f}"/>',
        f'    <rect id="delay-d-cursor-tag" class="sv-cursor-tag" x="{d2_pill_dx - d2_pill_w / 2:.1f}" y="74" width="{int(d2_pill_w)}" height="26" rx="4"/>',
        f'    <text id="delay-d-cursor-text" class="sv-cursor-tag-text" x="{d2_pill_dx:.1f}" y="92" text-anchor="middle">Peak: {faa_peak_op_str} airports</text>',
        '  </g>',
        '</svg>',
    ]

    # Mobile SVG for Chart 2 (viewBox 317px: 3-tier 64px rows with code/count, name on own line, strip, and spaced ET endpoints)
    m2_strip_x, m2_strip_w = 4.0, 308.0
    m2_cw = m2_strip_w / n_h
    m2_y0, m2_row_h = 104.0, 64.0
    m2_rows_end = m2_y0 + len(faa["op_rows"]) * m2_row_h
    m2_foot_y = m2_rows_end + 14.0
    m2_foot_h = 98.0 if faa["closure_rows"] else 16.0
    m2_total_h = int(m2_foot_y + m2_foot_h)

    def _split_et_label(et_str: str) -> tuple[str, str]:
        if ", " in et_str:
            d_part, t_part = et_str.split(", ", 1)
            return d_part + ",", t_part
        return et_str, ""

    first_d_part, first_t_part = _split_et_label(faa_first_et)
    last_d_part, last_t_part = _split_et_label(faa_last_et)

    def _et_tick_line(et_str: str, d_part: str, t_part: str, x_pos: float, anchor: str) -> str:
        if t_part:
            return (
                f'  <text class="sv-axis sv-date-tick" x="{x_pos:.1f}" y="38" text-anchor="{anchor}">'
                f'<tspan x="{x_pos:.1f}">{_esc(d_part)}</tspan> <tspan x="{x_pos:.1f}" dy="15">{_esc(t_part)}</tspan></text>'
            )
        return f'  <text class="sv-axis sv-date-tick" x="{x_pos:.1f}" y="46" text-anchor="{anchor}">{_esc(et_str)}</text>'

    m2_svg: list[str] = [
        f'<svg id="delay-svg-mobile" class="story-svg svg-mobile" viewBox="0 0 317 {m2_total_h}" '
        f'data-strip-x="{m2_strip_x:.1f}" data-strip-w="{m2_strip_w:.1f}" data-strip-cw="{m2_cw:.4f}" '
        f'data-row-h="{int(m2_row_h)}" data-rows-y="{int(m2_y0)}" data-foot-h="{int(m2_foot_h)}" '
        f'role="img" aria-labelledby="delay-m-title delay-m-desc">',
        f'  <title id="delay-m-title">FAA {faa_n_hours}-hour delay and stop timeline by airport, mobile view</title>',
        f'  <desc id="delay-m-desc">{faa_n_hours}-hour hourly status timeline ({_esc(faa_first_et)} to {_esc(faa_last_et)}) across airports with delay or stop checks.</desc>',
        '  <defs>',
        '    <pattern id="pat-stop-m" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
        '      <rect width="6" height="6" fill="var(--red)"/>',
        '      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--red-ink)" stroke-width="1.6" stroke-opacity="0.75"/>',
        '    </pattern>',
        '  </defs>',
        '  <rect class="sv-bar-delay" x="4" y="5" width="12" height="12" rx="2"/>',
        '  <text class="sv-label" x="20" y="16">FAA delay</text>',
        '  <rect class="sv-bar-stop" x="108" y="5" width="12" height="12" rx="2" style="fill:url(#pat-stop-m)"/>',
        '  <text class="sv-label" x="124" y="16">Ground stop or closure</text>',
        _et_tick_line(faa_first_et, first_d_part, first_t_part, m2_strip_x, "start"),
        _et_tick_line(faa_last_et, last_d_part, last_t_part, m2_strip_x + m2_strip_w, "end"),
        f'  <line class="sv-grid" x1="{m2_strip_x:.1f}" x2="{m2_strip_x + m2_strip_w:.1f}" y1="60" y2="60"/>',
        f'  <line class="sv-grid" x1="{m2_strip_x:.1f}" x2="{m2_strip_x:.1f}" y1="57" y2="64"/>',
        f'  <line class="sv-grid" x1="{m2_strip_x + m2_strip_w:.1f}" x2="{m2_strip_x + m2_strip_w:.1f}" y1="57" y2="64"/>',
    ]
    for hi_tk in et_midnight_indices:
        xt = m2_strip_x + hi_tk * m2_cw
        m2_svg.append(f'  <line class="sv-grid" x1="{xt:.1f}" x2="{xt:.1f}" y1="57" y2="64"/>')

    pk_idx = faa["peak_hr"]["idx"]
    pk_mx = m2_strip_x + pk_idx * m2_cw + m2_cw / 2
    m2_pill_w = 128.0
    m2_pill_dx = max(2.0 + m2_pill_w / 2 - pk_mx, min(315.0 - m2_pill_w / 2 - pk_mx, 0.0))
    # Emit mobile cursor before airport rows so its vertical sightline passes behind text halos.
    m2_svg += [
        f'  <g id="delay-m-hour-cursor" class="sv-cursor" transform="translate({pk_mx:.1f}, 0)">',
        f'    <line id="delay-m-hour-cursor-line" class="sv-cursor-line" x1="0" x2="0" y1="93" y2="{m2_rows_end:.1f}"/>',
        f'    <rect id="delay-m-cursor-tag" class="sv-cursor-tag" x="{m2_pill_dx - m2_pill_w / 2:.1f}" y="69" width="{int(m2_pill_w)}" height="24" rx="4"/>',
        f'    <text id="delay-m-cursor-text" class="sv-cursor-tag-text" x="{m2_pill_dx:.1f}" y="86" text-anchor="middle">Peak: {faa_peak_op_str} airports</text>',
        '  </g>',
    ]

    def _render_faa_mobile_row(r: dict[str, Any], y: float, is_foot: bool = False) -> list[str]:
        out: list[str] = []
        code = r["code"]
        nc = ledger.faa_ap_stat(code, "non_clear", r["non_clear"])
        dc = ledger.faa_ap_stat(code, "d", r["d"])
        sc = ledger.faa_ap_stat(code, "s", r["s"])
        r_cls = "sv-sna-row" if is_foot else "sv-ap-row"
        hit_cls = "sv-ap-hit" + (" is-selected" if (not is_foot and top_op and code == top_op["code"]) else "")
        out.append(f'  <g class="{r_cls} {hit_cls}" data-ap-code="{_esc(code)}" data-has-stop="{"1" if r["s"] > 0 else "0"}" data-base-y="{y:.1f}" tabindex="0" role="button" aria-label="{_esc(code)} {_esc(r["short"])}: {nc} of {faa_n_hours} checks ({dc} delay, {sc} stop/closure)">')
        out.append(f'    <line class="sv-grid" x1="0" x2="317" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'    <rect class="sv-hit-bg" x="0" y="{y + 1:.1f}" width="317" height="62.0" rx="4"/>')
        out.append(f'    <text class="sv-code" x="4" y="{y + 18:.1f}">{_esc(code)}</text>')
        if is_foot:
            lbl = f"{nc}/{faa_n_hours} checks (closed)"
        elif r["s"] > 0:
            lbl = f"{nc}/{faa_n_hours} checks ({sc} stop)"
        else:
            lbl = f"{nc}/{faa_n_hours} checks"
        out.append(f'    <text class="sv-muted sv-row-cnt" x="313" y="{y + 18:.1f}" text-anchor="end">{_esc(lbl)}</text>')
        out.append(f'    <text class="sv-label sv-ap-name" x="4" y="{y + 36:.1f}">{_esc(r["short"])}</text>')
        out.append(f'    <rect class="sv-bar-clear" x="{m2_strip_x:.1f}" y="{y + 50:.1f}" width="{m2_strip_w - 0.8:.1f}" height="3" rx="1"/>')
        for hi_tk in et_midnight_indices:
            xt = m2_strip_x + hi_tk * m2_cw
            out.append(f'    <line class="sv-grid" x1="{xt:.1f}" x2="{xt:.1f}" y1="{y + 44:.1f}" y2="{y + 59:.1f}"/>')
        for hi, ch in enumerate(r["strip"]):
            if ch == "c":
                continue
            cx = m2_strip_x + hi * m2_cw
            w_cell = max(2.0, m2_cw - 1.3)
            if ch == "d":
                out.append(f'    <rect class="sv-bar-delay sv-hr-cell" x="{cx:.1f}" y="{y + 45:.1f}" width="{w_cell:.1f}" height="13" rx="0.8"/>')
            elif ch == "s":
                out.append(f'    <rect class="sv-bar-stop sv-hr-cell" x="{cx:.1f}" y="{y + 44:.1f}" width="{w_cell:.1f}" height="15" rx="0.8" style="fill:url(#pat-stop-m)"/>')
            elif ch == "-":
                out.append(f'    <rect class="sv-hr-cell" x="{cx:.1f}" y="{y + 48:.1f}" width="{w_cell:.1f}" height="7" fill="var(--surface)" stroke="var(--border)" stroke-width="0.7"/>')
        out.append('  </g>')
        return out

    for idx_r, r in enumerate(faa["op_rows"]):
        m2_svg.extend(_render_faa_mobile_row(r, m2_y0 + idx_r * m2_row_h, is_foot=False))

    if faa["closure_rows"]:
        m2_svg.append(f'  <g class="sv-sna-foot" data-base-y="{m2_foot_y:.1f}">')
        m2_svg.append(f'    <line class="sv-grid" x1="2" x2="315" y1="{m2_foot_y:.1f}" y2="{m2_foot_y:.1f}"/>')
        m2_svg.append(f'    <text class="sv-muted" x="4" y="{m2_foot_y + 18:.1f}">Closure listing (separate from delay ranks)</text>')
        for idx_c, r in enumerate(faa["closure_rows"]):
            m2_svg.extend(_render_faa_mobile_row(r, m2_foot_y + 28.0 + idx_c * m2_row_h, is_foot=True))
        m2_svg.append('  </g>')

    m2_svg.append('</svg>')

    # Table 1: TSA daily table HTML
    t1_rows: list[str] = []
    for r in corridor:
        now_cell = ledger.tsa_direct(r["date"]) if r["count"] is not None else "Not yet published"
        cells_y = []
        for y in cmp_years:
            y_obj = r["years"][str(y)]
            cells_y.append(f'<td class="num">{ledger.tsa_direct(y_obj["date"]) if y_obj["count"] is not None else "—"}</td>')
        ly_default_iso = r["years"][cmp_str]["date"]
        if r["count"] is not None and r["years"][cmp_str]["count"] is not None:
            diff_cell = f"{ledger.tsa_diff('t1_' + r['date'], [r['date']], [ly_default_iso])} ({ledger.tsa_pct('t1_p_' + r['date'], [r['date']], [ly_default_iso])})"
        else:
            diff_cell = "—"
        hi_cls = ' class="is-highlight"' if r["is_thanksgiving"] else ""
        t1_rows.append(
            f'<tr{hi_cls}><th scope="row">{ledger.tsa_date(r["date_obj"], "dow_short", target_year=target_year)} ({ledger.tsa_offset(r["k"])})</th>'
            f'<td class="num">{now_cell}</td>{"".join(cells_y)}<td class="num">{diff_cell}</td></tr>'
        )

    # Table 2: FAA airport table HTML
    t2_rows: list[str] = []
    for r in faa["all_rows"]:
        c = r["code"]
        nc = ledger.faa_ap_stat(c, "non_clear", r["non_clear"])
        dc = ledger.faa_ap_stat(c, "d", r["d"])
        sc = ledger.faa_ap_stat(c, "s", r["s"])
        cc = ledger.faa_ap_stat(c, "c", r["c"])
        mc = ledger.faa_ap_stat(c, "missing", r["missing"])
        sh = ledger.faa_ap_stat(c, "share_pct", r["share_pct"])
        first_cell = (
            f'{ledger.faa_ap_stat(c, "first_non_clear_utc", r["first_utc"], rendered=r["first_local"])}'
            if r["first_utc"] else "—"
        )
        note = "Closure listing" if r["is_closure_listing"] else "Delay / stop program"
        t2_rows.append(
            f'<tr><th scope="row"><a href="/airports/{_esc(c)}">{_esc(c)}</a> · {_esc(r["short"])} ({_esc(note)})</th>'
            f'<td class="num">{dc}</td><td class="num">{sc}</td><td class="num">{nc}</td>'
            f'<td class="num">{sh}</td><td class="num">{cc}</td><td class="num">{mc}</td><td>{first_cell}</td></tr>'
        )
    zero = ledger.tsa_window_count("t2_zero", "zero", 0, target_year)
    clear_miss_min = ledger.faa_meta_num("clear_miss_min", "clear_missing_min", faa["clear_missing_min"])
    clear_miss_max = ledger.faa_meta_num("clear_miss_max", "clear_missing_max", faa["clear_missing_max"])
    clear_miss_cell = clear_miss_min if faa["clear_missing_min"] == faa["clear_missing_max"] else f"{clear_miss_min}–{clear_miss_max}"
    ledger.entries["faa_clear_share"] = {
        "rendered": "0.0%",
        "value": 0.0,
        "op": "hist_clear_share",
        "source": FAA_SOURCE,
        "file": faa_hist_file,
        "args": {},
        "url": FAA_URL,
        "as_of": str(faa_hist.get("generated_utc") or ""),
    }
    t2_rows.append(
        f'<tr><th scope="row">Remaining {faa_clear_str} airports</th>'
        f'<td class="num">{zero}</td><td class="num">{zero}</td><td class="num">{zero}</td>'
        f'<td class="num">0.0%</td><td class="num">{faa_n_hours}</td><td class="num">{clear_miss_cell}</td><td>None</td></tr>'
    )

    # Default readouts (work statically with JS off!)
    def_day = corridor[default_day_idx]
    def_ly_iso = def_day["years"][cmp_str]["date"]
    def_ly_obj = def_day["years"][cmp_str]
    def_now_str = ledger.tsa_direct(def_day["date"]) if def_day["count"] is not None else "Not yet published by TSA"
    def_ly_str = ledger.tsa_direct(def_ly_iso) if def_ly_obj["count"] is not None else "—"
    if def_day["count"] is not None and def_ly_obj["count"] is not None:
        def_delta = f'in {y_now_t} ({ledger.tsa_diff("ro_def", [def_day["date"]], [def_ly_iso])}, {ledger.tsa_pct("ro_def", [def_day["date"]], [def_ly_iso])} vs {y_cmp_t})'
    else:
        def_delta = f"{y_now_t} awaiting TSA daily release"

    pk = faa["peak_hr"]
    pk_utc_field = f"hours.{pk['idx']}"
    pk_et_str = ledger.faa_timestamp(pk_utc_field, pk["utc"], "et_short") if pk["utc"] else ""
    pk_utc_str = ledger.faa_timestamp(pk_utc_field, pk["utc"], "iso") if pk["utc"] else ""
    pk_codes = [r["code"] for r in faa["op_rows"] if r["strip"][pk["idx"]] in ("d", "s")]
    top_ap_sub = (
        f"{ledger.faa_ap_stat(top_op['code'], 'd', top_op['d'])} delay, "
        f"{ledger.faa_ap_stat(top_op['code'], 's', top_op['s'])} stop/closure · first non-clear "
        f"{ledger.faa_ap_stat(top_op['code'], 'first_non_clear_utc', top_op['first_utc'], rendered=top_op['first_local'])}"
        if top_op else ""
    )

    trail7_start_short = ledger.tsa_date(date.fromisoformat(trail7_now_dates[0]), "short", target_year=target_year) if trail7_now_dates else ""
    trail7_end_short = ledger.tsa_date(date.fromisoformat(trail7_now_dates[-1]), "short", target_year=target_year) if trail7_now_dates else ""
    trail7_end_full = ledger.tsa_date(date.fromisoformat(trail7_now_dates[-1]), "full", target_year=target_year) if trail7_now_dates else ""
    corr_start_short_c = ledger.tsa_date(date.fromisoformat(corr_now_dates[0]), "short", target_year=target_year) if corr_now_dates else ""
    corr_end_short_c = ledger.tsa_date(date.fromisoformat(corr_now_dates[-1]), "short", target_year=target_year) if corr_now_dates else ""
    corr_end_full_c = ledger.tsa_date(date.fromisoformat(corr_now_dates[-1]), "full", target_year=target_year) if corr_now_dates else ""

    # Story-data JSON for progressive enhancement
    story_data = {
        "target_year": target_year,
        "default_cmp_year": default_cmp,
        "cmp_years": cmp_years,
        "default_day_idx": default_day_idx,
        "core_counted": n_core_counted,
        "record_date": rec_date,
        "record_count": int(tsa["record_count"]),
        "trail7_label": f"{trail7_start_short} to {trail7_end_full}" if trail7_now_dates else "",
        "trail7_now": sum(days_map[d] for d in trail7_now_dates) if trail7_now_dates else None,
        "trail7_cmp": {k: {"total": v["total"]} for k, v in trail7_cmp.items()},
        "corr_counted": len(corr_now_dates),
        "corr_label": f"{corr_start_short_c} to {corr_end_full_c}" if corr_now_dates else "",
        "corr_now": sum(days_map[d] for d in corr_now_dates) if corr_now_dates else None,
        "corr_cmp": corr_cmp_map,
        "years": cmp_meta,
        "days": [
            {
                "idx": r["idx"],
                "k": r["k"],
                "offset_label": r["offset_label"],
                "date": r["date"],
                "short": r["short"],
                "label": r["label"],
                "in_core": r["in_core"],
                "count": r["count"],
                "years": r["years"],
            }
            for r in corridor
        ],
        "faa": {
            "peak_hour_idx": pk["idx"],
            "default_ap": top_op["code"] if top_op else "",
            "hours": faa["hours"],
            "rows": [
                {
                    "code": r["code"],
                    "short": r["short"],
                    "strip": r["strip"],
                    "d": r["d"],
                    "s": r["s"],
                    "c": r["c"],
                    "missing": r["missing"],
                    "non_clear": r["non_clear"],
                    "share_pct": r["share_pct"],
                    "is_closure_listing": r["is_closure_listing"],
                    "first_onset_local": r["first_local"],
                }
                for r in faa["all_rows"]
            ],
        },
    }

    year_btns_html = "".join(
        f'<button type="button" class="story-toggle-btn" data-cmp-year="{y}" aria-pressed="{"true" if y == default_cmp else "false"}">vs {y}</button>'
        for y in cmp_years
    )
    cmp_th_html = "".join(f'<th scope="col" class="num">{y}</th>' for y in cmp_years)

    tsa_fetched_date_str = ledger.tsa_timestamp("date_full")
    tsa_fetched_iso = ledger.tsa_timestamp("iso")
    faa_gen_date_str = ledger.faa_timestamp("generated_utc", faa["generated_utc"], "date_full")
    faa_gen_iso = ledger.faa_timestamp("generated_utc", faa["generated_utc"], "iso")
    faa_rows_str = ledger.faa_meta_num("rows_total", "rows_total", faa["rows_total"])

    if n_core_counted == 0 and corr_now_dates and corr_cmp_dates:
        takeaway_1 = (
            f"Across the first {ledger.tsa_window_count('tk_cc', 'counted_corridor', len(corr_now_dates), target_year)} corridor days "
            f"({corr_start_short_c} to {corr_end_full_c}), TSA screened {ledger.tsa_sum('tk_corr_now', corr_now_dates)} travelers "
            f"this year vs {ledger.tsa_sum('tk_corr_ly', corr_cmp_dates)} in {y_cmp_t} "
            f"({ledger.tsa_pct('tk_corr_pct', corr_now_dates, corr_cmp_dates)}); core holiday week runs {core_start_short} to {core_end_full}."
        )
    elif n_core_counted == 0 and trail7_cmp_dates:
        takeaway_1 = (
            f"Across the {ledger.tsa_window_count('tk_t7', 'trail_len', len(trail7_now_dates), target_year)} days "
            f"({trail7_start_short} to {trail7_end_full}), TSA screened {ledger.tsa_sum('tk_t7_now', trail7_now_dates)} travelers "
            f"this year vs {ledger.tsa_sum('tk_t7_ly', trail7_cmp_dates)} in {y_cmp_t} "
            f"({ledger.tsa_pct('tk_t7_pct', trail7_now_dates, trail7_cmp_dates)}); {y_cmp_t} Thanksgiving week peaked at "
            f"{ledger.tsa_millions(rec_date)} on {ledger.tsa_date(rec_d, 'dow_full', target_year=target_year)}."
        )
    elif 1 <= n_core_counted < 7:
        both_now_t = [r["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        both_cmp_t = [r["years"][cmp_str]["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        takeaway_1 = (
            f"Across the first {ledger.tsa_window_count('tk_cc_c', 'counted_core', n_core_counted, target_year)} of "
            f"{ledger.tsa_window_count('tk_cl_c', 'core_len', len(core_rows), target_year)} holiday days "
            f"({ledger.tsa_date(counted_core[0]['date_obj'], 'short', target_year=target_year)} to "
            f"{ledger.tsa_date(counted_core[-1]['date_obj'], 'full', target_year=target_year)}), TSA screened "
            f"{ledger.tsa_sum('tk_c', both_now_t)} flyers this year vs {ledger.tsa_sum('tk_c_ly', both_cmp_t)} in {y_cmp_t} "
            f"({ledger.tsa_pct('tk_c_pct', both_now_t, both_cmp_t)})."
        )
    elif 7 <= n_core_counted < len(core_rows):
        both_now_t = [r["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        both_cmp_t = [r["years"][cmp_str]["date"] for r in counted_core if r["years"][cmp_str]["count"] is not None]
        takeaway_1 = (
            f"Through {ledger.tsa_window_count('tk_cc_c', 'counted_core', n_core_counted, target_year)} of "
            f"{ledger.tsa_window_count('tk_cl_c', 'core_len', len(core_rows), target_year)} holiday days "
            f"({ledger.tsa_date(counted_core[0]['date_obj'], 'short', target_year=target_year)} to "
            f"{ledger.tsa_date(counted_core[-1]['date_obj'], 'full', target_year=target_year)}), TSA screened "
            f"{ledger.tsa_sum('tk_c', both_now_t)} flyers this year vs {ledger.tsa_sum('tk_c_ly', both_cmp_t)} on the same weekdays in {y_cmp_t} "
            f"({ledger.tsa_pct('tk_c_pct', both_now_t, both_cmp_t)})."
        )
    else:
        both_now_t = [r["date"] for r in counted_core]
        both_cmp_t = [r["years"][cmp_str]["date"] for r in counted_core]
        takeaway_1 = (
            f"Across all {ledger.tsa_window_count('tk_cl_c', 'core_len', len(core_rows), target_year)} Thanksgiving week days "
            f"({core_start_short} to {core_end_full}), "
            f"TSA screened {ledger.tsa_sum('tk_c', both_now_t)} travelers this year vs {ledger.tsa_sum('tk_c_ly', both_cmp_t)} in {y_cmp_t} "
            f"({ledger.tsa_pct('tk_c_pct', both_now_t, both_cmp_t)})."
        )

    # Assemble JSON-LD without external requests
    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Air Travel Desk", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Stories", "item": f"{SITE_URL}/stories/"},
            {"@type": "ListItem", "position": 3, "name": "The Thanksgiving rush", "item": f"{SITE_URL}/stories/thanksgiving"},
        ],
    }

    title_str = f"{full_headline_text} | Air Travel Desk"
    desc_str = f"{full_headline_text}. Daily TSA checkpoint travel counts for Thanksgiving week against prior years, plus early FAA hourly delay readings across {faa_canon_str} US airports."
    canonical = f"{SITE_URL}/stories/thanksgiving"

    story_data_json = json.dumps(story_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    def _delta_cls(pct_text: str) -> str:
        if pct_text in ("\u2014", "n/a"):
            return "story-delta--warn"
        if pct_text.startswith("-"):
            return "story-delta--down"
        return "story-delta--up"

    latest_delta_cls = _delta_cls(latest_pct_str)
    t7_delta_cls = _delta_cls(t7_pct_str)
    trail7_len_str = ledger.tsa_window_count("kpi_trail", "trail_len", len(trail7_now_dates), target_year)
    latest_dow_short = ledger.tsa_date(latest_d, "dow_short", target_year=target_year)
    clos_codes_str = ", ".join(r["code"] for r in faa["closure_rows"])
    if faa["closure_rows"] and top_op:
        faa_kpi_sub = (
            f"Plus {faa_clos_str} closed ({clos_codes_str}) and {faa_clear_str} clear; "
            f"{top_op['code']} led with {ledger.faa_ap_stat(top_op['code'], 'non_clear', top_op['non_clear'])} hourly checks"
        )
        faa_takeaway = (
            f"Across {faa_n_hours} hourly FAA snapshots ({faa_first_et} to {faa_last_et}), {faa_clear_str} of {faa_canon_str} "
            f"monitored US airports stayed clear, {faa_op_str} had flight-delay or ground-stop programs, and {faa_clos_str} "
            f"carried a closure listing ({clos_codes_str}) — peaking at {faa_peak_op_str} delayed or stopped airports at {pk_et_str}."
        )
    elif top_op:
        faa_kpi_sub = (
            f"Remaining {faa_clear_str} clear; "
            f"{top_op['code']} led with {ledger.faa_ap_stat(top_op['code'], 'non_clear', top_op['non_clear'])} hourly checks"
        )
        faa_takeaway = (
            f"Across {faa_n_hours} hourly FAA snapshots ({faa_first_et} to {faa_last_et}), {faa_clear_str} of {faa_canon_str} "
            f"monitored US airports stayed clear and {faa_op_str} had flight-delay or ground-stop programs — peaking at "
            f"{faa_peak_op_str} delayed or stopped airports at {pk_et_str}."
        )
    else:
        faa_kpi_sub = f"All {faa_clear_str} airports clear in all {faa_n_hours} hourly checks"
        faa_takeaway = (
            f"Across {faa_n_hours} hourly FAA snapshots ({faa_first_et} to {faa_last_et}), all {faa_clear_str} of {faa_canon_str} "
            f"monitored US airports stayed clear."
        )
    faa_clos_note = f"Plus {clos_codes_str} nightly closure listing." if faa["closure_rows"] else "All operational hubs checked."
    def_day_pill = f'{ledger.tsa_date(def_day["date_obj"], "short", target_year=target_year)} · {ledger.tsa_offset(def_day["k"])}'
    corr_len_t1 = ledger.tsa_window_count("t1_corr_len", "corridor_len", len(corridor), target_year)
    pre_end_k = counted_corridor[-1]["k"] if (counted_corridor and n_core_counted == 0) else -5

    html_head_and_main = "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{_esc(title_str)}</title>",
        f'  <meta name="description" content="{_esc(desc_str)}">',
        f'  <link rel="canonical" href="{_esc(canonical)}">',
        f'  <meta property="og:title" content="{_esc(title_str)}">',
        f'  <meta property="og:description" content="{_esc(desc_str)}">',
        f'  <meta property="og:image" content="{SITE_URL}/og.png">',
        f'  <meta property="og:url" content="{_esc(canonical)}">',
        '  <meta property="og:type" content="article">',
        '  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:title" content="{_esc(title_str)}">',
        f'  <meta name="twitter:description" content="{_esc(desc_str)}">',
        f'  <meta name="twitter:image" content="{SITE_URL}/og.png">',
        '  <meta name="theme-color" content="#080b0f" media="(prefers-color-scheme: dark)">',
        '  <meta name="theme-color" content="#f6f4ef" media="(prefers-color-scheme: light)">',
        '  <link rel="icon" href="/favicon.svg" type="image/svg+xml">',
        '  <link rel="icon" href="/favicon.png" type="image/png">',
        f"  {bap.THEME_SNIPPET}",
        '  <script src="/theme.js" defer></script>',
        '  <script src="/watch.js" defer></script>',
        '  <link rel="stylesheet" href="/tokens.css">',
        '  <link rel="stylesheet" href="/style.css">',
        '  <link rel="stylesheet" href="/stories/thanksgiving/story.css">',
        bap._json_ld_script(breadcrumb_ld),
        "</head>",
        '<body class="page-story">',
        _header(),
        '  <div class="container">',
        '  <main id="main-content" class="story-main">',
        '    <p class="crumb"><a href="/">Live board</a> <span aria-hidden="true">/</span> <a href="/stories/">Stories</a> <span aria-hidden="true">/</span> <span>Thanksgiving rush</span></p>',
        '    <header class="story-head">',
        '      <div class="story-hero-grid">',
        '        <div class="story-hero-copy">',
        f'          <p class="story-kicker">Thanksgiving tracker · Updated {_esc(tsa_fetched_date_str)}</p>',
        f'          <h1 class="story-title">{_esc(headline_html)}</h1>',
        f'          <p class="story-dek">{_esc(dek_html)}</p>',
        '        </div>',
        '        <ul class="story-metrics" aria-label="Key Thanksgiving figures">',
        '          <li class="story-metric">',
        f'            <p class="story-metric-value">{_esc(latest_m_str)}</p>',
        '            <div class="story-metric-body">',
        f'              <p class="story-metric-label">Flyers screened {_esc(latest_dow_short)} (latest TSA count)</p>',
        f'              <p class="story-metric-sub">{_esc(latest_int_str)} this year vs {_esc(latest_ly_int)} in {y_cmp_t} (<span class="{latest_delta_cls}">{_esc(latest_pct_str)}</span>)</p>',
        '            </div>',
        '          </li>',
        '          <li class="story-metric">',
        f'            <p class="story-metric-value">{_esc(t7_m_str)}</p>',
        '            <div class="story-metric-body">',
        f'              <p class="story-metric-label">Flyers in {trail7_len_str} days ({_esc(trail7_start_short)} to {_esc(trail7_end_full)}, TSA)</p>',
        f'              <p class="story-metric-sub">{_esc(t7_now_int)} this year vs {_esc(t7_ly_int)} in {y_cmp_t} (<span class="{t7_delta_cls}">{_esc(t7_pct_str)}</span>)</p>',
        '            </div>',
        '          </li>',
        '          <li class="story-metric">',
        f'            <p class="story-metric-value">{_esc(rec_m_str)}M</p>',
        '            <div class="story-metric-body">',
        f'              <p class="story-metric-label">TSA single-day record ({_esc(rec_full_str)})</p>',
        f'              <p class="story-metric-sub">{_esc(rec_int_str)} on return Sunday (TSA)</p>',
        '            </div>',
        '          </li>',
        '          <li class="story-metric">',
        f'            <p class="story-metric-value">{faa_op_str} of {faa_canon_str}</p>',
        '            <div class="story-metric-body">',
        f'              <p class="story-metric-label">Early: airports with delays in {faa_n_hours}-hour FAA archive</p>',
        f'              <p class="story-metric-sub">{_esc(faa_kpi_sub)}</p>',
        '            </div>',
        '          </li>',
        '        </ul>',
        '      </div>',
        '    </header>',
        '',
        '    <section id="rush" class="story-sec" aria-labelledby="rush-heading">',
        '      <div class="story-sec-head">',
        '        <h2 id="rush-heading">Daily travelers across Thanksgiving week: this year vs prior years</h2>',
        f'        <p id="rush-takeaway" class="story-takeaway">{_esc(takeaway_1)}</p>',
        '      </div>',
        '      <div class="story-scrolly">',
        '        <div class="story-stage">',
        '          <p class="story-chart-guide">Drag the day slider or choose a year to compare.</p>',
        '          <div class="story-controls">',
        '            <div class="story-control-block">',
        '              <span class="story-control-label">Compare</span>',
        '              <div class="story-segmented" role="group" aria-label="Comparison year">',
        f'                {year_btns_html}',
        '              </div>',
        '            </div>',
        '            <div class="story-scrub-row">',
        '              <div class="story-scrub-head">',
        '                <label class="story-control-label" for="rush-scrub">Day</label>',
        f'                <output id="rush-scrub-val" class="story-scrub-val" for="rush-scrub">Selected: {_esc(def_day_pill)}</output>',
        '              </div>',
        '              <div class="story-scrub-inputs">',
        '                <button type="button" id="rush-prev" class="story-step-nav" aria-label="Previous day">&lsaquo;</button>',
        f'                <input type="range" id="rush-scrub" class="story-range" min="0" max="{len(corridor) - 1}" value="{default_day_idx}" aria-label="Select day in Thanksgiving corridor">',
        '                <button type="button" id="rush-next" class="story-step-nav" aria-label="Next day">&rsaquo;</button>',
        '              </div>',
        '            </div>',
        '          </div>',
        '          <div id="rush-readout" class="story-readout" aria-live="polite">',
        f'            <p id="rush-ro-day" class="story-readout-day">{_esc(ledger.tsa_date(def_day["date_obj"], "dow_full", target_year=target_year))} ({ledger.tsa_offset(def_day["k"])})</p>',
        f'            <p id="rush-ro-now" class="story-readout-stat">{_esc(def_now_str)}<span>{_esc(def_delta)}</span></p>',
        f'            <p id="rush-ro-ly" class="story-readout-stat">{_esc(def_ly_str)}<span>in {y_cmp_t} ({_esc(ledger.tsa_date(date.fromisoformat(def_ly_iso), "full", target_year=target_year))} · same weekday)</span></p>',
        '          </div>',
        '          <div class="story-chart-wrap">',
        "\n".join(d_svg),
        "\n".join(m_svg),
        '          </div>',
        f'          <p class="story-chart-src"><a href="{TSA_URL}" target="_blank" rel="noopener noreferrer">Source: {TSA_SOURCE}</a> <span>Fetched {_esc(tsa_fetched_iso)} · aligned by days to Thanksgiving ({_esc(corr_start_short)} to {_esc(corr_end_full)}; {ledger.tsa_offset(-11)} to {ledger.tsa_offset(4)}).</span></p>',
        '          <details class="story-table-details">',
        f'            <summary>Show table: daily TSA checkpoint counts ({corr_len_t1} days, {_esc(corr_start_short)} to {_esc(corr_end_full)})</summary>',
        '            <div class="story-table-scroll">',
        '              <table class="story-table">',
        f'                <caption>Daily TSA checkpoint counts ({_esc(corr_start_short)} to {_esc(corr_end_full)}; {ledger.tsa_offset(-11)} to {ledger.tsa_offset(4)})</caption>',
        f'                <thead><tr><th scope="col">Day ({y_now_t})</th><th scope="col" class="num">{y_now_t}</th>{cmp_th_html}<th scope="col" class="num">{y_now_t} vs {y_cmp_t}</th></tr></thead>',
        '                <tbody>',
        "\n".join(t1_rows),
        '                </tbody>',
        '              </table>',
        '            </div>',
        '          </details>',
        '        </div>',
        '        <ol class="story-steps" aria-label="Story beats across Thanksgiving week">',
        f'          <li class="story-step is-active" data-step-idx="{step1_idx}"><button type="button" class="story-step-btn"><span class="story-step-kicker">Pre-week ramp · {ledger.tsa_offset(-11)} to {ledger.tsa_offset(pre_end_k)}</span><span class="story-step-title">Travel builds before the core week begins</span><span class="story-step-body">{_esc(step1_body)}</span></button></li>',
        f'          <li class="story-step" data-step-idx="{wed_row["idx"]}"><button type="button" class="story-step-btn"><span class="story-step-kicker">Outbound peak · {ledger.tsa_offset(-1)}</span><span class="story-step-title">Wednesday before Thanksgiving</span><span class="story-step-body">{_esc(step2_body)}</span></button></li>',
        f'          <li class="story-step" data-step-idx="{tg_row["idx"]}"><button type="button" class="story-step-btn"><span class="story-step-kicker">Holiday lull · {ledger.tsa_offset(0)}</span><span class="story-step-title">Thanksgiving Day drop</span><span class="story-step-body">{_esc(step3_body)}</span></button></li>',
        f'          <li class="story-step" data-step-idx="{sun_row["idx"]}"><button type="button" class="story-step-btn"><span class="story-step-kicker">Return record · {ledger.tsa_offset(3)}</span><span class="story-step-title">Sunday after Thanksgiving</span><span class="story-step-body">{_esc(step4_body)}</span></button></li>',
        '        </ol>',
        '      </div>',
        '    </section>',
        '',
        '    <section id="delays" class="story-sec" aria-labelledby="delays-heading">',
        '      <div class="story-sec-head">',
        f'        <p class="story-kicker story-kicker--early">Early reading · {faa_days_str}-day FAA hourly archive</p>',
        '        <h2 id="delays-heading">Where airport delays and ground stops started</h2>',
        f'        <p class="story-takeaway">{_esc(faa_takeaway)}</p>',
        '      </div>',
        '      <div class="story-delay-box">',
        '        <p class="story-chart-guide">Drag the hour slider to inspect any hourly FAA check, or filter to ground stops.</p>',
        '        <div class="story-controls">',
        '          <div class="story-control-block">',
        '            <span class="story-control-label">Show</span>',
        '            <div class="story-segmented story-segmented--two" role="group" aria-label="Airport program filter">',
        '              <button type="button" class="story-toggle-btn" data-delay-filter="all" aria-pressed="true">All delayed</button>',
        f'              <button type="button" class="story-toggle-btn" data-delay-filter="stops" aria-pressed="false">Stops only ({faa_stops_str})</button>',
        '            </div>',
        '          </div>',
        '          <div class="story-scrub-row">',
        '            <div class="story-scrub-head">',
        '              <label class="story-control-label" for="delay-scrub">Hour</label>',
        f'              <output id="delay-scrub-val" class="story-scrub-val" for="delay-scrub">Selected: {_esc(pk_et_str)}</output>',
        '            </div>',
        '            <div class="story-scrub-inputs">',
        '              <button type="button" id="delay-prev" class="story-step-nav" aria-label="Previous hour">&lsaquo;</button>',
        f'              <input type="range" id="delay-scrub" class="story-range" min="0" max="{max(0, faa["n_hours"] - 1)}" value="{pk["idx"]}" aria-label="Select hour in hourly FAA archive">',
        '              <button type="button" id="delay-next" class="story-step-nav" aria-label="Next hour">&rsaquo;</button>',
        '            </div>',
        '          </div>',
        '        </div>',
        '        <div id="delay-readout" class="story-readout" aria-live="polite">',
        f'          <p id="delay-ro-time" class="story-readout-day">{_esc(pk_et_str)} ({_esc(pk_utc_str)})</p>',
        f'          <p id="delay-ro-active" class="story-readout-stat">{faa_peak_op_str} airports with active delay/stop: {_esc(", ".join(pk_codes))}<span>{_esc(faa_clos_note)}</span></p>',
        f'          <p id="delay-ro-ap" class="story-readout-stat">{_esc(top_op["code"] + " · " + top_op["short"] + ": " + ledger.faa_ap_stat(top_op["code"], "non_clear", top_op["non_clear"]) + " non-clear hourly checks") if top_op else "None"}<span>{_esc(top_ap_sub)}</span></p>',
        '        </div>',
        '        <div class="story-chart-wrap">',
        "\n".join(d2_svg),
        "\n".join(m2_svg),
        '        </div>',
        '        <div class="story-caveats">',
        f'          <p><strong>Early data &amp; limits:</strong> This {faa_days_str}-day archive ({faa_rows_str} airport-hour readings) is marked <strong>early</strong>; less than a full week of data cannot establish a recurring Thanksgiving pattern. Hourly snapshots count active FAA program checks, not exact delay durations in minutes. Missing checks (-) never mean clear, and FAA feeds do not log airline-caused delays.</p>',
        '        </div>',
        f'        <p class="story-chart-src"><a href="{FAA_URL}" target="_blank" rel="noopener noreferrer">Source: {FAA_SOURCE} (nasstatus.faa.gov)</a> <span>Generated {_esc(faa_gen_iso)}.</span></p>',
        '        <details class="story-table-details">',
        '          <summary>Show table: FAA hourly readings by airport</summary>',
        '          <div class="story-table-scroll">',
        '            <table class="story-table">',
        f'              <caption>FAA NAS status hourly checks by canonical airport ({faa_n_hours} hours, {_esc(faa_first_et)} to {_esc(faa_last_et)})</caption>',
        f'              <thead><tr><th scope="col">Airport</th><th scope="col" class="num">Delay (d)</th><th scope="col" class="num">Stop/closed (s)</th><th scope="col" class="num">Non-clear</th><th scope="col" class="num">Share ({faa_n_hours}h)</th><th scope="col" class="num">Clear (c)</th><th scope="col" class="num">Missing (-)</th><th scope="col">First non-clear</th></tr></thead>',
        '              <tbody>',
        "\n".join(t2_rows),
        '              </tbody>',
        '            </table>',
        '          </div>',
        '        </details>',
        '      </div>',
        '    </section>',
        '',
        '    <section id="method" class="story-sec" aria-labelledby="method-heading">',
        '      <div class="story-sec-head">',
        '        <h2 id="method-heading">Method note &amp; source ledger</h2>',
        '      </div>',
        '      <div class="story-method-grid">',
        '        <div class="story-method-copy">',
        f'          <p><strong>Weekday alignment:</strong> Thanksgiving falls on the fourth Thursday of November ({_esc(ledger.tsa_date(tg_now, "full", target_year=target_year))}). Every prior year is aligned by day offset ({ledger.tsa_offset(-11)} to {ledger.tsa_offset(4)}) so Saturday meets Saturday and Sunday meets Sunday.</p>',
        '          <p><strong>Self-updating build:</strong> On every site build, <code>tools/build_stories.py</code> fetches the latest TSA daily table, merges cached historical years, reads the stored FAA hourly archive, and embeds a machine-readable trace block linking every displayed figure to its source file and field. Unpublished future dates remain empty slots rather than zero bars.</p>',
        '          <p><strong>Canonical codes &amp; closures:</strong> FAA readings merge legacy PBI rows into DJT and display SNA&#x27;s multi-day closure listing from <code>readings/state.json</code> separately below the operational delay ranking.</p>',
        '        </div>',
        '        <div class="story-table-scroll">',
        '          <table class="story-table">',
        '            <caption>Data sources, licences, and latest timestamps for this story</caption>',
        '            <thead><tr><th scope="col">Source</th><th scope="col">URL</th><th scope="col">Licence</th><th scope="col">Fetched / generated</th></tr></thead>',
        '            <tbody>',
        f'              <tr><th scope="row">{TSA_SOURCE}</th><td data-label="URL"><a href="{TSA_URL}" target="_blank" rel="noopener noreferrer">{TSA_URL}</a></td><td data-label="Licence">{TSA_LICENCE}</td><td data-label="Fetched">{_esc(tsa_fetched_iso)}</td></tr>',
        f'              <tr><th scope="row">{FAA_SOURCE}</th><td data-label="URL"><a href="{FAA_URL}" target="_blank" rel="noopener noreferrer">{FAA_URL}</a></td><td data-label="Licence">{FAA_LICENCE}</td><td data-label="Fetched">{_esc(faa_gen_iso)}</td></tr>',
        '            </tbody>',
        '          </table>',
        '        </div>',
        '      </div>',
        '      <div class="story-crosslinks" aria-label="Related Air Travel Desk pages">',
        '        <a class="tap" href="/">Check live US airport board</a>',
        '        <a class="tap" href="/airports/">Browse US airport pages</a>',
        '        <a class="tap" href="/stuck">Delayed or cancelled guide</a>',
        '      </div>',
        '    </section>',
        '  </main>',
        '  </div>',
        '  <div id="story-tip" class="story-tip" role="status" hidden></div>',
        _footer(),
    ])
    # Build trace payload strictly after all visible text and SVGs are constructed
    trace_payload = {
        "story": "thanksgiving",
        "generated_utc": _iso_utc(now_dt),
        "files": {
            "tsa": {"path": tsa_file, "source": TSA_SOURCE, "url": TSA_URL, "as_of": tsa["fetched_utc"]},
            "faa_history": {"path": faa_hist_file, "source": FAA_SOURCE, "url": FAA_URL, "as_of": faa["generated_utc"]},
            "faa_state": {"path": faa_state_file, "source": "FAA NAS status snapshot", "url": FAA_URL, "as_of": str(faa_state.get("updated_utc") or "")},
        },
        "entries": ledger.entries,
    }
    trace_json = json.dumps(trace_payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html_doc = "\n".join([
        html_head_and_main,
        f'  <script type="application/json" id="story-data">{story_data_json}</script>',
        f'  <script type="application/json" id="trace">{trace_json}</script>',
        '  <script src="/stories/thanksgiving/story.js" defer></script>',
        "</body>",
        "</html>",
        "",
    ])
    verify_story_numbers(html_doc, tsa=tsa, faa=faa, target_year=target_year)
    verify_story_date_windows(html_doc, tsa=tsa, faa_hist=faa_hist, target_year=target_year)
    return html_doc, trace_payload


def build_stories_index() -> str:
    canonical = f"{SITE_URL}/stories/"
    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Air Travel Desk", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Stories", "item": canonical},
        ],
    }
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        "  <title>Data stories | Air Travel Desk</title>",
        '  <meta name="description" content="Interactive reporting built from TSA checkpoint travel counts and FAA airport status archives.">',
        f'  <link rel="canonical" href="{_esc(canonical)}">',
        '  <meta name="theme-color" content="#080b0f" media="(prefers-color-scheme: dark)">',
        '  <meta name="theme-color" content="#f6f4ef" media="(prefers-color-scheme: light)">',
        '  <link rel="icon" href="/favicon.svg" type="image/svg+xml">',
        '  <link rel="icon" href="/favicon.png" type="image/png">',
        f"  {bap.THEME_SNIPPET}",
        '  <script src="/theme.js" defer></script>',
        '  <script src="/watch.js" defer></script>',
        '  <link rel="stylesheet" href="/tokens.css">',
        '  <link rel="stylesheet" href="/style.css">',
        '  <link rel="stylesheet" href="/stories/thanksgiving/story.css">',
        bap._json_ld_script(breadcrumb_ld),
        "</head>",
        '<body class="page-story">',
        _header(),
        '  <div class="container">',
        '  <main id="main-content" class="story-main">',
        '    <p class="crumb"><a href="/">Live board</a> <span aria-hidden="true">/</span> Stories</p>',
        '    <header class="story-head">',
        '      <p class="story-kicker">Air Travel Desk reporting</p>',
        '      <h1 class="story-title">Interactive data stories</h1>',
        '      <p class="story-dek">Visual reporting built directly from public TSA checkpoint volumes and Air Travel Desk FAA status archives, updated on every site build.</p>',
        '    </header>',
        '    <ul class="story-index-list">',
        '      <li class="story-index-item">',
        '        <a href="/stories/thanksgiving">The Thanksgiving rush: TSA passenger counts and where FAA delays start</a>',
        '        <p>Weekday-aligned TSA checkpoint totals across Thanksgiving week against prior years, paired with early FAA hourly delay readings across the 100 busiest US airports.</p>',
        '      </li>',
        '    </ul>',
        '  </main>',
        '  </div>',
        _footer(),
        "</body>",
        "</html>",
        "",
    ])


def update_sitemap(sitemap_path: Path, build_date: str) -> None:
    block = "\n".join([
        f"  {SITEMAP_BEGIN}",
        f"  <url><loc>{SITE_URL}/stories/</loc><lastmod>{build_date}</lastmod></url>",
        f"  <url><loc>{SITE_URL}/stories/thanksgiving</loc><lastmod>{build_date}</lastmod></url>",
        f"  {SITEMAP_END}",
    ])
    bap.update_sitemap_block(sitemap_path, block, SITEMAP_BEGIN, SITEMAP_END)


def _sync_assets(out_dir: Path) -> None:
    src_dir = ROOT / "stories" / "thanksgiving"
    dst_dir = out_dir / "thanksgiving"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in ("story.css", "story.js"):
        src = src_dir / name
        dst = dst_dir / name
        if src.is_file() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)


def build_all(
    *,
    data_dir: Path,
    readings_dir: Path,
    out_dir: Path,
    sitemap_path: Optional[Path] = None,
    now: Optional[datetime] = None,
    no_fetch: bool = False,
    force_fetch: bool = False,
    fixture_dir: Optional[Path] = None,
    fetcher: Optional[Callable[[str], str]] = None,
) -> dict[str, Any]:
    now_dt = now or datetime.now(timezone.utc)
    tsa, tsa_file = ensure_tsa_history(
        data_dir=data_dir,
        readings_dir=readings_dir,
        now_dt=now_dt,
        no_fetch=no_fetch,
        force_fetch=force_fetch,
        fixture_dir=fixture_dir,
        fetcher=fetcher,
    )
    faa_hist_p, faa_hist, faa_state_p, faa_state = _choose_faa_files(data_dir, readings_dir)
    if not faa_hist or not faa_hist.get("hours"):
        raise FileNotFoundError(f"Missing FAA hourly archive in {readings_dir} or {data_dir}")

    page_html, trace_payload = build_thanksgiving_story(
        tsa=tsa,
        tsa_file=tsa_file,
        faa_hist=faa_hist,
        faa_hist_file=_rel_file_label(faa_hist_p),
        faa_state=faa_state,
        faa_state_file=_rel_file_label(faa_state_p),
        now_dt=now_dt,
    )
    tg_dir = out_dir / "thanksgiving"
    tg_dir.mkdir(parents=True, exist_ok=True)
    _sync_assets(out_dir)
    _write_atomic(tg_dir / "index.html", page_html)
    _write_atomic(out_dir / "index.html", build_stories_index())
    if sitemap_path is not None:
        update_sitemap(sitemap_path, now_dt.strftime("%Y-%m-%d"))
    return trace_payload


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--readings", default=str(ROOT / "readings"))
    ap.add_argument("--out", default=str(ROOT / "stories"))
    ap.add_argument("--sitemap", default=None, help="Path to sitemap.xml (default: sitemap.xml when --out is default)")
    ap.add_argument("--now", default=None, help="Override build UTC timestamp (ISO)")
    ap.add_argument("--no-fetch", action="store_true", help="Do not fetch TSA from network")
    ap.add_argument("--force-fetch", action="store_true", help="Ignore 6h TSA cache freshness")
    ap.add_argument("--tsa-fixture-dir", default=None, help="Read TSA tsa-*.html fixtures from directory")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    if args.sitemap is not None:
        sitemap: Optional[Path] = Path(args.sitemap) if args.sitemap else None
    elif out_dir.resolve() == (ROOT / "stories").resolve():
        sitemap = ROOT / "sitemap.xml"
    else:
        sitemap = None

    now_dt = _parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if now_dt is None:
        ap.error(f"Invalid --now ISO timestamp: {args.now}")

    trace = build_all(
        data_dir=Path(args.data),
        readings_dir=Path(args.readings),
        out_dir=out_dir,
        sitemap_path=sitemap,
        now=now_dt,
        no_fetch=args.no_fetch,
        force_fetch=args.force_fetch,
        fixture_dir=Path(args.tsa_fixture_dir) if args.tsa_fixture_dir else None,
    )
    print(f"build_stories: wrote {out_dir / 'thanksgiving' / 'index.html'} ({len(trace['entries'])} traced entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
