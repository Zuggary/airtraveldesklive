"""Build data/places.json: hotels and car-rental places within 5 km of each busiest-30 airport (AN9).

Source: OpenStreetMap through the Overpass API. One query per airport, 2 seconds apart. The data job
calls this on every run, but it only fetches when the cached places.json is older than 7 days.
Viewer browsers never call Overpass; the page reads data/places.json from its own origin.
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk.airports import AIRPORTS, BUSIEST_30, BUSIEST_100  # noqa: E402
from desk.feeds import USER_AGENT  # noqa: E402

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Same API, used only when the main server fails (it often answers 502 or times out).
OVERPASS_MIRRORS = ("https://overpass.kumi.systems/api/interpreter",)
RADIUS_M = 5000
MAX_HOTELS = 8
MAX_CARS = 6
PAUSE_SEC = 2.0
MAX_AGE_SEC = 7 * 86400.0
RETRY_AFTER_SEC = 6 * 3600.0   # an incomplete file is retried at most every 6 hours
RUN_BUDGET_SEC = 540.0         # stop starting new queries after 9 minutes
SOURCE = "© OpenStreetMap contributors"


def build_query(lat: float, lon: float, radius_m: int = RADIUS_M) -> str:
    around = f"(around:{radius_m},{lat},{lon})"
    return (
        "[out:json][timeout:50];("
        f'nwr["tourism"~"^(hotel|motel)$"]{around};'
        f'nwr["amenity"="car_rental"]{around};'
        ");out center tags;"
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def clean_website(tags: dict[str, Any]) -> Optional[str]:
    """The place's own website, only when it is an http(s) URL."""
    for key in ("website", "contact:website"):
        raw = str(tags.get(key) or "").strip()
        if not raw:
            continue
        # OSM allows several values separated by semicolons: take the first.
        raw = raw.split(";")[0].strip()
        parts = urllib.parse.urlsplit(raw)
        if parts.scheme in ("http", "https") and parts.netloc and " " not in raw:
            return raw
    return None


