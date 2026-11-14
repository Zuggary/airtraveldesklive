#!/usr/bin/env python3
"""Build data/status.json from FAA NAS status and NWS active weather alerts."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

USER_AGENT = "AirTravelDeskLive/1.0 (+https://www.airtraveldesklive.com)"
FAA_URL = "https://nasstatus.faa.gov/api/airport-status-information"
NWS_URL_TEMPLATE = "https://api.weather.gov/alerts/active?point={lat},{lon}"

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "status.json"

# 30 busiest US airports in order: (code, display_name, iana_tz)
BUSIEST_30: list[tuple[str, str, str]] = [
    ("ATL", "Hartsfield-Jackson Atlanta International", "America/New_York"),
    ("DFW", "Dallas Fort Worth International", "America/Chicago"),
    ("DEN", "Denver International", "America/Denver"),
    ("ORD", "Chicago O'Hare International", "America/Chicago"),
    ("LAX", "Los Angeles International", "America/Los_Angeles"),
    ("JFK", "John F. Kennedy International", "America/New_York"),
    ("LAS", "Harry Reid International", "America/Los_Angeles"),
    ("MCO", "Orlando International", "America/New_York"),
    ("MIA", "Miami International", "America/New_York"),
    ("CLT", "Charlotte Douglas International", "America/New_York"),
    ("SEA", "Seattle-Tacoma International", "America/Los_Angeles"),
    ("PHX", "Phoenix Sky Harbor International", "America/Phoenix"),
    ("EWR", "Newark Liberty International", "America/New_York"),
    ("SFO", "San Francisco International", "America/Los_Angeles"),
    ("IAH", "George Bush Intercontinental", "America/Chicago"),
    ("BOS", "Boston Logan International", "America/New_York"),
    ("FLL", "Fort Lauderdale-Hollywood International", "America/New_York"),
    ("MSP", "Minneapolis-Saint Paul International", "America/Chicago"),
    ("LGA", "LaGuardia", "America/New_York"),
    ("DTW", "Detroit Metropolitan Wayne County", "America/New_York"),
    ("PHL", "Philadelphia International", "America/New_York"),
    ("SLC", "Salt Lake City International", "America/Denver"),
    ("BWI", "Baltimore/Washington International", "America/New_York"),
    ("IAD", "Washington Dulles International", "America/New_York"),
    ("SAN", "San Diego International", "America/Los_Angeles"),
    ("DCA", "Ronald Reagan Washington National", "America/New_York"),
    ("TPA", "Tampa International", "America/New_York"),
    ("BNA", "Nashville International", "America/Chicago"),
    ("AUS", "Austin-Bergstrom International", "America/Chicago"),
    ("MDW", "Chicago Midway International", "America/Chicago"),
]

# All known airports: code -> (display_name, lat, lon, iana_tz)
AIRPORTS: dict[str, tuple[str, float, float, str]] = {
    "ATL": ("Hartsfield-Jackson Atlanta International", 33.641, -84.427, "America/New_York"),
    "DFW": ("Dallas Fort Worth International", 32.897, -97.038, "America/Chicago"),
    "DEN": ("Denver International", 39.856, -104.674, "America/Denver"),
    "ORD": ("Chicago O'Hare International", 41.974, -87.907, "America/Chicago"),
    "LAX": ("Los Angeles International", 33.942, -118.408, "America/Los_Angeles"),
    "JFK": ("John F. Kennedy International", 40.641, -73.778, "America/New_York"),
    "LAS": ("Harry Reid International", 36.084, -115.154, "America/Los_Angeles"),
    "MCO": ("Orlando International", 28.431, -81.308, "America/New_York"),
    "MIA": ("Miami International", 25.796, -80.287, "America/New_York"),
    "CLT": ("Charlotte Douglas International", 35.214, -80.943, "America/New_York"),
    "SEA": ("Seattle-Tacoma International", 47.450, -122.309, "America/Los_Angeles"),
    "PHX": ("Phoenix Sky Harbor International", 33.437, -112.008, "America/Phoenix"),
    "EWR": ("Newark Liberty International", 40.690, -74.174, "America/New_York"),
    "SFO": ("San Francisco International", 37.621, -122.379, "America/Los_Angeles"),
    "IAH": ("George Bush Intercontinental", 29.990, -95.337, "America/Chicago"),
    "BOS": ("Boston Logan International", 42.366, -71.010, "America/New_York"),
    "FLL": ("Fort Lauderdale-Hollywood International", 26.073, -80.153, "America/New_York"),
    "MSP": ("Minneapolis-Saint Paul International", 44.885, -93.222, "America/Chicago"),
    "LGA": ("LaGuardia", 40.777, -73.874, "America/New_York"),
    "DTW": ("Detroit Metropolitan Wayne County", 42.212, -83.353, "America/New_York"),
    "PHL": ("Philadelphia International", 39.874, -75.242, "America/New_York"),
    "SLC": ("Salt Lake City International", 40.789, -111.978, "America/Denver"),
    "BWI": ("Baltimore/Washington International", 39.177, -76.668, "America/New_York"),
    "IAD": ("Washington Dulles International", 38.953, -77.457, "America/New_York"),
    "SAN": ("San Diego International", 32.734, -117.190, "America/Los_Angeles"),
    "DCA": ("Ronald Reagan Washington National", 38.851, -77.040, "America/New_York"),
    "TPA": ("Tampa International", 27.977, -82.531, "America/New_York"),
    "BNA": ("Nashville International", 36.127, -86.678, "America/Chicago"),
    "AUS": ("Austin-Bergstrom International", 30.197, -97.666, "America/Chicago"),
    "MDW": ("Chicago Midway International", 41.786, -87.752, "America/Chicago"),
    "HNL": ("Daniel K. Inouye International", 21.319, -157.922, "Pacific/Honolulu"),
    "DAL": ("Dallas Love Field", 32.847, -96.852, "America/Chicago"),
    "PDX": ("Portland International", 45.589, -122.595, "America/Los_Angeles"),
    "STL": ("St. Louis Lambert International", 38.749, -90.370, "America/Chicago"),
    "HOU": ("William P. Hobby", 29.645, -95.279, "America/Chicago"),
    "SMF": ("Sacramento International", 38.695, -121.591, "America/Los_Angeles"),
    "SJC": ("San Jose Mineta International", 37.363, -121.929, "America/Los_Angeles"),
    "OAK": ("Oakland International", 37.721, -122.221, "America/Los_Angeles"),
    "RDU": ("Raleigh-Durham International", 35.878, -78.788, "America/New_York"),
    "BDL": ("Bradley International", 41.939, -72.683, "America/New_York"),
}

WEATHER_WORDS = (
    "wind",
    "thunderstorms",
    "snow",
    "ice",
    "fog",
    "low ceilings",
    "low visibility",
    "rain",
    "weather",
)
_WEATHER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in WEATHER_WORDS) + r")\b",
    re.IGNORECASE,
)

_LEVEL_RANK = {"clear": 0, "delay": 1, "stop": 2}
_KIND_TO_LEVEL = {
    "ground_stop": "stop",
    "closure": "stop",
    "ground_delay": "delay",
    "delay": "delay",
}


def is_weather(reason: str) -> bool:
    """Return True if the FAA reason mentions a weather keyword."""
    if not reason:
        return False
    return bool(_WEATHER_RE.search(reason))


def airport_name(code: str) -> str:
    """Map an airport code to its display name, falling back to the code."""
    norm = (code or "").strip().upper()
    if norm in AIRPORTS:
        return AIRPORTS[norm][0]
    return norm or (code or "")


def airport_tz(code: str) -> Optional[str]:
    """Return the IANA timezone for a known airport code, or None."""
    norm = (code or "").strip().upper()
    if norm in AIRPORTS:
        return AIRPORTS[norm][3]
    return None


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _make_event(
    kind: str,
    code: str,
    reason: str,
    *,
    avg: str = "",
    max_val: str = "",
    min_val: str = "",
    trend: str = "",
    direction: str = "",
    end_time: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "name": airport_name(code),
        "tz": airport_tz(code),
        "kind": kind,
        "reason": reason,
        "avg": avg or None,
        "max": max_val or None,
        "min": min_val or None,
        "trend": trend or None,
        "direction": direction or None,
        "end_time": end_time or None,
        "status": "OFFICIAL",
        "alert": None,
        "sources": ["FAA"],
    }


def parse_faa(xml_text: str) -> list[dict[str, Any]]:
    """Parse FAA NAS status XML into normalized event dictionaries."""
    if not xml_text or not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    events: list[dict[str, Any]] = []

    for prog in root.findall(".//Ground_Stop_List/Program"):
        arpt = _text(prog, "ARPT").upper()
        if not arpt:
            continue
        events.append(
            _make_event(
                "ground_stop",
                arpt,
                _text(prog, "Reason"),
                end_time=_text(prog, "End_Time"),
            )
        )

    for gd in root.findall(".//Ground_Delay_List/Ground_Delay"):
        arpt = _text(gd, "ARPT").upper()
        if not arpt:
            continue
        events.append(
            _make_event(
                "ground_delay",
                arpt,
                _text(gd, "Reason"),
                avg=_text(gd, "Avg"),
                max_val=_text(gd, "Max"),
            )
        )

    for delay in root.findall(".//Arrival_Departure_Delay_List/Delay"):
        arpt = _text(delay, "ARPT").upper()
        if not arpt:
            continue
        reason = _text(delay, "Reason")
        ad = delay.find("Arrival_Departure")
        direction = ""
        min_val = ""
        max_val = ""
        trend = ""
        if ad is not None:
            direction = (ad.attrib.get("Type") or "").strip()
            min_val = _text(ad, "Min")
            max_val = _text(ad, "Max")
            trend = _text(ad, "Trend")
        events.append(
            _make_event(
                "delay",
                arpt,
                reason,
                direction=direction,
                min_val=min_val,
                max_val=max_val,
                trend=trend,
            )
        )

    for ap in root.findall(".//Airport_Closure_List/Airport"):
        arpt = _text(ap, "ARPT").upper()
        if not arpt:
            continue
        raw_reason = _text(ap, "Reason")
        upper_reason = raw_reason.upper()
        if "CLSD TO" in upper_reason or " EXC " in upper_reason:
            continue
        events.append(
            _make_event(
                "closure",
                arpt,
                "Airport closed",
                end_time=_text(ap, "Reopen"),
            )
        )

    return events


def parse_nws(json_text: str) -> list[str]:
    """Parse NWS active alerts GeoJSON and return unique alert event names."""
    if not json_text or not json_text.strip():
        return []
    data = json.loads(json_text)
    names: list[str] = []
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        ev = (props.get("event") or "").strip()
        if ev and ev not in names:
            names.append(ev)
    return names


def fetch_url(url: str, timeout: int = 20) -> str:
    """Fetch a URL with the required User-Agent header."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/geo+json, application/json, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _read_nws_fixture(fixture_nws: Path, code: str) -> str:
    """Read NWS JSON fixture for a given airport code from a file or directory."""
    if fixture_nws.is_dir():
        for candidate in (f"nws-{code}.json", f"nws-{code}-synthetic.json"):
            path = fixture_nws / candidate
            if path.is_file():
                return path.read_text(encoding="utf-8")
        return '{"type":"FeatureCollection","features":[]}'

    match = re.match(r"^nws-([A-Z0-9]{3,4})(?:-|\.)", fixture_nws.name, re.IGNORECASE)
    if match:
        target_code = match.group(1).upper()
        if target_code == code:
            return fixture_nws.read_text(encoding="utf-8")
        for candidate in (f"nws-{code}.json", f"nws-{code}-synthetic.json"):
            sibling = fixture_nws.parent / candidate
            if sibling.is_file():
                return sibling.read_text(encoding="utf-8")
        return '{"type":"FeatureCollection","features":[]}'

    return fixture_nws.read_text(encoding="utf-8")


