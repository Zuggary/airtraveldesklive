from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional, Union

from desk.airports import AIRPORTS

USER_AGENT = "AirTravelDeskLive/1.0 (+https://www.airtraveldesklive.com)"

FAA_URL = "https://nasstatus.faa.gov/api/airport-status-information"
NWS_URL_TEMPLATE = "https://api.weather.gov/alerts/active?point={lat},{lon}"
ADSB_URL = "https://api.adsb.lol/v2/sqk/7700"

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


def is_weather(reason: str) -> bool:
    """Return True if reason mentions any weather keyword from the README list."""
    if not reason:
        return False
    return bool(_WEATHER_RE.search(reason))


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _build_faa_event(
    kind: str,
    airport: str,
    reason: str,
    fields: dict[str, str],
) -> dict[str, Any]:
    clean_fields = {k: v for k, v in fields.items() if v != ""}
    return {
        "id": f"{kind}:{airport}",
        "kind": kind,
        "airport": airport,
        "reason": reason,
        "fields": clean_fields,
        "source": "FAA",
    }


def parse_faa(xml_text: str) -> list[dict[str, Any]]:
    """Parse FAA NAS status XML into normalized event dicts."""
    if not xml_text or not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    events: list[dict[str, Any]] = []

    for prog in root.findall(".//Ground_Stop_List/Program"):
        arpt = _text(prog, "ARPT").upper()
        if not arpt:
            continue
        events.append(
            _build_faa_event(
                "ground_stop",
                arpt,
                _text(prog, "Reason"),
                {"end_time": _text(prog, "End_Time")},
            )
        )

    for gd in root.findall(".//Ground_Delay_List/Ground_Delay"):
        arpt = _text(gd, "ARPT").upper()
        if not arpt:
            continue
        events.append(
            _build_faa_event(
                "ground_delay",
                arpt,
                _text(gd, "Reason"),
                {"avg": _text(gd, "Avg"), "max": _text(gd, "Max")},
            )
        )

    for delay in root.findall(".//Arrival_Departure_Delay_List/Delay"):
        arpt = _text(delay, "ARPT").upper()
        if not arpt:
            continue
        reason = _text(delay, "Reason")
        ad = delay.find("Arrival_Departure")
        fields: dict[str, str] = {}
        if ad is not None:
            fields = {
                "direction": (ad.attrib.get("Type") or "").strip(),
                "min": _text(ad, "Min"),
                "max": _text(ad, "Max"),
                "trend": _text(ad, "Trend"),
            }
        events.append(_build_faa_event("delay", arpt, reason, fields))

    for ap in root.findall(".//Airport_Closure_List/Airport"):
        arpt = _text(ap, "ARPT").upper()
        if not arpt:
            continue
        raw_reason = _text(ap, "Reason")
        upper_reason = raw_reason.upper()
        if "CLSD TO" in upper_reason or " EXC " in upper_reason:
            continue
        events.append(
            _build_faa_event(
                "closure",
                arpt,
                "closed",
                {"reopen": _text(ap, "Reopen")},
            )
        )

    return events


def parse_nws(json_text: str) -> list[str]:
    """Parse NWS active alerts GeoJSON and return active alert event names."""
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


def _in_lower_48(lat: Any, lon: Any) -> bool:
    if lat is None or lon is None:
        return False
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    return 24.0 <= lat_f <= 50.0 and -125.0 <= lon_f <= -66.0


def parse_adsb(json_text: str) -> list[dict[str, Any]]:
    """Parse adsb.lol squawk 7700 JSON, keeping aircraft inside the lower 48 box."""
    if not json_text or not json_text.strip():
        return []
    data = json.loads(json_text)
    events: list[dict[str, Any]] = []
    for ac in data.get("ac") or []:
        hex_code = (ac.get("hex") or "").strip()
        lat = ac.get("lat")
        lon = ac.get("lon")
        if not hex_code or not _in_lower_48(lat, lon):
            continue
        callsign = (ac.get("flight") or "").strip()
        alt = ac.get("alt_baro")
        if alt is None:
            alt = ac.get("alt_geom", ac.get("alt"))
        events.append(
            {
                "id": f"sqk:{hex_code}",
                "kind": "squawk7700",
                "fields": {
                    "callsign": callsign,
                    "lat": float(lat),
                    "lon": float(lon),
                    "alt": alt,
                },
                "source": "adsb.lol",
            }
        )
    return events


class Replay:
    """Serves fixture files by name from fixtures/ instead of hitting the network."""

    def __init__(self, fixtures_dir: Optional[Union[Path, str]] = None) -> None:
        if fixtures_dir is None:
            fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
        self.fixtures_dir = Path(fixtures_dir)

    def read(self, name: str) -> str:
        path = self.fixtures_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Fixture not found: {path}")
        return path.read_text(encoding="utf-8")

    get = read

    def fetch(self, url_or_name: str, timeout: int = 20) -> str:  # noqa: ARG002
        direct = self.fixtures_dir / url_or_name
        if direct.is_file():
            return direct.read_text(encoding="utf-8")

        if "nasstatus.faa.gov" in url_or_name:
            return self.read("faa-1.xml")
        if "api.adsb.lol" in url_or_name:
            return self.read("adsb-7700.json")
        if "api.weather.gov" in url_or_name:
            return self._nws_for_url(url_or_name)

        raise FileNotFoundError(f"No replay fixture for: {url_or_name}")

    def _nws_for_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        point = (qs.get("point") or [""])[0]
        if "," in point:
            try:
                lat_s, lon_s = point.split(",", 1)
                lat, lon = float(lat_s), float(lon_s)
                for code, (_, alat, alon) in AIRPORTS.items():
                    if abs(lat - alat) < 0.05 and abs(lon - alon) < 0.05:
                        for candidate in (f"nws-{code}.json", f"nws-{code}-synthetic.json"):
                            if (self.fixtures_dir / candidate).is_file():
                                return self.read(candidate)
            except ValueError:
                pass
        return '{"type":"FeatureCollection","features":[]}'


def _replay_enabled() -> bool:
    val = os.environ.get("AN2_REPLAY", "").strip().lower()
    return val not in ("", "0", "false", "no")


def fetch(url: str, timeout: int = 20) -> str:
    """Fetch a URL with the required User-Agent, or serve from Replay if AN2_REPLAY is set."""
    if _replay_enabled():
        return Replay().fetch(url, timeout=timeout)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")
