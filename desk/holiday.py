"""AN12 item 2: the Thanksgiving card, day by day. This year against last year, from tsa.json only.

Last year's days line up by distance from Thanksgiving, so Thursday meets Thursday. A day this year with no
count yet is None (the page draws it as an empty outline, never as zero).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _d(iso: str) -> date:
    return datetime.strptime(iso, "%Y-%m-%d").date()


def assemble(tsa: Optional[dict[str, Any]], today: date) -> Optional[dict[str, Any]]:
    tg = (tsa or {}).get("thanksgiving") or {}
    week = tg.get("last_year_week") or []
    if not week or not tg.get("date_this_year") or not tg.get("last_year_date"):
        return None
    tg_now, tg_ly = _d(tg["date_this_year"]), _d(tg["last_year_date"])
    now_counts: dict[str, int] = {}
    for r in (tsa.get("last7") or []):
        if r.get("count") is not None:
            now_counts[r["date"]] = r["count"]
    for r in (tg.get("this_year_week") or []):
        if r.get("count") is not None:
            now_counts[r["date"]] = r["count"]
    if tsa.get("latest_date") and tsa.get("latest_count") is not None:
        now_counts[tsa["latest_date"]] = tsa["latest_count"]
    rec = tsa.get("record") or {}
    busiest = tg.get("busiest_date")
    days = []
    for r in week:
        ly = _d(r["date"])
        d = tg_now + (ly - tg_ly)
        iso = d.isoformat()
        days.append({
            "date": iso, "dow": DOW[d.weekday()], "day": d.day,
            "count": now_counts.get(iso), "ly_date": r["date"], "ly_count": r["count"],
            "is_busiest": r["date"] == busiest,
            "is_record": rec.get("date") in (r["date"], iso),
            "is_thanksgiving": d == tg_now,
        })
    busy = next((x for x in days if x["is_busiest"]), None)
    latest = None
    if tsa.get("latest_date") and tsa.get("latest_count") is not None:
        lc, lyc = tsa["latest_count"], tsa.get("ly_count")
        latest = {"date": tsa["latest_date"], "count": lc, "ly_date": tsa.get("ly_date"), "ly_count": lyc,
                  "pct": round((lc - lyc) / lyc * 100, 1) if lyc else None}
    return {
        "source": "TSA", "fetched_utc": tsa.get("fetched_utc"),
        "thanksgiving": tg_now.isoformat(), "days_to": (tg_now - today).days,
        "busiest_date": busiest, "busiest_count": busy["ly_count"] if busy else None,
        "busiest_this_year_date": busy["date"] if busy else None,
        "record": {"date": rec.get("date"), "count": rec.get("count")} if rec else None,
        "latest": latest, "days": days,
        "counted_days": sum(1 for x in days if x["count"] is not None),
    }