def build_board(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Compute board status entries for the 30 busiest US airports."""
    levels: dict[str, str] = {}
    for ev in events:
        code = ev["code"]
        ev_level = _KIND_TO_LEVEL.get(ev["kind"], "clear")
        prev_level = levels.get(code, "clear")
        if _LEVEL_RANK[ev_level] > _LEVEL_RANK[prev_level]:
            levels[code] = ev_level

    return [
        {
            "code": code,
            "name": name,
            "tz": tz,
            "level": levels.get(code, "clear"),
        }
        for code, name, tz in BUSIEST_30
    ]


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write JSON payload to path using a temp file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".status-", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _load_previous_status(output_path: Path) -> Optional[dict[str, Any]]:
    """Load previous status.json if present and valid."""
    if not output_path.is_file():
        return None
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return data
    except (OSError, ValueError):
        return None
    return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_status(
    output_path: Path = DEFAULT_OUTPUT,
    fixture_faa: Optional[Path] = None,
    fixture_nws: Optional[Path] = None,
) -> dict[str, Any]:
    """Fetch FAA and NWS data (or fixtures), build status payload, and write atomically."""
    try:
        if fixture_faa is not None:
            faa_xml = fixture_faa.read_text(encoding="utf-8")
        else:
            faa_xml = fetch_url(FAA_URL)
        events = parse_faa(faa_xml)
    except Exception as exc:  # noqa: BLE001
        prev = _load_previous_status(output_path)
        if prev is not None:
            payload = dict(prev)
            payload["stale"] = True
            payload["error"] = f"FAA feed error: {exc}"
            if "board" not in payload or not isinstance(payload["board"], list):
                payload["board"] = build_board(payload.get("events", []))
            if "sources" not in payload:
                payload["sources"] = ["FAA", "NWS"]
        else:
            payload = {
                "updated_utc": _utc_now_iso(),
                "board": build_board([]),
                "events": [],
                "sources": ["FAA", "NWS"],
                "stale": True,
                "error": f"FAA feed error: {exc}",
            }
        atomic_write_json(output_path, payload)
        return payload

    nws_cache: dict[str, list[str]] = {}
    for ev in events:
        if not is_weather(ev["reason"]):
            continue
        code = ev["code"]
        if code not in AIRPORTS:
            continue
        if code not in nws_cache:
            _, lat, lon, _ = AIRPORTS[code]
            try:
                if fixture_nws is not None:
                    nws_json = _read_nws_fixture(fixture_nws, code)
                else:
                    nws_json = fetch_url(NWS_URL_TEMPLATE.format(lat=lat, lon=lon))
                nws_cache[code] = parse_nws(nws_json)
            except Exception as exc:  # noqa: BLE001
                print(f"NWS feed error for {code}: {exc}", file=sys.stderr)
                nws_cache[code] = []

        alerts = nws_cache[code]
        if alerts:
            ev["status"] = "CONFIRMED"
            ev["alert"] = alerts[0] if len(alerts) == 1 else "; ".join(alerts)
            ev["sources"] = ["FAA", "NWS"]

    payload = {
        "updated_utc": _utc_now_iso(),
        "board": build_board(events),
        "events": events,
        "sources": ["FAA", "NWS"],
    }
    atomic_write_json(output_path, payload)
    return payload


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build data/status.json from FAA NAS status and NWS alerts."
    )
    parser.add_argument(
        "--fixture-faa",
        type=Path,
        default=None,
        help="Read FAA NAS status XML from a local file instead of fetching.",
    )
    parser.add_argument(
        "--fixture-nws",
        type=Path,
        default=None,
        help="Read NWS active alerts JSON from a local file or directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON file path (default: data/status.json).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    build_status(
        output_path=args.output,
        fixture_faa=args.fixture_faa,
        fixture_nws=args.fixture_nws,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
