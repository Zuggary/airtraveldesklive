"""AN11 item 3: aircraft that seem to hold near a hub, from the trails the desk already keeps (adsb.lol).

A pattern in positions, never a cause. An aircraft counts as holding when, within 25 nm of one hub, its last 6 or more
positions over at least 4 minutes turn through 300 degrees or more in total while it stays above 2,000 ft.
The page shows a hub only when 3 or more aircraft hold there at once.

Limit: positions come once per poll (60 s near hubs with an event, 120 s in the national sample), so a tight pattern
flown faster than the poll interval can be missed. A miss shows nothing; it never shows a false hub.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from desk.airports import AIRPORTS, BUSIEST_30
from desk.tracks import distance_nm

RADIUS_NM = 25.0
MIN_POINTS = 6
MIN_SPAN_S = 240.0
MIN_TURN_DEG = 300.0
MIN_ALT_FT = 2000.0
MAX_AGE_S = 420.0        # the newest position must be this fresh
WINDOW_S = 900.0         # only the last 15 minutes count
MIN_SEG_NM = 0.15        # shorter hops are position noise, not a heading
SHOW_MIN = 3             # hubs with fewer holding aircraft are not written

# The website job gets one position every 5 minutes, so it uses a looser profile: 4 or more positions over at least
# 10 minutes inside a 25 minute window. Fewer samples mean it misses more holds; it never reports one that is not there
# in the positions it has. The page says "sampled" beside the note.
STREAM = {"min_points": MIN_POINTS, "min_span": MIN_SPAN_S, "max_age": MAX_AGE_S, "window": WINDOW_S}
WEB = {"min_points": 4, "min_span": 600.0, "max_age": 720.0, "window": 1500.0}

Point = tuple  # (lon, lat, ts, alt_ft_or_None)


def _bearing(a: Point, b: Point) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def total_turn(pts: list[Point]) -> float:
    """Absolute value of the summed signed heading change along the track, in degrees."""
    heads: list[float] = []
    prev: Optional[Point] = None
    for p in pts:
        if prev is not None and distance_nm(prev[1], prev[0], p[1], p[0]) >= MIN_SEG_NM:
            heads.append(_bearing(prev, p))
            prev = p
        elif prev is None:
            prev = p
    total = 0.0
    for h0, h1 in zip(heads, heads[1:]):
        total += (h1 - h0 + 180.0) % 360.0 - 180.0
    return abs(total)


def hub_for(pts: list[Point], hubs: dict[str, tuple[float, float]]) -> Optional[str]:
    last = pts[-1]
    best, best_d = None, RADIUS_NM
    for code, (lat, lon) in hubs.items():
        d = distance_nm(lat, lon, last[1], last[0])
        if d <= best_d:
            best, best_d = code, d
    return best


def is_holding(pts: list[Point], hubs: dict[str, tuple[float, float]], now_ts: float, prof: Optional[dict[str, float]] = None) -> Optional[str]:
    """The hub code when this track looks like a hold, else None."""
    prof = prof or STREAM
    if len(pts) < prof["min_points"] or now_ts - pts[-1][2] > prof["max_age"]:
        return None
    code = hub_for(pts, hubs)
    if code is None:
        return None
    lat, lon = hubs[code]
    run: list[Point] = []
    for p in reversed(pts):                       # newest back: stay near the hub, airborne, in the window
        alt = p[3]
        if (now_ts - p[2] > prof["window"] or distance_nm(lat, lon, p[1], p[0]) > RADIUS_NM
                or not isinstance(alt, (int, float)) or alt <= MIN_ALT_FT):
            break
        run.append(p)
    run.reverse()
    if len(run) < prof["min_points"] or run[-1][2] - run[0][2] < prof["min_span"]:
        return None
    return code if total_turn(run) >= MIN_TURN_DEG else None


def count_by_hub(aircraft: Iterable[dict[str, Any]], hubs: dict[str, tuple[float, float]], now_ts: float, prof: Optional[dict[str, float]] = None) -> dict[str, int]:
    """aircraft: dicts with 'hex' and 'pts' (lon, lat, ts, alt). One count per aircraft."""
    out: dict[str, int] = {}
    seen: set[str] = set()
    for a in aircraft:
        if a["hex"] in seen:
            continue
        seen.add(a["hex"])
        code = is_holding(a["pts"], hubs, now_ts, prof)
        if code:
            out[code] = out.get(code, 0) + 1
    return out


def hub_positions(event_airports: Iterable[str] = ()) -> dict[str, tuple[float, float]]:
    codes = list(BUSIEST_30) + [str(c).upper() for c in event_airports]
    return {c: (AIRPORTS[c][1], AIRPORTS[c][2]) for c in codes if c in AIRPORTS}


def holding_map(counts: dict[str, int], now_ts: float) -> dict[str, dict[str, Any]]:
    as_of = datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {c: {"count": n, "as_of_utc": as_of} for c, n in sorted(counts.items()) if n >= SHOW_MIN}


def from_trackers(tracker: Any, ntracker: Any) -> list[dict[str, Any]]:
    """Merge the near-hub tracker and the national tracker; the longer track wins for a shared hex."""
    best: dict[str, list[Point]] = {}
    sources = []
    for book in getattr(tracker, "ac", {}).values():
        sources.extend(book.items())
    sources.extend(getattr(ntracker, "ac", {}).items())
    for hx, rec in sources:
        trail, meta = rec.get("trail") or [], rec.get("meta") or []
        if len(trail) != len(meta):
            continue
        pts = [(p[0], p[1], m[0], m[1]) for p, m in zip(trail, meta)]
        if len(pts) > len(best.get(hx, [])):
            best[hx] = pts
    return [{"hex": h, "pts": p} for h, p in best.items()]


def synthetic_racetracks(lat: float, lon: float, now_ts: float, n: int = 3) -> list[dict[str, Any]]:
    """SYNTHETIC demo aircraft for replay shots only: n tracks flying a 1.2 nm circle over a hub, 12 positions 60 s apart."""
    out = []
    for k in range(n):
        pts: list[Point] = []
        for i in range(12):
            ang = math.radians(60.0 * i + 40.0 * k)
            r = (1.5 + 0.5 * k) / 60.0
            pts.append((lon + r * math.sin(ang) / math.cos(math.radians(lat)), lat + r * math.cos(ang),
                        now_ts - (11 - i) * 60.0, 6000 + 1000 * k))
        out.append({"hex": f"synth{k}", "pts": pts})
    return out
