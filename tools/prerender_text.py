"""Plain-text helpers for the build-time pre-render (AN23 phase 1).

The 5-minute build writes live status, weather and a timestamp into the HTML as text, so a
reader and a search crawler see them with JavaScript off. The browser script then refreshes
the same elements. Every value comes from the data files; nothing is invented here.

Stdlib only. No network.
"""
from __future__ import annotations

from html import escape

import json
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

FALLBACK_STATUS = "Checking the FAA's status page; if this stays blank see nasstatus.faa.gov"
STALE_MIN = 30

WORD_CLEAR = "No FAA delays reported"
WORD_STOP = "Ground stop"
WORD_GDP = "Ground delay program"
WORD_DELAY = "Delays"
WORD_CLOSED = "Closed"
WORD_NIGHT = "Closed overnight"

LEVEL_TEXT = {
    "clear": "Clear: no FAA delay or ground stop listed.",
    "delay": "Delays: FAA delay program in effect.",
    "stop": "Ground stop: FAA ground stop in effect.",
    "closed": "Closed: FAA airport closure in effect.",
    "night": "Closed overnight: the FAA lists a daily closure.",
}
BADGE_CLASS = {
    "clear": "badge badge--clear",
    "delay": "badge badge--delay",
    "stop": "badge badge--stop",
    "closed": "badge badge--stop",
    "night": "badge badge--night",
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


def faa_age_parts(iso: Any, tz: str, now: datetime, stale: bool) -> tuple[str, str]:
    """AN35: the one place a page states the FAA data age. Returns the text before and after the 'FAA NAS status' source link.

    Fresh: 'FAA data 4 min old, checked 11:17 PM PST. Source: [FAA NAS status].' Stale: 'Source: [FAA NAS status], last checked 11:17 PM PST.'
    (the stale banner carries the age). Same rule as faaParts in the page scripts.
    """
    clock = clock_label(iso, tz)
    if not clock:
        return "Source: ", ", check time unknown."
    if stale:
        return "Source: ", f", last checked {clock}."
    m = age_minutes(iso, now)
    age = "under 1 min" if (m or 0) < 1 else dur_text(m)
    return f"FAA data {age} old, checked {clock}. Source: ", "."


def faa_age_plain(iso: Any, tz: str, now: datetime, stale: bool) -> str:
    """The same line as plain text (no link), for the home page: 'FAA data 4 min old, checked 11:17 PM PST.'"""
    before, after = faa_age_parts(iso, tz, now, stale)
    if stale or not clock_label(iso, tz):
        return f"FAA NAS status{after}"
    return before.removesuffix(" Source: ")


def stale_text(iso: Any, now: datetime) -> str:
    """The stale notice sentence (without the FAA link), or '' when the data is fresh enough."""
    m = age_minutes(iso, now)
    if not is_stale(m):
        return ""
    return f"This data is {old_text(m)}, not live. FAA's own page:"


STALE_LINK_HTML = (
    '<a class="stale-link" href="https://nasstatus.faa.gov" target="_blank" rel="noopener noreferrer">'
    '<span class="sn-wide">nasstatus.faa.gov</span><span class="sn-short">FAA status</span></a>'
)


def stale_notice_html(iso: Any, now: datetime) -> str:
    """AN34 r2: the stale notice as HTML that fits one line on a phone: the long words and the long link text
    hide below 700 px (CSS .sn-long, .sn-wide), the short link text shows instead. '' when fresh."""
    text = stale_text(iso, now)
    if not text:
        return ""
    main = text.removesuffix(" FAA's own page:")
    return f'{escape(main)} <span class="sn-long">FAA\'s own page:</span> {STALE_LINK_HTML}'


def short_check_text(iso: Any, tz: str, now: datetime) -> str:
    """Compact home verdict clock, with a day for readings over a day old."""
    dt = parse_utc(iso)
    if not dt:
        return "time unknown"
    local = dt.astimezone(ZoneInfo(tz))
    minutes = age_minutes(iso, now)
    day = (local.strftime("%a") if minutes < 10080 else f"{local.strftime('%b')} {local.day}") + " " if minutes >= 1440 else ""
    return f"{day}{local.strftime('%I:%M %p').lstrip('0')} ({ago_text(minutes)})"


def as_of_text(iso: Any, tz: str, now: datetime) -> str:
    """'as of 1:50 AM PST (12 hours ago)', or 'as of an unknown time'."""
    clock = clock_label(iso, tz)
    if not clock:
        return "as of an unknown time"
    dt = parse_utc(iso)
    if tz and ZoneInfo is not None:
        dt = dt.astimezone(ZoneInfo(tz))
    return f"as of {dt.strftime('%b')} {dt.day}, {dt.year}, {clock} ({ago_text(age_minutes(iso, now))})"


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


_LISTED_UTC_RE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}) at (\d{2}):(\d{2}) UTC")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def listed_utc(text: Any, now: datetime) -> datetime | None:
    """A FAA listed time such as 'Nov 20 at 14:15 UTC.' as a UTC time. The year is the current one (next year for a month far behind)."""
    m = _LISTED_UTC_RE.search(str(text or ""))
    if not m or m.group(1) not in _MONTHS:
        return None
    month = _MONTHS.index(m.group(1)) + 1
    year = now.year + (1 if month < now.month - 6 else 0)
    try:
        return datetime(year, month, int(m.group(2)), int(m.group(3)), int(m.group(4)), tzinfo=timezone.utc)
    except ValueError:
        return None