def parse_places(overpass_json: str | dict, lat: float, lon: float) -> dict[str, list[dict[str, Any]]]:
    """Overpass JSON -> {"hotels": [...], "cars": [...]} sorted by distance, with name, km and website."""
    data = json.loads(overpass_json) if isinstance(overpass_json, str) else overpass_json
    hotels: list[dict[str, Any]] = []
    cars: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for el in (data or {}).get("elements") or []:
        tags = el.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        if not name:
            continue
        plat = el.get("lat", (el.get("center") or {}).get("lat"))
        plon = el.get("lon", (el.get("center") or {}).get("lon"))
        if not isinstance(plat, (int, float)) or not isinstance(plon, (int, float)):
            continue
        km = haversine_km(lat, lon, plat, plon)
        if km > RADIUS_M / 1000.0 + 0.2:
            continue
        if tags.get("amenity") == "car_rental":
            bucket, kind = cars, "cars"
        elif tags.get("tourism") in ("hotel", "motel"):
            bucket, kind = hotels, "hotels"
        else:
            continue
        key = (kind, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        item: dict[str, Any] = {"name": name, "km": round(km, 1)}
        site = clean_website(tags)
        if site:
            item["website"] = site
        bucket.append(item)
    hotels.sort(key=lambda p: (p["km"], p["name"]))
    cars.sort(key=lambda p: (p["km"], p["name"]))
    return {"hotels": hotels[:MAX_HOTELS], "cars": cars[:MAX_CARS]}


def fetch_overpass(query: str, timeout: int = 60) -> str:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last: Exception = RuntimeError("no server")
    for url in (OVERPASS_URL,) + OVERPASS_MIRRORS:
        req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as exc:
            last = exc
    raise last


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_existing(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_fresh(existing: dict[str, Any], now: float, max_age: float = MAX_AGE_SEC) -> bool:
    try:
        fetched = datetime.strptime(existing["fetched_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (KeyError, ValueError, TypeError):
        return False
    complete = len(existing.get("airports") or {}) >= len(BUSIEST_30)
    limit = max_age if complete else RETRY_AFTER_SEC
    return 0 <= now - fetched < limit


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"), ensure_ascii=False)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def update(out_dir: Path, now: Optional[float] = None, fetcher: Callable[[str], str] = fetch_overpass,
           pause: float = PAUSE_SEC, force: bool = False) -> str:
    """Returns 'skip' (fresh), 'ok' (all airports fetched) or 'partial' (some kept from the old file)."""
    out = Path(out_dir)
    path = out / "places.json"
    now = time.time() if now is None else now
    existing = load_existing(path)
    if not force and is_fresh(existing, now):
        return "skip"
    old = existing.get("airports") or {}
    airports: dict[str, Any] = dict(old)
    # An incomplete file only asks again for the airports it lacks.
    targets = [c for c in BUSIEST_30 if c not in old] if existing and len(old) < len(BUSIEST_30) else list(BUSIEST_30)
    failed = 0
    started = time.time()
    for i, code in enumerate(targets):
        _, lat, lon = AIRPORTS[code]
        if i and pause > 0:
            time.sleep(pause)
        if i and time.time() - started > RUN_BUDGET_SEC:
            failed += 1
            continue
        try:
            try:
                raw = fetcher(build_query(lat, lon))
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 504):
                    raise
                time.sleep(max(pause, 10.0))
                raw = fetcher(build_query(lat, lon))
            airports[code] = parse_places(raw, lat, lon)
        except Exception as exc:  # one airport failing keeps its older data
            failed += 1
            print(f"places {code}: {type(exc).__name__}: {exc}", file=sys.stderr)
    # A run that fetched nothing new must not reset the clock.
    if failed == len(targets):
        return "error"
    write_json(path, {"fetched_utc": _iso(now), "source": SOURCE, "radius_km": RADIUS_M / 1000.0, "airports": airports})
    return "ok" if not failed else "partial"


# ---- AN23: the 70 airports after the first 30, in a separate file and a slower, gentler step ----

MORE_FILE = "places-more.json"
MORE_BATCH = 3                 # airports per run (an Overpass query can take 30 s; the step also has a 3 minute timeout in the workflow)
MORE_MIN_GAP_SEC = 3600.0      # at least an hour between runs that ask Overpass
MORE_PAUSE_SEC = 5.0           # between two queries
MORE_MAX_AGE_SEC = 7 * 86400.0 # an airport is asked again after a week


def _parse_iso(text: Any) -> Optional[float]:
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def update_more(out_dir: Path, now: Optional[float] = None, fetcher: Callable[[str], str] = fetch_overpass,
                pause: float = MORE_PAUSE_SEC, batch: int = MORE_BATCH, sleep: Callable[[float], None] = time.sleep) -> str:
    """Fetch places for a few of the 70 airports after the first 30. One query at a time, with a pause.

    Each run takes at most `batch` airports: first those never fetched, then the oldest ones older than a week.
    A run is skipped when the last attempt was less than an hour ago. Failures keep the older data for that airport.
    Returns 'skip', 'idle' (nothing is due), 'ok', 'partial' or 'error'."""
    out = Path(out_dir)
    path = out / MORE_FILE
    now = time.time() if now is None else now
    existing = load_existing(path)
    last_try = _parse_iso(existing.get("attempt_utc"))
    if last_try is not None and 0 <= now - last_try < MORE_MIN_GAP_SEC:
        return "skip"
    old: dict[str, Any] = dict(existing.get("airports") or {})
    pool = [c for c in BUSIEST_100 if c not in BUSIEST_30]

    def age_key(code: str) -> float:
        got = _parse_iso((old.get(code) or {}).get("fetched_utc"))
        return -1.0 if got is None else got

    due = [c for c in pool if c not in old or now - age_key(c) >= MORE_MAX_AGE_SEC]
    due.sort(key=lambda c: (age_key(c), pool.index(c)))
    targets = due[:batch]
    if not targets:
        return "idle"
    failed = 0
    for i, code in enumerate(targets):
        _, lat, lon = AIRPORTS[code]
        if i and pause > 0:
            sleep(pause)
        try:
            raw = fetcher(build_query(lat, lon))
            got = parse_places(raw, lat, lon)
            got["fetched_utc"] = _iso(now)
            old[code] = got
        except Exception as exc:
            failed += 1
            print(f"places-more {code}: {type(exc).__name__}: {exc}", file=sys.stderr)
    # The attempt time is written even on failure, so a down server is not asked again for an hour.
    write_json(path, {"attempt_utc": _iso(now), "source": SOURCE, "radius_km": RADIUS_M / 1000.0, "airports": old})
    return "error" if failed == len(targets) else ("ok" if not failed else "partial")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--more", action="store_true", help="the 70 airports after the first 30 (separate file, small batches)")
    a = ap.parse_args()
    if a.more:
        print(f"{MORE_FILE}: {update_more(Path(a.out))}")
        return 0
    res = update(Path(a.out), force=a.force)
    print(f"places.json: {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
