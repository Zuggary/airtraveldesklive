"""Spoken and captioned times for the desk: 12-hour am/pm in the airport's zone, zone said once.

No 'UTC' and no 'Z' times on air (CoS rule, 2026-11-14). Standard library only.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

ZONE_WORDS = {
    "America/New_York": "Eastern", "America/Detroit": "Eastern", "America/Chicago": "Central",
    "America/Denver": "Mountain", "America/Phoenix": "Mountain", "America/Boise": "Mountain",
    "America/Los_Angeles": "Pacific", "America/Anchorage": "Alaska", "Pacific/Honolulu": "Hawaii",
}
EASTERN = "America/New_York"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
_MON3 = {m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_FAA_WHEN = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})\s+at\s+(\d{1,2}):(\d{2})\s*UTC", re.IGNORECASE)


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def zone_word(tz: Optional[str]) -> str:
    return ZONE_WORDS.get(tz or EASTERN, "Eastern")


def clock12(dt_utc: datetime, tz: Optional[str]) -> str:
    """'5:30 pm' (on the hour: '5 pm')."""
    loc = dt_utc.astimezone(ZoneInfo(tz or EASTERN))
    h = loc.hour % 12 or 12
    suffix = "am" if loc.hour < 12 else "pm"
    return f"{h} {suffix}" if loc.minute == 0 else f"{h}:{loc.minute:02d} {suffix}"


def spoken_date(d, today) -> str:
    """'November 14th'; the year only when it is not the current year."""
    s = f"{MONTHS[d.month - 1]} {ordinal(d.day)}"
    return s if d.year == today.year else f"{s}, {d.year}"


def say_when(dt_utc: datetime, tz: Optional[str], now_utc: Optional[datetime] = None, zone: bool = True) -> str:
    """'5:30 pm Eastern' today; 'tomorrow at ...'; a full weekday within a week; else 'November 20th at ...'."""
    now = now_utc or datetime.now(timezone.utc)
    z = ZoneInfo(tz or EASTERN)
    loc, nloc = dt_utc.astimezone(z), now.astimezone(z)
    clock = clock12(dt_utc, tz) + (f" {zone_word(tz)}" if zone else "")
    days = (loc.date() - nloc.date()).days
    if days == 0 or (dt_utc < now and now - dt_utc < timedelta(hours=36)):   # a listed end that just passed: say the time only
        return clock
    if days == 1:
        return "tomorrow at " + clock
    if 2 <= days <= 6:
        return f"{WEEKDAYS[loc.weekday()]} at {clock}"
    return f"{spoken_date(loc.date(), nloc.date())} at {clock}"


def parse_faa_when(text: str, now_utc: Optional[datetime] = None) -> Optional[datetime]:
    """'Nov 14 at 14:15 UTC.' -> aware UTC datetime (year chosen nearest to now)."""
    m = _FAA_WHEN.search(text or "")
    if not m or m.group(1).lower() not in _MON3:
        return None
    now = now_utc or datetime.now(timezone.utc)
    best = None
    for yr in (now.year - 1, now.year, now.year + 1):
        try:
            c = datetime(yr, _MON3[m.group(1).lower()], int(m.group(2)), int(m.group(3)), int(m.group(4)), tzinfo=timezone.utc)
        except ValueError:
            continue
        if best is None or abs(c - now) < abs(best - now):
            best = c
    return best


def caption_when(dt_utc: datetime, tz: Optional[str], now_utc: Optional[datetime] = None) -> str:
    """Short on-screen form: '5:30 pm ET', or 'Nov 14, 6:15 am PT' on another day."""
    now = now_utc or datetime.now(timezone.utc)
    z = ZoneInfo(tz or EASTERN)
    loc = dt_utc.astimezone(z)
    ab = {"Eastern": "ET", "Central": "CT", "Mountain": "MT", "Pacific": "PT", "Alaska": "AKT", "Hawaii": "HT"}[zone_word(tz)]
    base = f"{clock12(dt_utc, tz)} {ab}"
    if loc.date() == now.astimezone(z).date():
        return base
    return f"{MONTHS[loc.month - 1][:3]} {loc.day}, {base}"
