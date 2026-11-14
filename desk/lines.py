from __future__ import annotations

import re
from typing import Any, Optional

from desk.airports import nearest_airport, spoken

_TZ_MAP = {
    "EST": "Eastern",
    "EDT": "Eastern",
    "CST": "Central",
    "CDT": "Central",
    "MST": "Mountain",
    "MDT": "Mountain",
    "PST": "Pacific",
    "PDT": "Pacific",
}
_TZ_RE = re.compile(r"\b(EST|EDT|CST|CDT|MST|MDT|PST|PDT)\.?", re.IGNORECASE)
_HOURS_RE = re.compile(r"(\d+)\s*hours?", re.IGNORECASE)
_MINS_RE = re.compile(r"(\d+)\s*minutes?", re.IGNORECASE)


def _clean_time(text: str) -> str:
    """Expand US timezone abbreviations and strip trailing periods."""
    if not text:
        return ""
    expanded = _TZ_RE.sub(lambda m: _TZ_MAP[m.group(1).upper()], text.strip())
    return expanded.rstrip(".").strip()


def _parse_duration_minutes(text: str) -> Optional[int]:
    """Parse FAA duration strings like '2 hours and 40 minutes' into total minutes."""
    if not text:
        return None
    hm = _HOURS_RE.search(text)
    mm = _MINS_RE.search(text)
    if not hm and not mm:
        return None
    hours = int(hm.group(1)) if hm else 0
    mins = int(mm.group(1)) if mm else 0
    return hours * 60 + mins


def _nws_suffix(event: dict[str, Any]) -> str:
    if event.get("status") != "CONFIRMED":
        return ""
    for src in event.get("sources") or []:
        if src.startswith("NWS:"):
            alert = src[4:].strip()
            if alert:
                return f", and the National Weather Service has a {alert} in effect"
    return ""


def _airport_for_closure(code: str) -> str:
    name = spoken(code)
    lower = name.lower()
    if "airport" in lower or "international" in lower or "national" in lower:
        return name
    return f"{name} airport"


def _squawk_line(change_type: str, event: dict[str, Any]) -> str:
    fields = event.get("fields") or {}
    callsign = (fields.get("callsign") or "").strip()
    cs_part = f", call sign {' '.join(callsign)}" if callsign else ""

    lat = fields.get("lat")
    lon = fields.get("lon")
    near_name = None
    if lat is not None and lon is not None:
        near_name = nearest_airport(float(lat), float(lon), max_km=150.0)
    near_part = f", near {near_name}" if near_name else ""

    if change_type == "cleared":
        return f"An aircraft{cs_part}{near_part}, is no longer squawking 7700. Source: adsb.lol."
    return (
        f"An aircraft{cs_part}{near_part}, is showing the general emergency code on its transponder. "
        "That is not a confirmed emergency. Source: adsb.lol."
    )


def _ground_stop_line(change_type: str, event: dict[str, Any], prev: Optional[dict[str, Any]]) -> str:
    name = spoken(event.get("airport", ""))
    fields = event.get("fields") or {}
    reason = (event.get("reason") or "").strip()
    end_time = _clean_time(fields.get("end_time", ""))
    nws = _nws_suffix(event)

    if change_type == "cleared":
        return f"The ground stop at {name} has ended, per the FAA."

    reason_part = f" for {reason}" if reason else ""
    if change_type == "updated" and prev:
        old_end = _clean_time((prev.get("fields") or {}).get("end_time", ""))
        if end_time and old_end and end_time != old_end:
            time_part = f", now until {end_time}, changed from {old_end}"
        elif end_time:
            time_part = f", until {end_time}"
        else:
            time_part = ""
        return f"Ground stop at {name}{reason_part}{time_part}{nws}, per the FAA."

    until_part = f", until {end_time}" if end_time else ""
    return f"New ground stop at {name}{reason_part}{until_part}{nws}, per the FAA."


def _ground_delay_line(change_type: str, event: dict[str, Any], prev: Optional[dict[str, Any]]) -> str:
    name = spoken(event.get("airport", ""))
    fields = event.get("fields") or {}
    reason = (event.get("reason") or "").strip()
    avg = (fields.get("avg") or "").strip()
    max_d = (fields.get("max") or "").strip()
    nws = _nws_suffix(event)

    if change_type == "cleared":
        return f"The ground delay at {name} has ended, per the FAA."

    reason_part = f" for {reason}" if reason else ""
    if change_type == "updated":
        old_fields = (prev or {}).get("fields") or {}
        old_avg = (old_fields.get("avg") or "").strip()
        old_max = (old_fields.get("max") or "").strip()
        if avg and old_avg and avg != old_avg:
            new_m = _parse_duration_minutes(avg)
            old_m = _parse_duration_minutes(old_avg)
            if new_m is not None and old_m is not None and new_m > old_m:
                detail = f", now averaging {avg}, up from {old_avg}"
            elif new_m is not None and old_m is not None and new_m < old_m:
                detail = f", now averaging {avg}, down from {old_avg}"
            else:
                detail = f", now averaging {avg}, changed from {old_avg}"
        elif max_d and old_max and max_d != old_max:
            detail = f", max delay now {max_d}, changed from {old_max}"
        elif avg:
            detail = f", now averaging {avg}"
        else:
            detail = ""
        return f"Ground delay at {name}{reason_part}{detail}{nws}, per the FAA."

    avg_part = f", averaging {avg}" if avg else ""
    return f"New ground delay at {name}{reason_part}{avg_part}{nws}, per the FAA."


