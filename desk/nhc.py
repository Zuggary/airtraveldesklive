"""AN11 item 6: hurricane auto-layer from NHC CurrentStorms.json. Nothing active means nothing drawn.

The JSON offers the forecast cone only as KMZ/shapefile links, so the layer shows the storm's current position and
name with 'NHC · advisory <n>'. Writes <out>/nhc.json.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from desk import demo, feeds
from desk.radar import _atomic_write

SOURCE = "NOAA NHC"
URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
EVERY_SEC = 1800.0
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _advisory(s: dict[str, Any]) -> str:
    for key in ("publicAdvisory", "advisory"):
        a = s.get(key)
        if isinstance(a, dict):
            for k in ("advNum", "advisoryNumber", "number"):
                if a.get(k):
                    return str(a[k]).lstrip("0") or "0"
            m = re.search(r"(\d+)", str(a.get("url") or ""))
            if m:
                return m.group(1).lstrip("0") or "0"
    return ""


def parse(text: str) -> list[dict[str, Any]]:
    """Active storms with a usable position. Anything without one is left out."""
    data = json.loads(text) if text.strip() else {}
    out: list[dict[str, Any]] = []
    for s in data.get("activeStorms") or []:
        lat = _num(s.get("latitudeNumeric", s.get("latitude")))
        lon = _num(s.get("longitudeNumeric", s.get("longitude")))
        if lat is None or lon is None:
            continue
        out.append({
            "id": str(s.get("id") or ""), "name": str(s.get("name") or "").title(),
            "kind": str(s.get("classification") or ""), "lat": lat, "lon": lon,
            "advisory": _advisory(s), "updated": str(s.get("lastUpdate") or ""),
        })
    return out


def maybe_fetch(
    out_dir: Path | str,
    now_ts: Optional[float] = None,
    replay: bool = False,
    fetcher: Optional[Callable[[str], str]] = None,
    attempts: Optional[dict[str, float]] = None,
    fixture: str = "nhc-empty.json",
) -> str:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = time.time() if now_ts is None else now_ts
    try:
        d = json.loads((out / "nhc.json").read_text(encoding="utf-8"))
        fetched = datetime.strptime(d["fetched_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        if 0 <= now - fetched < EVERY_SEC:
            return "skip"
    except (OSError, ValueError, KeyError):
        pass
    if attempts is not None:
        last = attempts.get("nhc")
        if last is not None and 0 <= now - last < EVERY_SEC:
            return "skip"
        attempts["nhc"] = now
    text = (FIXTURES / ("nhc-active-synthetic.json" if demo.on() else fixture)).read_text(encoding="utf-8") if replay else (fetcher or feeds.fetch)(URL)
    storms = parse(text)
    _atomic_write(out / "nhc.json", json.dumps({"fetched_utc": _iso(now), "source": SOURCE, "storms": storms}).encode("utf-8"))
    return "ok"
