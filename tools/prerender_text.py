"""Plain-text helpers for the build-time pre-render (AN23 phase 1).

The 5-minute build writes live status, weather and a timestamp into the HTML as text, so a
reader and a search crawler see them with JavaScript off. The browser script then refreshes
the same elements. Every value comes from the data files; nothing is invented here.

Stdlib only. No network.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

FALLBACK_STATUS = "Live status loads here; the FAA's own page is nasstatus.faa.gov"
STALE_MIN = 30

WORD_CLEAR = "No FAA delays reported"
WORD_STOP = "Ground stop"
WORD_GDP = "Ground delay program"
WORD_DELAY = "Delays"
WORD_CLOSED = "Closed"

LEVEL_TEXT = {
    "clear": "Clear — no FAA delay or ground stop listed.",
    "delay": "Delays — FAA delay program in effect.",
    "stop": "Ground stop — FAA ground stop in effect.",
    "closed": "Closed — FAA airport closure in effect.",
}
BADGE_CLASS = {
    "clear": "badge badge--clear",
    "delay": "badge badge--delay",
    "stop": "badge badge--stop",
    "closed": "badge badge--stop",
}


def parse_utc(iso: Any) -> datetime | None:
    """Parse an ISO time ending in Z (or with an offset). None when it is missing or bad."""
    text = str(iso or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_label(iso: Any, tz: str = "") -> str:
    """'3:50 AM PST' for a UTC time in the given IANA zone; UTC when the zone is unknown. '' when the time is bad."""
    dt = parse_utc(iso)
    if dt is None:
        return ""
    local = dt
    if tz and ZoneInfo is not None:
        try:
            local = dt.astimezone(ZoneInfo(tz))
        except Exception:  # unknown zone id
            local = dt
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{hour}:{local.minute:02d} {ampm} {local.tzname() or 'UTC'}"


def age_minutes(iso: Any, now: datetime) -> int | None:
    dt = parse_utc(iso)
    if dt is None:
        return None
    return max(0, int((now - dt).total_seconds() // 60))


def ago_text(minutes: int | None) -> str:
    if minutes is None:
        return "age unknown"
    if minutes < 1:
        return "less than 1 min ago"
    if minutes >= 120:
        return f"{minutes // 60} hours ago"
    return f"{minutes} min ago"


def old_text(minutes: int | None) -> str:
    if minutes is None:
        return "of unknown age"
    if minutes >= 120:
        return f"{minutes // 60} hours old"
    return f"{minutes} minutes old"


def checked_text(iso: Any, tz: str, now: datetime) -> str:
    """'checked 3:50 AM PST (12 min ago)', or 'check time unknown'."""
    clock = clock_label(iso, tz)
    if not clock:
        return "check time unknown"
    return f"checked {clock} ({ago_text(age_minutes(iso, now))})"


def stale_text(iso: Any, now: datetime) -> str:
    """The stale notice sentence (without the FAA link), or '' when the data is fresh enough."""
    m = age_minutes(iso, now)
    if m is not None and m <= STALE_MIN:
        return ""
    return f"This data is {old_text(m)}. It normally updates about every 5 minutes. For the FAA's own page, go to"


def effective_level(entry: dict[str, Any]) -> str:
    """clear, delay, stop or closed, the same rule the browser script uses."""
    level = str(entry.get("level") or "clear")
    events = entry.get("events") or []
    if level == "closed" or any(isinstance(e, dict) and e.get("kind") == "closure" for e in events):
        return "closed"
    return level if level in LEVEL_TEXT else "clear"


def status_word(entry: dict[str, Any]) -> str:
    """Plain status words for one airport entry from data/airports.json."""
    lvl = effective_level(entry)
    if lvl == "clear":
        return WORD_CLEAR
    if lvl == "stop":
        return WORD_STOP
    if lvl == "closed":
        return WORD_CLOSED
    kinds = {e.get("kind") for e in (entry.get("events") or []) if isinstance(e, dict)}
    return WORD_GDP if "ground_delay" in kinds else WORD_DELAY


def wind_text(wx: dict[str, Any], gusts: bool = True) -> str:
    """'calm (0 kt)' or '9 kt gusting 20 kt'. '' when the wind is not in the data."""
    wind = wx.get("wind_kt")
    if wind is None:
        return ""
    kt = round(float(wind))
    if kt == 0:
        return "calm (0 kt)"
    out = f"{kt} kt"
    gust = wx.get("gust_kt")
    if gusts and gust:
        out += f" gusting {round(float(gust))} kt"
    return out


def weather_summary(wx: dict[str, Any] | None) -> str:
    """'clear, wind 9 kt' for the meta description and chips. '' when there is no weather text."""
    if not isinstance(wx, dict) or not wx.get("now_text"):
        return ""
    out = str(wx["now_text"])
    wind = wind_text(wx)
    return f"{out}, wind {wind}" if wind else out


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