def _delay_line(change_type: str, event: dict[str, Any], prev: Optional[dict[str, Any]]) -> str:
    name = spoken(event.get("airport", ""))
    fields = event.get("fields") or {}
    direction = (fields.get("direction") or "").strip()
    min_v = (fields.get("min") or "").strip()
    max_v = (fields.get("max") or "").strip()
    trend = (fields.get("trend") or "").strip()
    reason = (event.get("reason") or "").strip()
    nws = _nws_suffix(event)

    if change_type == "cleared":
        dir_prefix = f"{direction.lower()} " if direction else ""
        return f"The {dir_prefix}delays at {name} have ended, per the FAA."

    label = f"{direction} delays" if direction else "Delays"
    if min_v and max_v:
        range_part = f" of {min_v} to {max_v}"
    elif max_v:
        range_part = f" up to {max_v}"
    elif min_v:
        range_part = f" starting at {min_v}"
    else:
        range_part = ""

    reason_part = ""
    if reason and not reason.upper().startswith("OTHER:"):
        reason_part = f" for {reason}"

    trend_part = f", and {trend.lower()}" if trend else ""
    if change_type == "updated" and prev:
        old_fields = prev.get("fields") or {}
        if (old_fields.get("min"), old_fields.get("max")) != (min_v, max_v) and min_v and max_v:
            range_part = f" now {min_v} to {max_v}"

    return f"{label} at {name}{reason_part}{range_part}{trend_part}{nws}, per the FAA."


def _closure_line(change_type: str, event: dict[str, Any], prev: Optional[dict[str, Any]]) -> str:
    name = _airport_for_closure(event.get("airport", ""))
    fields = event.get("fields") or {}
    reopen = _clean_time(fields.get("reopen", ""))

    if change_type == "cleared":
        return f"{name} has reopened, per the FAA."

    if change_type == "updated" and prev:
        old_reopen = _clean_time((prev.get("fields") or {}).get("reopen", ""))
        if reopen and old_reopen and reopen != old_reopen:
            return f"{name} closure updated, now reopening {reopen}, per the FAA."
        reopen_part = f", reopening {reopen}" if reopen else ""
        return f"{name} remains closed{reopen_part}, per the FAA."

    reopen_part = f", reopening {reopen}" if reopen else ""
    return f"{name} is closed{reopen_part}, per the FAA."


def line(change: dict[str, Any]) -> str:
    """Format a single change dict into a spoken broadcast sentence."""
    change_type = change["change"]
    event = change["event"]
    prev = change.get("previous")
    kind = event.get("kind", "")

    if kind == "squawk7700":
        return _squawk_line(change_type, event)
    if kind == "ground_stop":
        return _ground_stop_line(change_type, event, prev)
    if kind == "ground_delay":
        return _ground_delay_line(change_type, event, prev)
    if kind == "delay":
        return _delay_line(change_type, event, prev)
    if kind == "closure":
        return _closure_line(change_type, event, prev)

    name = spoken(event.get("airport", ""))
    return f"Advisory at {name}, per the FAA."


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def recap(events: list[dict[str, Any]]) -> str:
    """Format a summary recap line for active FAA events."""
    faa_events = [ev for ev in events if ev.get("source") == "FAA"]
    if not faa_events:
        return "Right now there are no FAA delays."

    stops = [ev for ev in faa_events if ev.get("kind") == "ground_stop"]
    ground_delays = [ev for ev in faa_events if ev.get("kind") == "ground_delay"]
    delays = [ev for ev in faa_events if ev.get("kind") == "delay"]
    closures = [ev for ev in faa_events if ev.get("kind") == "closure"]

    parts: list[str] = []
    if stops:
        parts.append(_plural(len(stops), "ground stop", "ground stops"))
    if ground_delays:
        parts.append(_plural(len(ground_delays), "ground delay", "ground delays"))
    if delays:
        dirs = {(ev.get("fields") or {}).get("direction", "").strip().lower() for ev in delays}
        if dirs == {"departure"}:
            parts.append(_plural(len(delays), "airport with departure delays", "airports with departure delays"))
        elif dirs == {"arrival"}:
            parts.append(_plural(len(delays), "airport with arrival delays", "airports with arrival delays"))
        else:
            parts.append(_plural(len(delays), "airport with delays", "airports with delays"))
    if closures:
        parts.append(_plural(len(closures), "closure", "closures"))

    summary = f"Right now: {', '.join(parts)}."

    longest_ev: Optional[dict[str, Any]] = None
    longest_mins = -1
    for ev in ground_delays:
        avg = (ev.get("fields") or {}).get("avg", "")
        mins = _parse_duration_minutes(avg)
        if mins is not None and mins > longest_mins:
            longest_mins = mins
            longest_ev = ev

    if longest_ev is not None:
        avg_str = (longest_ev.get("fields") or {})["avg"]
        return (
            f"{summary} The longest average delay is at "
            f"{spoken(longest_ev.get('airport', ''))}, {avg_str}, per the FAA."
        )
    return f"{summary[:-1]}, per the FAA."


def still(event: dict[str, Any]) -> str:
    """Heartbeat line: restate one event that is still in effect."""
    text = line({"change": "new", "event": event})
    if text.startswith("New "):
        text = text[4:]
        text = text[0].upper() + text[1:]
    return "Still in effect: " + text[0].lower() + text[1:]
