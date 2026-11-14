"""AN11 item 2: storm areas. NOAA SPC day-1 categorical outlook (polygons) and convective SIGMETs (aviationweather.gov).

Writes <out>/storms.json. The page draws SPC areas as faint fills and convective SIGMETs as dashed red outlines.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from desk import demo, feeds
from desk.radar import _atomic_write

SOURCE = "NOAA SPC, aviationweather.gov"
SPC_URL = "https://www.spc.noaa.gov/products/outlook/day1otlk_cat.lyr.geojson"
SIGMET_URL = "https://aviationweather.gov/api/data/airsigmet?format=json"
EVERY_SEC = 900.0
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
LABELS = ("TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH")
MAX_RING_POINTS = 600     # thin very long rings so storms.json stays small and the static layer draws fast


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _thin(ring: list[list[float]]) -> list[list[float]]:
    if len(ring) <= MAX_RING_POINTS:
        return [[round(p[0], 3), round(p[1], 3)] for p in ring]
    step = len(ring) / MAX_RING_POINTS
    pts = [ring[int(i * step)] for i in range(MAX_RING_POINTS)]
    pts.append(ring[-1])
    return [[round(p[0], 3), round(p[1], 3)] for p in pts]


def parse_spc(text: str) -> dict[str, Any]:
    """SPC geojson -> {'valid_utc','expire_utc','areas':[{'label','rings':[[ [lon,lat], ... ]]}]} (drawing order TSTM first)."""
    data = json.loads(text)
    areas: list[dict[str, Any]] = []
    valid = expire = ""
    for f in data.get("features") or []:
        props = f.get("properties") or {}
        label = str(props.get("LABEL") or "").upper()
        if label not in LABELS:
            continue
        valid = valid or str(props.get("VALID_ISO") or "")[:19]
        expire = expire or str(props.get("EXPIRE_ISO") or "")[:19]
        geom = f.get("geometry") or {}
        polys = geom.get("coordinates") or []
        if geom.get("type") == "Polygon":
            polys = [polys]
        rings = [_thin(r) for poly in polys for r in poly if len(r) >= 3]
        if rings:
            areas.append({"label": label, "rings": rings})
    areas.sort(key=lambda a: LABELS.index(a["label"]))
    return {"valid_utc": valid + "Z" if valid else "", "expire_utc": expire + "Z" if expire else "", "areas": areas}


def parse_sigmets(text: str, now_ts: float) -> list[dict[str, Any]]:
    """Convective SIGMETs only (hazard CONVECTIVE, type SIGMET), still valid. Other hazards (turbulence, ice) are dropped."""
    out: list[dict[str, Any]] = []
    for s in json.loads(text) if text.strip() else []:
        if str(s.get("hazard") or "").upper() != "CONVECTIVE" or str(s.get("airSigmetType") or "").upper() != "SIGMET":
            continue
        f, t = s.get("validTimeFrom"), s.get("validTimeTo")
        if isinstance(f, (int, float)) and isinstance(t, (int, float)) and not (f - 300 <= now_ts <= t):
            continue
        pts = [[round(float(c["lon"]), 3), round(float(c["lat"]), 3)] for c in s.get("coords") or [] if "lon" in c and "lat" in c]
        if len(pts) < 2:
            continue
        out.append({"id": f"{s.get('seriesId') or ''}", "valid_to_utc": _iso(t) if isinstance(t, (int, float)) else "", "coords": pts})
    return out


def build(spc_text: str, sig_text: str, now_ts: float) -> dict[str, Any]:
    spc = parse_spc(spc_text)
    sig = parse_sigmets(sig_text, now_ts)
    return {"fetched_utc": _iso(now_ts), "source": SOURCE, "spc": spc, "sigmets": sig}


def _parse_iso(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def is_fresh(out_dir: Path, now_ts: float, every: float = EVERY_SEC) -> bool:
    try:
        d = json.loads((Path(out_dir) / "storms.json").read_text(encoding="utf-8"))
        return 0 <= now_ts - _parse_iso(d["fetched_utc"]) < every
    except (OSError, ValueError, KeyError):
        return False


def maybe_fetch(
    out_dir: Path | str,
    now_ts: Optional[float] = None,
    replay: bool = False,
    fetcher: Optional[Callable[[str], str]] = None,
    attempts: Optional[dict[str, float]] = None,
) -> str:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = time.time() if now_ts is None else now_ts
    if is_fresh(out, now):
        return "skip"
    if attempts is not None:
        last = attempts.get("storms")
        if last is not None and 0 <= now - last < EVERY_SEC:
            return "skip"
        attempts["storms"] = now
    if replay:
        spc = (FIXTURES / ("storms-spc-synthetic.json" if demo.on() else "storms-spc.json")).read_text(encoding="utf-8")
        sig = (FIXTURES / "storms-airsigmet.json").read_text(encoding="utf-8")
        # the recording's SIGMETs have expired by now: read them as valid at the recording time
        rec = json.loads((FIXTURES / "wx-recorded.json").read_text(encoding="utf-8"))["recorded_ts"]
        payload = build(spc, sig, rec)
        payload["fetched_utc"] = _iso(now)
        for sg in payload["sigmets"]:
            if sg["valid_to_utc"]:
                sg["valid_to_utc"] = _iso(_parse_iso(sg["valid_to_utc"]) + (now - rec))
    else:
        get = fetcher or feeds.fetch
        payload = build(get(SPC_URL), get(SIGMET_URL), now)
    if not payload["spc"]["areas"] and not payload["sigmets"]:
        # nothing to draw is a valid answer; the file still says "fetched now, nothing active"
        pass
    _atomic_write(out / "storms.json", json.dumps(payload).encode("utf-8"))
    return "ok"


# ---------- Website: which hubs sit inside a storm area ----------
RISK_WORDS = {"TSTM": "thunderstorms possible", "MRGL": "marginal storm risk", "SLGT": "slight risk of severe storms",
              "ENH": "enhanced risk of severe storms", "MDT": "moderate risk of severe storms", "HIGH": "high risk of severe storms"}
NOTE_FROM = "SLGT"          # a note on an airport card needs at least this level, or a convective SIGMET


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def hub_notes(payload: Optional[dict[str, Any]], hubs: dict[str, tuple[float, float]]) -> dict[str, dict[str, Any]]:
    """{code: {'spc': label, 'text': words, 'sigmet': bool, 'src', 'as_of_utc'}} for hubs inside a SLGT or higher SPC area
    or inside a convective SIGMET. A hub in no such area is left out."""
    out: dict[str, dict[str, Any]] = {}
    if not payload:
        return out
    areas = [a for a in (payload.get("spc") or {}).get("areas") or [] if LABELS.index(a["label"]) >= LABELS.index(NOTE_FROM)]
    sig = payload.get("sigmets") or []
    for code, (lat, lon) in hubs.items():
        best = None
        for a in areas:
            # rings are [outer, hole, ...] flattened by parse_spc; any ring that holds the point counts (holes are rare and small)
            if any(_in_ring(lon, lat, r) for r in a["rings"]):
                if best is None or LABELS.index(a["label"]) > LABELS.index(best):
                    best = a["label"]
        in_sig = any(len(s["coords"]) >= 3 and _in_ring(lon, lat, s["coords"]) for s in sig)
        if best or in_sig:
            parts = []
            if in_sig:
                parts.append("inside a convective SIGMET area")
            if best:
                parts.append(RISK_WORDS[best] + " today")
            out[code] = {"spc": best, "sigmet": in_sig, "text": "; ".join(parts), "src": payload.get("source") or SOURCE,
                         "as_of_utc": payload.get("fetched_utc")}
    return out
