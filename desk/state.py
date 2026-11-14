from __future__ import annotations

from typing import Any, Optional

from desk.feeds import is_weather


def apply_status(
    events: list[dict[str, Any]],
    nws_by_airport: Optional[dict[str, list[str]]] = None,
) -> list[dict[str, Any]]:
    """Apply OFFICIAL / CONFIRMED / UNCONFIRMED status and sources list to events."""
    nws_map = nws_by_airport or {}
    for ev in events:
        if ev.get("kind") == "squawk7700" or ev.get("source") == "adsb.lol":
            ev["status"] = "UNCONFIRMED"
            ev["sources"] = ["adsb.lol"]
            continue

        airport = ev.get("airport", "")
        alerts = [a for a in (nws_map.get(airport) or []) if a]
        if is_weather(ev.get("reason", "")) and alerts:
            ev["status"] = "CONFIRMED"
            ev["sources"] = ["FAA"] + [f"NWS: {alert}" for alert in alerts]
        else:
            ev["status"] = "OFFICIAL"
            ev["sources"] = ["FAA"]

    return events


def diff(
    old: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Diff two event lists into new, updated, and cleared change records."""
    old_by_id = {ev["id"]: ev for ev in old}
    new_by_id = {ev["id"]: ev for ev in new}
    changes: list[dict[str, Any]] = []

    for ev_id, ev in new_by_id.items():
        if ev_id not in old_by_id:
            changes.append({"change": "new", "event": ev})
            continue
        prev = old_by_id[ev_id]
        if prev.get("reason") != ev.get("reason") or prev.get("fields", {}) != ev.get("fields", {}):
            changes.append({"change": "updated", "event": ev, "previous": prev})

    for ev_id, ev in old_by_id.items():
        if ev_id not in new_by_id:
            changes.append({"change": "cleared", "event": ev})

    return changes