def _local_clock(dt: datetime, tz: str) -> str:
    """'6:15 AM' in the airport's own zone (UTC when the zone is unknown)."""
    local = dt
    if tz and ZoneInfo is not None:
        try:
            local = dt.astimezone(ZoneInfo(tz))
        except Exception:  # unknown zone id
            local = dt
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def closure_schedule(ev: dict[str, Any], tz: str, now: datetime) -> dict[str, Any] | None:
    """AN35: a closure the FAA lists as daily ('CLSD DLY 0730-1415', UTC hours) is a scheduled closure.

    Returns None for any other closure (that stays an alarm). Otherwise {in_window, reopen, close}: whether the
    airport is inside its daily closed hours now, the next reopening and the next closing in the airport's own
    clock ('6:15 AM'). A listing whose end time has passed counts as outside the window. Same rule as ATD.closureSchedule in lib.js.
    """
    if not isinstance(ev, dict) or ev.get("kind") != "closure":
        return None
    fields = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
    daily = str(ev.get("daily") or fields.get("daily") or "")
    m = re.fullmatch(r"(\d{2})(\d{2})-(\d{2})(\d{2})", daily)
    if not m:
        return None
    s_min = int(m.group(1)) * 60 + int(m.group(2))
    e_min = int(m.group(3)) * 60 + int(m.group(4))
    if s_min == e_min or s_min >= 1440 or e_min >= 1440:
        return None
    t = now.hour * 60 + now.minute
    in_window = (s_min <= t < e_min) if s_min < e_min else (t >= s_min or t < e_min)
    start = listed_utc(ev.get("start") or fields.get("start"), now)
    end = listed_utc(ev.get("reopen") or fields.get("reopen"), now)
    if (start and now < start - timedelta(days=1)) or (end and now >= end):
        in_window = False

    def next_at(minute: int) -> datetime:
        day = now.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
        return day if day > now else day + timedelta(days=1)

    return {"in_window": in_window, "reopen": _local_clock(next_at(e_min), tz), "close": _local_clock(next_at(s_min), tz)}


def effective_level(entry: dict[str, Any], now: datetime | None = None) -> str:
    """clear, delay, stop, closed or night (a scheduled daily closure, inside its hours), the same rule the browser script uses.

    AN35: a closure with a daily window is calm: 'night' inside the closed hours, and ignored outside them.
    Any other closure is 'closed' (an alarm).
    """
    level = str(entry.get("level") or "clear")
    events = [e for e in (entry.get("events") or []) if isinstance(e, dict)]
    closures = [e for e in events if e.get("kind") == "closure"]
    if closures or level == "closed":
        tz = str(entry.get("tz") or "")
        sched = [closure_schedule(e, tz, now or now_utc()) for e in closures]
        if closures and all(sched):
            if any(x["in_window"] for x in sched if x):
                return "night"
            rest = [e for e in events if e.get("kind") != "closure"]
            if any(e.get("kind") == "ground_stop" for e in rest):
                return "stop"
            return "delay" if rest else "clear"
        return "closed"
    return level if level in LEVEL_TEXT and level != "night" else "clear"


def status_word(entry: dict[str, Any], now: datetime | None = None) -> str:
    """Plain status words for one airport entry from data/airports.json."""
    lvl = effective_level(entry, now)
    if lvl == "clear":
        return WORD_CLEAR
    if lvl == "stop":
        return WORD_STOP
    if lvl == "closed":
        return WORD_CLOSED
    if lvl == "night":
        return WORD_NIGHT
    kinds = {e.get("kind") for e in (entry.get("events") or []) if isinstance(e, dict)}
    return WORD_GDP if "ground_delay" in kinds else WORD_DELAY


