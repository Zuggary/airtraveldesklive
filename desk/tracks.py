"""Aircraft near airports with a ground stop or ground delay (adsb.lol, ODbL). Standard library only.

One request per selected airport per poll (at most 3 airports). The Tracker keeps positions in memory
across polls to build trails; the page only reads <out>/tracks.json.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from desk import feeds
from desk.airports import AIRPORTS

SOURCE = "adsb.lol (ODbL)"
URL_TEMPLATE = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/40"
MAX_AIRPORTS = 3
MAX_TRAIL = 10
DROP_AFTER = 3          # polls an aircraft may stay unseen before it is dropped
MAX_AIRCRAFT = 120      # per airport in tracks.json
RADIUS_NM = 40.0
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_HOURS_RE = re.compile(r"(\d+)\s*hours?", re.IGNORECASE)
_MINS_RE = re.compile(r"(\d+)\s*minutes?", re.IGNORECASE)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _minutes(text: str) -> int:
    if not text:
        return 0
    h = _HOURS_RE.search(text)
    m = _MINS_RE.search(text)
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def select_airports(events: list[dict[str, Any]], limit: int = MAX_AIRPORTS) -> list[str]:
    """Airports with an active ground stop first, then ground delays by longest average delay.

    Ties keep the order of the events. Airports not in desk.airports are skipped.
    """
    stops: list[str] = []
    delays: list[tuple[int, int, str]] = []
    for i, ev in enumerate(events):
        code = str(ev.get("airport") or "").upper()
        if code not in AIRPORTS:
            continue
        kind = ev.get("kind")
        if kind == "ground_stop":
            if code not in stops:
                stops.append(code)
        elif kind == "ground_delay":
            avg = _minutes(str((ev.get("fields") or {}).get("avg") or ""))
            delays.append((-avg, i, code))
    out = list(stops)
    for _, _, code in sorted(delays):
        if code not in out:
            out.append(code)
    return out[:limit]


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(a)))


def parse_near(json_text: str) -> list[dict[str, Any]]:
    """Parse an adsb.lol lat/lon/dist response into plain aircraft dicts (aircraft without a position are dropped)."""
    if not json_text or not json_text.strip():
        return []
    data = json.loads(json_text)
    out: list[dict[str, Any]] = []
    for ac in data.get("ac") or []:
        hex_code = str(ac.get("hex") or "").strip().lower()
        lat, lon = ac.get("lat"), ac.get("lon")
        if not hex_code or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        out.append({
            "hex": hex_code,
            "callsign": str(ac.get("flight") or "").strip(),
            "alt_baro": ac.get("alt_baro"),
            "gs": ac.get("gs"),
            "track": ac.get("track"),
            "lat": float(lat),
            "lon": float(lon),
        })
    return out


class Tracker:
    """Keeps the last MAX_TRAIL positions per aircraft per airport across polls."""

    def __init__(self, max_trail: int = MAX_TRAIL, drop_after: int = DROP_AFTER) -> None:
        self.max_trail = max_trail
        self.drop_after = drop_after
        self.polls: dict[str, int] = {}                  # successful polls per airport
        self.last_poll: dict[str, int] = {}              # global tick of the last update of each airport
        self.tick = 0
        self.ac: dict[str, dict[str, dict[str, Any]]] = {}

    def begin_poll(self, selected: list[str]) -> None:
        """Call once per desk poll. Airports no longer selected are forgotten after DROP_AFTER polls."""
        self.tick += 1
        for code in list(self.ac):
            if code not in selected and self.tick - self.last_poll.get(code, 0) >= self.drop_after:
                del self.ac[code]
                self.polls.pop(code, None)
                self.last_poll.pop(code, None)

    def update(self, code: str, aircraft: list[dict[str, Any]]) -> None:
        n = self.polls.get(code, 0) + 1
        self.polls[code] = n
        self.last_poll[code] = self.tick
        book = self.ac.setdefault(code, {})
        for a in aircraft:
            rec = book.get(a["hex"])
            if rec is None:
                rec = book[a["hex"]] = {"trail": []}
            rec.update({k: a.get(k) for k in ("callsign", "alt_baro", "gs", "track")})
            rec["last_n"] = n
            pt = [round(a["lon"], 5), round(a["lat"], 5)]
            if not rec["trail"] or rec["trail"][-1] != pt:
                rec["trail"].append(pt)
                del rec["trail"][:-self.max_trail]
        for hx in [h for h, r in book.items() if n - r["last_n"] >= self.drop_after]:
            del book[hx]

    def snapshot(self, code: str) -> list[dict[str, Any]]:
        out = []
        for hx, r in self.ac.get(code, {}).items():
            out.append({
                "hex": hx,
                "callsign": r.get("callsign") or "",
                "alt_baro": r.get("alt_baro"),
                "gs": r.get("gs"),
                "track": r.get("track"),
                "trail": [list(p) for p in r["trail"]],
            })
        out.sort(key=lambda a: a["hex"])
        return out[:MAX_AIRCRAFT]


def _atomic_write(path: Path, data: bytes) -> None:
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


def _fetch_airport(code: str, n: int, replay: bool, fetcher: Optional[Callable[[str], str]]) -> list[dict[str, Any]]:
    _, lat, lon = AIRPORTS[code]
    if replay:
        # Real poll around JFK, replayed in sequence; other airports get the aircraft within 40 nm of them.
        raw = (FIXTURES / f"adsb-near-{min(n, 2) + 1}.json").read_text(encoding="utf-8")
        acs = parse_near(raw)
        return [a for a in acs if distance_nm(lat, lon, a["lat"], a["lon"]) <= RADIUS_NM]
    url = URL_TEMPLATE.format(lat=lat, lon=lon)
    return parse_near((fetcher or feeds.fetch)(url))


def update(
    out_dir: Path | str,
    events: list[dict[str, Any]],
    tracker: Tracker,
    replay: bool = False,
    fetcher: Optional[Callable[[str], str]] = None,
    now_ts: Optional[float] = None,
    pause: float = 1.0,
) -> list[tuple[str, Exception]]:
    """One poll: fetch each selected airport once, update trails, write tracks.json. Returns per-airport errors."""
    now = time.time() if now_ts is None else now_ts
    selected = select_airports(events)
    tracker.begin_poll(selected)
    errors: list[tuple[str, Exception]] = []
    for i, code in enumerate(selected):
        if i and not replay and pause > 0:
            time.sleep(pause)
        try:
            acs = _fetch_airport(code, tracker.polls.get(code, 0), replay, fetcher)
            tracker.update(code, acs)
        except Exception as exc:  # one airport failing must not hide the others
            errors.append((code, exc))
    airports = []
    for code in selected:
        if code not in tracker.ac:
            continue
        _, lat, lon = AIRPORTS[code]
        airports.append({"code": code, "lat": lat, "lon": lon, "aircraft": tracker.snapshot(code)})
    payload = {"airports": airports, "source": SOURCE, "fetched_utc": _iso(now)}
    _atomic_write(Path(out_dir) / "tracks.json", json.dumps(payload).encode("utf-8"))
    return errors
