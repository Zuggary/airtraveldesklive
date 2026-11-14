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
import zlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from desk import feeds
from desk.airports import AIRPORTS

SOURCE = "adsb.lol (ODbL)"
URL_TEMPLATE = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/40"
MAX_AIRPORTS = 3
MAX_TRAIL = 16
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
            "seen_pos": ac.get("seen_pos") if isinstance(ac.get("seen_pos"), (int, float)) else 0.0,
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

    def update(self, code: str, aircraft: list[dict[str, Any]], ts: Optional[float] = None) -> None:
        ts = time.time() if ts is None else ts
        n = self.polls.get(code, 0) + 1
        self.polls[code] = n
        self.last_poll[code] = self.tick
        book = self.ac.setdefault(code, {})
        for a in aircraft:
            rec = book.get(a["hex"])
            if rec is None:
                rec = book[a["hex"]] = {"trail": [], "meta": []}
            rec.update({k: a.get(k) for k in ("callsign", "alt_baro", "gs", "track")})
            rec["last_n"] = n
            pt = [round(a["lon"], 5), round(a["lat"], 5)]
            if not rec["trail"] or rec["trail"][-1] != pt:
                rec["trail"].append(pt)
                rec["meta"].append([ts - max(0.0, min(60.0, float(a.get("seen_pos") or 0.0))), a.get("alt_baro")])
                del rec["trail"][:-self.max_trail]
                del rec["meta"][:-self.max_trail]
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
    point_ts: Optional[float] = None,
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
            tracker.update(code, acs, point_ts)
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


# ---------- AN10: national sample (regional circles around the 6 busiest hubs) ----------
NATIONAL_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
NATIONAL_DIST_NM = 250
NATIONAL_CIRCLES = 6
NATIONAL_EVERY = 2          # desk polls between national fetches
NATIONAL_TRAIL = 16
NATIONAL_MAX = 400          # aircraft written to national.json (and drawn)
NATIONAL_DROP_AFTER = 3     # national fetches an aircraft may stay unseen


def national_due(poll_idx: int) -> bool:
    """National fetch on every 2nd desk poll, starting with the first (poll 0)."""
    return poll_idx % NATIONAL_EVERY == 0


def regional_circles(limit: int = NATIONAL_CIRCLES) -> list[tuple[str, float, float]]:
    """The circles to fetch: the busiest hubs in AIRPORTS order (first entries are the busiest)."""
    return [(c, AIRPORTS[c][1], AIRPORTS[c][2]) for c in list(AIRPORTS)[: max(0, min(limit, NATIONAL_CIRCLES))]]


def _sample_key(hex_code: str) -> int:
    return zlib.crc32(hex_code.encode("ascii", "ignore"))


class NationalTracker:
    """Last NATIONAL_TRAIL positions per aircraft over all regional circles. Memory only."""

    def __init__(self, max_trail: int = NATIONAL_TRAIL, drop_after: int = NATIONAL_DROP_AFTER) -> None:
        self.max_trail = max_trail
        self.drop_after = drop_after
        self.n = 0
        self.ac: dict[str, dict[str, Any]] = {}

    def update(self, aircraft: list[dict[str, Any]], fetch_ts: float, clock_offset: Optional[float] = None) -> None:
        """One national fetch. Circles overlap, so the same hex can appear twice: the last one wins."""
        self.n += 1
        seen: dict[str, dict[str, Any]] = {}
        for a in aircraft:
            seen[a["hex"]] = a
        for hx, a in seen.items():
            rec = self.ac.get(hx)
            if rec is None:
                rec = self.ac[hx] = {"trail": [], "meta": []}
            rec.update({k: a.get(k) for k in ("alt_baro", "gs", "track")})
            rec["last_n"] = self.n
            # fix time = fetch time minus the age of the position, never in the future
            rec["t"] = fetch_ts - max(0.0, min(60.0, float(a.get("seen_pos") or 0.0)))
            pt = [round(a["lon"], 4), round(a["lat"], 4)]
            if not rec["trail"] or rec["trail"][-1] != pt:
                rec["trail"].append(pt)
                rec["meta"].append([rec["t"] if clock_offset is None else rec["t"] + clock_offset, a.get("alt_baro")])
                del rec["trail"][: -self.max_trail]
                del rec["meta"][: -self.max_trail]
        for hx in [h for h, r in self.ac.items() if self.n - r["last_n"] >= self.drop_after]:
            del self.ac[hx]

    def load(self, payload: Optional[dict[str, Any]], max_age_s: float = 1200.0, now_ts: Optional[float] = None) -> int:
        """Web job: rebuild the tracker from the previously published national.json (written with meta=True).
        Aircraft older than max_age_s, or without matching trail and meta, are left out. Returns how many were kept."""
        if not isinstance(payload, dict):
            return 0
        now = time.time() if now_ts is None else now_ts
        self.n = int(payload.get("n") or 0)
        kept = 0
        for a in payload.get("aircraft") or []:
            try:
                trail, meta, t = a["trail"], a["meta"], float(a["t"])
                if not a.get("hex") or len(trail) != len(meta) or not trail or now - t > max_age_s:
                    continue
                self.ac[a["hex"]] = {"trail": [list(p) for p in trail], "meta": [list(m) for m in meta],
                                     "alt_baro": a.get("alt_baro"), "gs": a.get("gs"), "track": a.get("track"),
                                     "t": t, "last_n": int(a.get("ln", self.n))}
                kept += 1
            except (KeyError, TypeError, ValueError):
                continue
        return kept

    def snapshot(self, cap: int = NATIONAL_MAX, meta: bool = False, keep: Optional[set] = None) -> list[dict[str, Any]]:
        """At most `cap` aircraft. Airborne first; a stable hash of the hex makes the sample fair, not alphabetical."""
        keep = keep or set()
        rows = sorted(self.ac.items(), key=lambda kv: (kv[0] not in keep, kv[1].get("alt_baro") == "ground", _sample_key(kv[0])))
        out = []
        for hx, r in rows[: max(0, cap)]:
            out.append({
                "hex": hx, "alt_baro": r.get("alt_baro"), "gs": r.get("gs"), "track": r.get("track"),
                "t": round(r["t"], 1), "trail": [list(p) for p in r["trail"]],
            })
            if meta:
                out[-1]["meta"] = [[int(round(m[0])), m[1]] for m in r["meta"]]
                out[-1]["ln"] = r["last_n"]
        return out


