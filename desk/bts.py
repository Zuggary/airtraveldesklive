"""BTS on-time statistics for the desk. Standard library only (zipfile, csv).

Source: transtats.bts.gov monthly "Reporting Carrier On-Time Performance" zip files.
Downloads go to ~/factory-scratch/an-bts-cache/ (never the repo). The CSV inside a zip is
streamed; nothing is extracted to disk.

Definitions (also written into bts.json):
  on-time %   = flights with ArrDel15 == 0, divided by flights that were not cancelled and not
                diverted and have an ArrDel15 value (arrival delay under 15 minutes).
  cancel %    = Cancelled == 1 flights divided by all flights in the file.
  airport     = arrivals at that airport (column Dest), same on-time rule.
  carrier     = Reporting_Airline.
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from desk.airports import canonical_code
from desk.feeds import USER_AGENT

PREZIP = ("https://transtats.bts.gov/PREZIP/"
          "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{y}_{m}.zip")
CACHE_DIR = Path(os.environ.get("AN_BTS_CACHE", str(Path.home() / "factory-scratch" / "an-bts-cache")))
CHECK_EVERY_SEC = 24 * 3600.0
MAX_MONTHS_BACK = 8
FIX_DIR = Path(__file__).resolve().parent.parent / "fixtures"

DEFINITION = ("On-time = arrival less than 15 minutes late (ArrDel15 = 0), as a share of flights that were "
              "not cancelled and not diverted. Cancelled = share of all scheduled flights in the file. "
              "Airport figures count arrivals at that airport (Dest). Carrier = reporting airline.")

# Code -> display name for current US reporting carriers. A label only; unknown codes show as the code.
CARRIER_NAMES = {
    "AA": "American", "DL": "Delta", "UA": "United", "WN": "Southwest", "B6": "JetBlue",
    "AS": "Alaska", "NK": "Spirit", "F9": "Frontier", "G4": "Allegiant", "HA": "Hawaiian",
    "SY": "Sun Country", "MQ": "Envoy", "OO": "SkyWest", "YX": "Republic", "9E": "Endeavor",
    "OH": "PSA", "YV": "Mesa", "QX": "Horizon", "C5": "CommuteAir", "ZW": "Air Wisconsin",
    "G7": "GoJet", "CP": "Compass", "PT": "Piedmont", "EV": "ExpressJet", "VX": "Virgin America",
}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(y: int, m: int) -> str:
    return f"{MONTHS[m - 1]} {y}"


def url_for(y: int, m: int) -> str:
    return PREZIP.format(y=y, m=m)  # month is not zero padded in BTS file names


def months_back(y: int, m: int, limit: int = MAX_MONTHS_BACK) -> Iterable[tuple[int, int]]:
    for _ in range(limit):
        yield y, m
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def head_ok(url: str, timeout: int = 30) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return False
        raise


def find_latest(now_ts: float, head: Callable[[str], bool] = head_ok) -> Optional[tuple[int, int]]:
    """HEAD-probe month files backwards from the current month; first that exists wins."""
    now = datetime.fromtimestamp(now_ts, timezone.utc)
    for y, m in months_back(now.year, now.month):
        if head(url_for(y, m)):
            return y, m
    return None


def download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, part.open("wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink()


def _pct(num: int, den: int) -> Optional[float]:
    return round(num / den * 100, 2) if den else None


class _Tally:
    __slots__ = ("flights", "cancelled", "done", "ontime")

    def __init__(self) -> None:
        self.flights = self.cancelled = self.done = self.ontime = 0


def compute_zip(zip_path: Path | str) -> dict[str, Any]:
    """Stream the CSV inside the zip and tally nation, per-Dest airport and per-carrier counts."""
    nation = _Tally()
    airports: dict[str, _Tally] = {}
    carriers: dict[str, _Tally] = {}
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("no csv in zip")
        with zf.open(names[0]) as raw:
            rd = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            head = next(rd)
            ix = {name: i for i, name in enumerate(head)}
            ic, idv, ia = ix["Cancelled"], ix["Diverted"], ix["ArrDel15"]
            iy, im = ix["Year"], ix["Month"]
            icar, idest = ix["Reporting_Airline"], ix["Dest"]
            year = month = None
            for row in rd:
                if len(row) <= max(ic, idv, ia, icar, idest):
                    continue
                if year is None:
                    year, month = int(row[iy]), int(row[im])
                car = carriers.get(row[icar])
                if car is None:
                    car = carriers[row[icar]] = _Tally()
                nation.flights += 1
                car.flights += 1
                if row[ic] in ("1", "1.00"):
                    nation.cancelled += 1
                    car.cancelled += 1
                    continue
                if row[idv] in ("1", "1.00") or row[ia] == "":
                    continue
                code = canonical_code(row[idest])
                ap = airports.get(code)
                if ap is None:
                    ap = airports[code] = _Tally()
                ot = 1 if row[ia] in ("0", "0.00") else 0
                for t in (nation, car, ap):
                    t.done += 1
                    t.ontime += ot
    return {"year": year, "month": month, "nation": nation, "airports": airports, "carriers": carriers}


def build_output(cur: dict[str, Any], ly: dict[str, Any], fetched_utc: str) -> dict[str, Any]:
    n, ln = cur["nation"], ly["nation"]
    airports = {}
    for code, t in cur["airports"].items():
        lt = ly["airports"].get(code)
        airports[code] = {
            "ontime": _pct(t.ontime, t.done),
            "ly_ontime": _pct(lt.ontime, lt.done) if lt else None,
            "flights": t.done,
        }
    carriers = []
    for code, t in cur["carriers"].items():
        lt = ly["carriers"].get(code)
        carriers.append({
            "code": code,
            "name": CARRIER_NAMES.get(code, code),
            "ontime": _pct(t.ontime, t.done),
            "ly_ontime": _pct(lt.ontime, lt.done) if lt else None,
            "cancel": _pct(t.cancelled, t.flights),
            "ly_cancel": _pct(lt.cancelled, lt.flights) if lt else None,
            "flights": t.flights,
        })
    carriers.sort(key=lambda c: (-c["flights"], c["code"]))
    return {
        "month": [cur["year"], cur["month"]],
        "month_label": month_label(cur["year"], cur["month"]),
        "ly_month_label": month_label(ly["year"], ly["month"]),
        "definition": DEFINITION,
        "nation": {
            "ontime": _pct(n.ontime, n.done), "ly_ontime": _pct(ln.ontime, ln.done),
            "cancel": _pct(n.cancelled, n.flights), "ly_cancel": _pct(ln.cancelled, ln.flights),
            "flights": n.flights, "ly_flights": ln.flights,
        },
        "airports": airports,
        "carriers": carriers,
        "source": "BTS",
        "fetched_utc": fetched_utc,
    }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _load(out: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads((out / "bts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def maybe_update(
    out_dir: Path | str,
    now_ts: Optional[float] = None,
    replay: bool = False,
    cache_dir: Optional[Path] = None,
    head: Callable[[str], bool] = head_ok,
    fetch_zip: Callable[[str, Path], None] = download,
    attempts: Optional[dict[str, float]] = None,
) -> str:
    """Check at most once a day; recompute only when a newer month exists. Returns skip|same|ok."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = time.time() if now_ts is None else now_ts
    if replay:
        src = FIX_DIR / "bts.json"
        if src.is_file() and not (out / "bts.json").is_file():
            _write_atomic(out / "bts.json", src.read_bytes())
            return "ok"
        return "skip"
    old = _load(out)
    if old:
        try:
            checked = datetime.strptime(old.get("checked_utc") or old["fetched_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            if 0 <= now - checked < CHECK_EVERY_SEC:
                return "skip"
        except (KeyError, ValueError):
            pass
    if attempts is not None:
        last = attempts.get("bts")
        if last is not None and 0 <= now - last < 3600.0:
            return "skip"
        attempts["bts"] = now
    latest = find_latest(now, head)
    if latest is None:
        raise RuntimeError("no BTS month file found")
    if old and old.get("month") == list(latest):
        old["checked_utc"] = _iso(now)
        _write_atomic(out / "bts.json", json.dumps(old, indent=2).encode("utf-8"))
        return "same"
    y, m = latest
    cdir = cache_dir or CACHE_DIR
    stats = []
    keep = []
    for yy in (y, y - 1):
        path = cdir / f"otp_{yy}_{m}.zip"
        if not path.is_file():
            fetch_zip(url_for(yy, m), path)
        keep.append(path)
        stats.append(compute_zip(path))
    for stale in cdir.glob("otp_*.zip"):
        if stale not in keep:
            stale.unlink()
    result = build_output(stats[0], stats[1], _iso(now))
    result["checked_utc"] = _iso(now)
    _write_atomic(out / "bts.json", json.dumps(result, indent=2).encode("utf-8"))
    return "ok"
