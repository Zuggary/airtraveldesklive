"""Build the desk data for the website (one shot, run by the GitHub Actions job every 5 minutes).

Writes into data/: state.json (desk screen), radar.png + radar.json, tsa.json.
The page only reads these files from its own origin; no viewer browser calls a third party.
The ticker keeps continuity by reading the previously published state.json (--prev URL or file)
and adding one line per change since then. Stdlib only. No voice on the web.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk import bts, feeds, lines, radar, screen, state, tracks, tsa  # noqa: E402
from desk.airports import AIRPORTS, BUSIEST_30, SHORT, TZ, display, nearest_airport, spoken  # noqa: E402

MAX_LINES = 8
NWS_TIMEOUT = 15
NEAR_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/20"
NEAR_MAX_CALLS = 5
NEAR_TIMEOUT = 15
DATA_VERSION = 1

# City words for the search box and the card subtitle. A label only.
CITY = {
    "ATL": "Atlanta, GA", "DFW": "Dallas-Fort Worth, TX", "DEN": "Denver, CO", "ORD": "Chicago, IL",
    "LAX": "Los Angeles, CA", "JFK": "New York, NY", "LAS": "Las Vegas, NV", "MCO": "Orlando, FL",
    "MIA": "Miami, FL", "CLT": "Charlotte, NC", "SEA": "Seattle, WA", "PHX": "Phoenix, AZ",
    "EWR": "Newark, NJ", "SFO": "San Francisco, CA", "IAH": "Houston, TX", "BOS": "Boston, MA",
    "FLL": "Fort Lauderdale, FL", "MSP": "Minneapolis, MN", "LGA": "New York, NY", "DTW": "Detroit, MI",
    "PHL": "Philadelphia, PA", "SLC": "Salt Lake City, UT", "BWI": "Baltimore, MD", "IAD": "Washington, DC",
    "SAN": "San Diego, CA", "DCA": "Washington, DC", "TPA": "Tampa, FL", "BNA": "Nashville, TN",
    "AUS": "Austin, TX", "MDW": "Chicago, IL",
}
_LEVEL_WORD = {"green": "clear", "amber": "delay", "red": "stop"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def load_prev(src: str) -> dict:
    if not src:
        return {}
    try:
        if src.startswith("https://"):
            req = urllib.request.Request(src, headers={"User-Agent": feeds.USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data if isinstance(data, dict) else {}
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def enrich(events: list[dict]) -> list[dict]:
    out = []
    for ev in events:
        item = copy.deepcopy(ev)
        if item.get("kind") == "squawk7700":
            f = item.get("fields") or {}
            item["lat"], item["lon"] = f.get("lat"), f.get("lon")
            near = nearest_airport(item["lat"], item["lon"], max_km=150.0) if item["lat"] is not None else None
            item["spoken"] = item["display"] = f"Near {near}" if near else "Transponder 7700"
        else:
            code = str(item.get("airport") or "").upper()
            item["spoken"], item["display"], item["tz"] = spoken(code), display(code), TZ.get(code)
            if item.get("kind") == "ground_stop":
                item["end_utc"] = screen.parse_end_time(str((item.get("fields") or {}).get("end_time") or ""))
            a = AIRPORTS.get(code)
            item["lat"], item["lon"] = (a[1], a[2]) if a else (None, None)
        out.append(item)
    return out


def build(out_dir: Path, prev: dict, faa_text: str | None = None, adsb_text: str | None = None,
          nws_map: dict | None = None, skip_slow: bool = False, near_fetch=None) -> dict:
    stale: list[str] = []
    try:
        faa_events = feeds.parse_faa(faa_text if faa_text is not None else feeds.fetch(feeds.FAA_URL))
    except Exception:
        faa_events = [e for e in prev.get("events", []) if e.get("kind") != "squawk7700"]
        stale.append("FAA")
    try:
        adsb_events = feeds.parse_adsb(adsb_text if adsb_text is not None else feeds.fetch(feeds.ADSB_URL))
    except Exception:
        adsb_events = [e for e in prev.get("events", []) if e.get("kind") == "squawk7700"]
        stale.append("adsb.lol")

    nws_by_airport: dict[str, list[str]] = {}
    for ev in faa_events:
        code = ev.get("airport")
        if code in nws_by_airport or code not in AIRPORTS or not feeds.is_weather(ev.get("reason", "")):
            continue
        if nws_map is not None:
            nws_by_airport[code] = nws_map.get(code, [])
            continue
        _, lat, lon = AIRPORTS[code]
        try:
            nws_by_airport[code] = feeds.parse_nws(feeds.fetch(feeds.NWS_URL_TEMPLATE.format(lat=lat, lon=lon), timeout=NWS_TIMEOUT))
        except Exception:
            nws_by_airport[code] = []
            if "NWS" not in stale:
                stale.append("NWS")

    combined = faa_events + adsb_events
    state.apply_status(combined, nws_by_airport)
    events = enrich(combined)

    if not skip_slow:
        for name, mod in (("radar", radar), ("TSA", tsa)):
            try:
                mod.maybe_fetch(out_dir)
            except Exception:
                if name == "radar" or not (out_dir / "tsa.json").is_file():
                    stale.append(name)

    stamp = now_iso()
    last_lines = list(prev.get("last_lines") or [])
    prev_events = prev.get("events")
    if prev_events is None:
        new_items = [(lines.recap(events), "recap")] + [(lines.still(e), e.get("id")) for e in events[:3]]
    else:
        new_items = [(lines.line(ch), (ch.get("event") or {}).get("id")) for ch in state.diff(prev_events, events)]
        if not new_items:
            recap = lines.recap(events)
            # Skip a recap identical to the last line, so a quiet board does not fill the ticker.
            if not last_lines or last_lines[-1].get("text") != recap:
                new_items = [(recap, "recap")]
    for text, event_id in new_items:
        # One snapshot rule: a line about an event replaces earlier lines about it.
        if event_id:
            last_lines = [l for l in last_lines if l.get("event_id") != event_id]
        last_lines.append({"time_utc": stamp, "text": text, "event_id": event_id})
    last_lines = last_lines[-MAX_LINES:]

    payload = {
        "updated_utc": stamp,
        "stale_feeds": stale,
        "events": events,
        "board": screen.board_from_events(events),
        "last_lines": last_lines,
        "update_note": "Updates about every 5 minutes. GitHub's scheduler can run late.",
    }
    write_json(out_dir / "state.json", payload)
    cards = build_airport_cards(events, payload["board"], nws_by_airport, stamp, near_fetch=near_fetch, skip_near=skip_slow or nws_map is not None and near_fetch is None)
    write_json(out_dir / "airports.json", cards)
    if not skip_slow:
        build_bts(out_dir)
    return payload


def _minutes(text: str) -> int:
    h = re.search(r"(\d+)\s*hours?", text or "", re.IGNORECASE)
    m = re.search(r"(\d+)\s*minutes?", text or "", re.IGNORECASE)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def pick_near_airports(events: list[dict], limit: int = NEAR_MAX_CALLS) -> list[str]:
    """Airports with an active FAA event, worst first (stop, then longest average), at most limit."""
    rank = {"ground_stop": 3, "closure": 3, "ground_delay": 2, "delay": 1}
    best: dict[str, tuple[int, int]] = {}
    for ev in events:
        code = str(ev.get("airport") or "").upper()
        if ev.get("source") != "FAA" or code not in BUSIEST_30 or ev.get("kind") not in rank:
            continue
        key = (rank[ev["kind"]], _minutes((ev.get("fields") or {}).get("avg", "")))
        if code not in best or key > best[code]:
            best[code] = key
    return sorted(best, key=lambda c: (-best[c][0], -best[c][1], c))[:limit]


def count_near(json_text: str) -> int:
    return len(tracks.parse_near(json_text))


def build_airport_cards(events: list[dict], board: list[dict], nws_by_airport: dict, stamp: str,
                        near_fetch=None, skip_near: bool = False) -> dict:
    """One card per busiest-30 airport: status, reason, events, NWS alert names, aircraft nearby, local tz."""
    level_by = {b["code"]: _LEVEL_WORD.get(b["level"], "clear") for b in board}
    near: dict[str, int] = {}
    if not skip_near:
        get = near_fetch or (lambda url: feeds.fetch(url, timeout=NEAR_TIMEOUT))
        for i, code in enumerate(pick_near_airports(events)):
            _, lat, lon = AIRPORTS[code]
            try:
                near[code] = count_near(get(NEAR_URL.format(lat=lat, lon=lon)))
            except Exception:
                pass
    cards = {}
    for code in BUSIEST_30:
        evs = [e for e in events if e.get("source") == "FAA" and str(e.get("airport") or "").upper() == code]
        reasons = []
        for e in evs:
            r = (e.get("reason") or "").strip()
            if r and r not in reasons:
                reasons.append(r)
        out_ev = []
        for e in evs:
            f = e.get("fields") or {}
            out_ev.append({
                "kind": e.get("kind"), "reason": e.get("reason") or "", "status": e.get("status") or "OFFICIAL",
                "avg": f.get("avg") or "", "max": f.get("max") or "", "min": f.get("min") or "",
                "trend": f.get("trend") or "", "direction": f.get("direction") or "",
                "end_time": f.get("end_time") or "", "end_utc": e.get("end_utc") or "",
            })
        _, lat, lon = AIRPORTS[code]
        cards[code] = {
            "code": code, "name": display(code), "short": SHORT.get(code, code), "city": CITY.get(code, ""),
            "tz": TZ.get(code), "lat": lat, "lon": lon,
            "level": level_by.get(code, "clear"), "reason": "; ".join(reasons),
            "events": out_ev, "alerts": list(nws_by_airport.get(code) or []),
            "aircraft_near": near.get(code),
        }
    return {"version": DATA_VERSION, "updated_utc": stamp, "aircraft_source": "adsb.lol (ODbL), within 20 nm", "airports": cards}


def build_bts(out_dir: Path) -> str:
    """BTS on-time card data. Failure is not fatal: the page hides the card when bts.json is missing."""
    try:
        return bts.maybe_update(out_dir, cache_dir=out_dir / "bts-cache")
    except Exception as exc:
        print(f"bts: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return "error"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--prev", default="https://www.airtraveldesklive.com/data/state.json")
    ap.add_argument("--fixture-faa")
    ap.add_argument("--fixture-adsb")
    ap.add_argument("--skip-slow", action="store_true", help="skip radar and TSA (tests)")
    a = ap.parse_args()
    faa = Path(a.fixture_faa).read_text() if a.fixture_faa else None
    adsb = Path(a.fixture_adsb).read_text() if a.fixture_adsb else None
    p = build(Path(a.out), load_prev(a.prev), faa, adsb, {} if a.fixture_faa else None, a.skip_slow)
    print(f"state.json: {len(p['events'])} events, stale={p['stale_feeds']}, lines={len(p['last_lines'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
