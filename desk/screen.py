"""AN6 screen helpers: board colours and FAA end-time parsing. Standard library only."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from desk.airports import AIRPORTS, BUSIEST_30, SHORT, canonical_code

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


_STATUS = {"ground_stop": "red", "closure": "red", "ground_delay": "orange", "delay": "yellow"}
_STATUS_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
_ZONE_OF_TZ = {
    "America/Los_Angeles": "PT", "America/Denver": "MT", "America/Phoenix": "MT", "America/Boise": "MT",
    "America/Chicago": "CT", "America/New_York": "ET", "America/Detroit": "ET",
}
ZONES = ("PT", "MT", "CT", "ET")
CAP_MIN = 120.0          # a bar is full at 120 minutes of FAA average delay
TREND_STEP_MIN = 5.0     # a change smaller than this reads as flat


def duration_minutes(text: Any) -> Optional[int]:
    """'2 hours and 18 minutes' -> 138; None when the text holds no duration."""
    t = str(text or "")
    hours = re.search(r"(\d+)\s*hours?", t, re.IGNORECASE)
    mins = re.search(r"(\d+)\s*minutes?", t, re.IGNORECASE)
    if not hours and not mins:
        return None
    return (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)


def minutes_text(minutes: int) -> str:
    """138 -> '2 h 18 m'; 120 -> '2 h'; 45 -> '45 m'."""
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m} m"
    return f"{h} h" if h else f"{m} m"


def zone_of(code: str) -> Optional[str]:
    from desk.airports import TZ
    return _ZONE_OF_TZ.get(TZ.get(code))


def event_minutes(ev: dict[str, Any]) -> tuple[Optional[int], str]:
    """(minutes, label) from one FAA event: its average if given, else its max, else its min."""
    f = ev.get("fields") or {}
    for key in ("avg", "max", "min"):
        m = duration_minutes(f.get(key))
        if m is not None:
            return m, key
    return None, ""


def fill_for(status: str, minutes: Optional[int]) -> float:
    """Bar fill 0..1. Clear is empty. Stop and closure are full. Otherwise FAA minutes / 120, capped."""
    if status == "green":
        return 0.0
    if status == "red":
        return 1.0
    if minutes is None:
        return 0.06            # a delay with no stated length: a sliver, not empty
    return round(min(1.0, max(0.0, minutes / CAP_MIN)), 4)


def score_of(status: str, avg_min: Optional[float]) -> float:
    if status == "red":
        return CAP_MIN
    if status == "green":
        return 0.0
    return min(CAP_MIN, float(avg_min or 0.0))


def trend_for(status: str, avg_min: Optional[float], prev: Optional[dict[str, Any]]) -> Optional[str]:
    """'up' (worse), 'down' (better) or 'flat' against the reading an hour ago.
    A code with no reading then counts as clear when other readings exist for that hour."""
    before = score_of(str((prev or {}).get("level") or "green"), (prev or {}).get("avg_min"))
    now = score_of(status, avg_min)
    if now - before >= TREND_STEP_MIN:
        return "up"
    if before - now >= TREND_STEP_MIN:
        return "down"
    return "flat"


def board_from_events(events: list[dict[str, Any]], prev: Optional[dict[str, dict[str, Any]]] = None) -> list[dict[str, Any]]:
    """One tile per busiest-30 airport. `level` is the old 3-colour value (green, amber, red).
    New in AN12: `status` (green, yellow, orange, red), `fill` (0..1), `avg_min`, `text`, `trend`, `zone`.
    prev is the board.jsonl reading from an hour ago, {code: {level, avg_min}}; None means no reading."""
    level_by_code: dict[str, str] = {}
    kind_by_code: dict[str, str] = {}
    status_by_code: dict[str, str] = {}
    minutes_by_code: dict[str, tuple[int, str]] = {}
    for ev in events:
        if ev.get("source") != "FAA":
            continue
        code = canonical_code(ev.get("airport"))
        lvl = _LEVEL.get(ev.get("kind", ""))
        if not code or not lvl:
            continue
        if _RANK[lvl] > _RANK[level_by_code.get(code, "green")]:
            level_by_code[code] = lvl
            kind_by_code[code] = ev["kind"]
        st = _STATUS[ev["kind"]]
        if _STATUS_RANK[st] > _STATUS_RANK[status_by_code.get(code, "green")]:
            status_by_code[code] = st
        mins, label = event_minutes(ev)
        if mins is not None and mins > minutes_by_code.get(code, (-1, ""))[0]:
            minutes_by_code[code] = (mins, label)
    out = []
    for code in BUSIEST_30:
        status = status_by_code.get(code, "green")
        kind = kind_by_code.get(code, "")
        mins, label = minutes_by_code.get(code, (None, ""))
        if status == "red":
            text = "closed" if kind == "closure" else "ground stop"
        elif status == "green":
            text = "clear"
        elif mins is not None:
            text = f"{label} {minutes_text(mins)}"
        else:
            text = "delays"
        use_min = mins if status in ("yellow", "orange") else None
        out.append({
            "code": code,
            "name": SHORT.get(code, code),
            "level": level_by_code.get(code, "green"),
            "kind": kind,
            "status": status,
            "fill": fill_for(status, mins),
            "avg_min": use_min,
            "text": text,
            "trend": trend_for(status, use_min, prev.get(code)) if prev else None,
            "zone": zone_of(code),
            "lat": AIRPORTS[code][1] if code in AIRPORTS else None,
            "lon": AIRPORTS[code][2] if code in AIRPORTS else None,
        })
    return out


def zone_counts(board: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Affected hubs per zone, from the 30 busiest: {'PT': {'affected': 2, 'hubs': 5}, ...}."""
    out = {z: {"affected": 0, "hubs": 0} for z in ZONES}
    for t in board:
        z = t.get("zone")
        if z in out:
            out[z]["hubs"] += 1
            if t.get("status", "green") != "green":
                out[z]["affected"] += 1
    return out


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