def mph(kt: Any) -> int:
    """Knots to whole miles per hour."""
    return round(float(kt) * 1.15078)


def wind_text(wx: dict[str, Any], gusts: bool = True) -> str:
    """'calm' or '10 mph gusting 23 mph' (AN34 r2: miles per hour for travelers). '' when the wind is not in the data."""
    wind = wx.get("wind_kt")
    if wind is None:
        return ""
    if round(float(wind)) == 0:
        return "calm"
    out = f"{mph(wind)} mph"
    gust = wx.get("gust_kt")
    if gusts and gust:
        out += f" gusting {mph(gust)} mph"
    return out


def temp_text(wx: dict[str, Any]) -> str:
    """'54°F' from the METAR temperature, or '' when the feed had none."""
    t = wx.get("temp_f")
    if t is None:
        return ""
    try:
        return f"{round(float(t))}\u00b0F"
    except (TypeError, ValueError):
        return ""


def weather_summary(wx: dict[str, Any] | None) -> str:
    """'clear, wind 9 kt' for the meta description and chips. '' when there is no weather text."""
    if not isinstance(wx, dict) or not wx.get("now_text"):
        return ""
    out = str(wx["now_text"])
    temp = temp_text(wx)
    if temp:
        out += f", {temp}"
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


# The home and airport builds share the browser card mapper's vocabulary.
CARD_REASON_MAPPER_JS = (Path(__file__).resolve().parents[1] / "lib.js").read_text(encoding="utf-8").split(
    "  // BEGIN CARD REASON MAPPER\n", 1
)[1].split("  // END CARD REASON MAPPER", 1)[0]
_CARD_REASON_WORDS = json.loads(CARD_REASON_MAPPER_JS.split("=", 1)[1].split(";", 1)[0])


def reason_text(reason: Any) -> str:
    parts = []
    for part in str(reason or "").split(";"):
        part = re.sub(r"^TM\s+Initiatives\s*:\s*", "", part.strip(), flags=re.I)
        terms = list(filter(None, re.split(r"\s*:\s*", part)))
        known = any(term.upper() in _CARD_REASON_WORDS for term in terms)
        words = [_CARD_REASON_WORDS.get(term.upper(), term.lower() if known else
                                  re.sub(r"[a-z]+", lambda m: m[0].capitalize(), term.lower()))
                 for term in terms]
        joiner = " due to " if terms and terms[0].upper() in ("MIT", "MINIT") else ", "
        phrase = joiner.join(dict.fromkeys(words))
        if phrase:
            parts.append(phrase[0].upper() + phrase[1:])
    return "; ".join(parts)


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


def dateline(local: datetime) -> str:
    """AN34 round 4: 'Sunday night, 10:27 PM', a dated line in place of a pulsing 'Right now'. Same rule as lib.js dateline."""
    clock = local.strftime("%I:%M %p").lstrip("0")
    day = local.strftime("%A")
    if local.hour < 5:
        return f"Early {day}, {clock}"
    part = "morning" if local.hour < 12 else "afternoon" if local.hour < 17 else "evening" if local.hour < 21 else "night"
    return f"{day} {part}, {clock}"


def airport_dateline(updated_utc: str, tz: str, place: str) -> str:
    """'Early Monday, 1:27 AM in Atlanta': the FAA check time in the airport's own zone. '' when unknown."""
    dt = parse_utc(updated_utc)
    if not dt:
        return ""
    try:
        local = dt.astimezone(ZoneInfo(tz)) if tz else dt
    except Exception:  # unknown zone name
        return ""
    return f"{dateline(local)} in {place}"


def fallback_status(state: dict[str, Any], now: datetime | None = None) -> str:
    """A dated build fallback; never infer a clear reading from absent data."""
    iso = state.get("faa_updated_utc") or state.get("updated_utc")
    if now is not None and (is_stale(age_minutes(iso, now)) or "FAA" in state.get("stale_feeds", [])):
        return "Last FAA check " + short_check_text(iso, "America/New_York", now)
    clock = clock_label(iso, "America/New_York")
    if not clock:
        return FALLBACK_STATUS
    events = [e for e in state.get("events", []) if e.get("source") == "FAA"]
    summary = f"{len(events)} FAA programs listed" if events else ("No FAA program listed" if state.get("board") else "airport readings unavailable")
    return f"Latest FAA check {clock}: {summary}"