def update_national(
    out_dir: Path | str,
    ntracker: NationalTracker,
    poll_idx: int,
    replay: bool = False,
    fetcher: Optional[Callable[[str], str]] = None,
    now_ts: Optional[float] = None,
    pause: float = 1.0,
    poll_sec: float = 60.0,
    point_ts: Optional[float] = None,
) -> list[tuple[str, Exception]]:
    """Every 2nd poll: GET up to 6 circles (250 nm, 1 s apart), update trails, write national.json."""
    if not national_due(poll_idx):
        return []
    now = time.time() if now_ts is None else now_ts
    errors: list[tuple[str, Exception]] = []
    got: list[dict[str, Any]] = []
    ok = 0
    for i, (code, lat, lon) in enumerate(regional_circles()):
        if i and not replay and pause > 0:
            time.sleep(pause)
        try:
            if replay:
                raw = (FIXTURES / f"adsb-near-{min(ntracker.n, 2) + 1}.json").read_text(encoding="utf-8")
                got.extend(a for a in parse_near(raw) if distance_nm(lat, lon, a["lat"], a["lon"]) <= NATIONAL_DIST_NM)
            else:
                url = NATIONAL_URL.format(lat=lat, lon=lon, dist=NATIONAL_DIST_NM)
                got.extend(parse_near((fetcher or feeds.fetch)(url)))
            ok += 1
        except Exception as exc:  # one circle failing must not hide the others
            errors.append((code, exc))
    if ok == 0:
        return errors          # keep the old file; the page ignores it once it is too old
    ntracker.update(got, now, None if point_ts is None else point_ts - now)
    payload = {
        "aircraft": ntracker.snapshot(), "source": SOURCE, "fetched_utc": _iso(now),
        "interval_s": poll_sec * NATIONAL_EVERY, "circles": [c for c, _, _ in regional_circles()],
        "tracked": len(ntracker.ac),
    }
    _atomic_write(Path(out_dir) / "national.json", json.dumps(payload).encode("utf-8"))
    return errors


# ---------- Website job: one national fetch per 5-minute run ----------
WEB_TRAIL = 8                 # 8 fixes, 5 minutes apart, is a 40-minute trail
WEB_DROP_AFTER = 3            # runs an aircraft may stay unseen
WEB_MAX_CALLS = 6             # adsb.lol GETs per run
WEB_EVERY_SEC = 300.0         # the page dead-reckons for at most this long, then snaps to the next file


def web_national(out_dir: Path | str, prev: Optional[dict[str, Any]], fetcher: Optional[Callable[[str], str]] = None,
                 now_ts: Optional[float] = None, pause: float = 1.0) -> tuple[NationalTracker, int, list[tuple[str, Exception]]]:
    """GET up to 6 regional circles, extend the trails from the previous published national.json, write national.json.
    Returns (tracker, circles that answered, errors). With no answer the old file stays and the tracker holds only old data."""
    now = time.time() if now_ts is None else now_ts
    nt = NationalTracker(max_trail=WEB_TRAIL, drop_after=WEB_DROP_AFTER)
    nt.load(prev, now_ts=now)
    errors: list[tuple[str, Exception]] = []
    got: list[dict[str, Any]] = []
    ok = 0
    for i, (code, lat, lon) in enumerate(regional_circles(WEB_MAX_CALLS)):
        if i and pause > 0:
            time.sleep(pause)
        url = NATIONAL_URL.format(lat=lat, lon=lon, dist=NATIONAL_DIST_NM)
        for attempt in (1, 2):                     # adsb.lol answers 429 when asked fast: wait once, try once more
            try:
                got.extend(parse_near((fetcher or feeds.fetch)(url)))
                ok += 1
                break
            except Exception as exc:
                if attempt == 2 or "429" not in str(exc) or pause <= 0:
                    errors.append((code, exc))
                    break
                time.sleep(4.0)
    if ok == 0:
        return nt, 0, errors
    nt.update(got, now)
    from desk.airports import BUSIEST_30
    near_hub = {hx for hx, r in nt.ac.items() if r["trail"] and r.get("alt_baro") != "ground" and any(
        distance_nm(AIRPORTS[c][1], AIRPORTS[c][2], r["trail"][-1][1], r["trail"][-1][0]) <= WEB_HUB_NM for c in BUSIEST_30)}
    payload = {
        "aircraft": nt.snapshot(WEB_CAP, meta=True, keep=near_hub), "source": SOURCE, "fetched_utc": _iso(now), "n": nt.n,
        "interval_s": WEB_EVERY_SEC, "circles": [c for c, _, _ in regional_circles(WEB_MAX_CALLS)], "tracked": len(nt.ac),
    }
    _atomic_write(Path(out_dir) / "national.json", json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return nt, ok, errors


WEB_CAP = 400
WEB_HUB_NM = 30.0             # aircraft this close to a busiest-30 hub are always kept, so holding can be judged
