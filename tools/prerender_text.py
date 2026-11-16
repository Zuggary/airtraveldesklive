"""Plain-text helpers for the build-time pre-render (AN23 phase 1).

The 5-minute build writes live status, weather and a timestamp into the HTML as text, so a
reader and a search crawler see them with JavaScript off. The browser script then refreshes
the same elements. Every value comes from the data files; nothing is invented here.

Stdlib only. No network.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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


def dur_text(minutes: int | None) -> str:
    """One age unit everywhere: under 60 min -> 'N min'; under 24 h -> 'N hour(s)'; then 'N day(s)'."""
    if minutes is None:
        return "age unknown"
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 1440:
        h = minutes // 60
        return "1 hour" if h == 1 else f"{h} hours"
    d = minutes // 1440
    return "1 day" if d == 1 else f"{d} days"


def ago_text(minutes: int | None) -> str:
    if minutes is None:
        return "age unknown"
    if minutes < 1:
        return "less than 1 min ago"
    return f"{dur_text(minutes)} ago"


def old_text(minutes: int | None) -> str:
    if minutes is None:
        return "of unknown age"
    if minutes < 60:
        return "1 minute old" if minutes == 1 else f"{minutes} minutes old"
    return f"{dur_text(minutes)} old"


def is_stale(minutes: int | None) -> bool:
    """True when the data is older than STALE_MIN, or its age is unknown."""
    return minutes is None or minutes > STALE_MIN


def checked_text(iso: Any, tz: str, now: datetime, last: bool = False) -> str:
    """'checked 3:50 AM PST (12 min ago)' ('last checked' when last is true), or 'check time unknown'."""
    clock = clock_label(iso, tz)
    if not clock:
        return "check time unknown"
    return f"{'last checked' if last else 'checked'} {clock} ({ago_text(age_minutes(iso, now))})"


def stale_text(iso: Any, now: datetime) -> str:
    """The stale notice sentence (without the FAA link), or '' when the data is fresh enough."""
    m = age_minutes(iso, now)
    if not is_stale(m):
        return ""
    return f"This data is {old_text(m)}. It normally updates about every 5 minutes. For the FAA's own page, go to"


def as_of_text(iso: Any, tz: str, now: datetime) -> str:
    """'as of 1:50 AM PST (12 hours ago)', or 'as of an unknown time'."""
    clock = clock_label(iso, tz)
    if not clock:
        return "as of an unknown time"
    return f"as of {clock} ({ago_text(age_minutes(iso, now))})"


ZONE_IDS = {
    "eastern": "America/New_York", "central": "America/Chicago", "mountain": "America/Denver",
    "pacific": "America/Los_Angeles", "alaska": "America/Anchorage", "hawaii": "Pacific/Honolulu",
}
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b(?:\s+(eastern|central|mountain|pacific|alaska|hawaii))?", re.I)


def forecast_end(text: Any, issued_iso: Any, tz: str = "") -> datetime | None:
    """End (or change) time named in a forecast window such as 'clear through 2 am Pacific', in UTC.

    The first time of day after the issue time that matches the clock in the text. None when the text
    has no clock time or the issue time is bad. Same rule as ATD.forecastEnd in lib.js.
    """
    m = _TIME_RE.search(str(text or ""))
    issued = parse_utc(issued_iso)
    if not m or issued is None or ZoneInfo is None:
        return None
    zone = ZONE_IDS.get((m.group(4) or "").lower()) or tz
    if not zone:
        return None
    try:
        z = ZoneInfo(zone)
    except Exception:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    minute = int(m.group(2) or 0)
    local = issued.astimezone(z)
    for add in (0, 1, 2):
        day = (local + timedelta(days=add)).date()
        cand = datetime(day.year, day.month, day.day, hour, minute, tzinfo=z).astimezone(timezone.utc)
        if cand > issued:
            return cand
    return None


def forecast_expired(text: Any, issued_iso: Any, tz: str, now: datetime) -> bool:
    """True when the forecast window has ended (or cannot be read) at 'now'."""
    end = forecast_end(text, issued_iso, tz)
    return end is None or end <= now


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


def stale_chip_text(entry: dict[str, Any], iso: Any, tz: str) -> str:
    """'As of 1:50 AM PST: no FAA delays reported'. Same facts as the live chip, dated."""
    clock = clock_label(iso, tz)
    word = status_word(entry)
    word = word[0].lower() + word[1:]
    return f"As of {clock}: {word}" if clock else f"As of an unknown time: {word}"


_REASON_PREFIX = {"WX": "weather", "VOLUME": "traffic volume", "RWY/TWY": "runway or taxiway",
                  "EQUIPMENT": "equipment", "STAFFING": "staffing", "OTHER": "other"}


def reason_plain(reason: Any) -> str:
    """Plain words for a raw FAA reason: 'low ceilings; WX:Wind' becomes 'low ceilings; weather, wind'."""
    out = []
    for part in str(reason or "").split(";"):
        part = part.strip()
        m = re.match(r"^([A-Za-z/]+):\s*(.*)$", part)
        if m and m.group(1).upper() in _REASON_PREFIX:
            prefix = _REASON_PREFIX[m.group(1).upper()]
            rest = m.group(2).lower()
            part = prefix if (not rest or rest in (prefix, "volume")) else f"{prefix}, {rest}"
        if part:
            out.append(part)
    return "; ".join(out)
