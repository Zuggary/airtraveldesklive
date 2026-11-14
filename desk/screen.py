"""AN6 screen helpers: board colours and FAA end-time parsing. Standard library only."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from desk.airports import AIRPORTS, BUSIEST_30, SHORT

# Fixed UTC offsets (hours) for the zone words the FAA uses.
ZONE_OFFSETS = {
    "EST": -5, "EDT": -4, "CST": -6, "CDT": -5, "MST": -7, "MDT": -6,
    "PST": -8, "PDT": -7, "AKST": -9, "AKDT": -8, "HST": -10,
    "UTC": 0, "GMT": 0, "Z": 0,
}

_END_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*([ap]m)\s*([A-Za-z]{1,4})?", re.IGNORECASE
)

_LEVEL = {"ground_stop": "red", "closure": "red", "ground_delay": "amber", "delay": "amber"}
_RANK = {"green": 0, "amber": 1, "red": 2}


def board_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One tile per busiest-30 airport: green none, amber delay, red stop or closure."""
    level_by_code: dict[str, str] = {}
    kind_by_code: dict[str, str] = {}
    for ev in events:
        if ev.get("source") != "FAA":
            continue
        code = str(ev.get("airport") or "").upper()
        lvl = _LEVEL.get(ev.get("kind", ""))
        if not code or not lvl:
            continue
        if _RANK[lvl] > _RANK[level_by_code.get(code, "green")]:
            level_by_code[code] = lvl
            kind_by_code[code] = ev["kind"]
    return [
        {
            "code": code,
            "name": SHORT.get(code, code),
            "level": level_by_code.get(code, "green"),
            "kind": kind_by_code.get(code, ""),
            "lat": AIRPORTS[code][1] if code in AIRPORTS else None,
            "lon": AIRPORTS[code][2] if code in AIRPORTS else None,
        }
        for code in BUSIEST_30
    ]


def parse_end_time(text: str, now_utc: Optional[datetime] = None) -> Optional[str]:
    """'8:30 pm EST.' -> ISO UTC of the nearest occurrence of that wall time in that zone."""
    if not text:
        return None
    m = _END_RE.search(text)
    if not m:
        return None
    hh, mm, ap, zone = int(m.group(1)), int(m.group(2)), m.group(3).lower(), (m.group(4) or "").upper()
    if zone not in ZONE_OFFSETS or not (1 <= hh <= 12) or mm > 59:
        return None
    hh = hh % 12 + (12 if ap == "pm" else 0)
    tz = timezone(timedelta(hours=ZONE_OFFSETS[zone]))
    now = now_utc or datetime.now(timezone.utc)
    local_now = now.astimezone(tz)
    base = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    # Nearest occurrence to now (yesterday, today or tomorrow). A ground stop past its listed end
    # must read as "past listed end time", never as a stop with 20 hours left.
    cand = min((base + timedelta(days=d) for d in (-1, 0, 1)), key=lambda c: abs((c - local_now).total_seconds()))
    return cand.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
