"""Pre-render live text into the home page at build time (AN23 phase 1, item 1).

Reads the repo's clean index.html template and the data files, and writes a copy with the live FAA
status, the TSA national number and a timestamp as plain HTML text. The browser script (app.js) keeps
refreshing the same elements, so a reader and a search crawler see real text with JavaScript off.

The template marks each slot with a comment pair: <!--pr:NAME--> ... <!--/pr:NAME-->. The text between
the markers is the static fallback. This tool replaces it and drops the markers. Every value comes
from the data files. If anything fails, the template is written unchanged (fallback text stays).

Usage: python tools/prerender_home.py --template index.html --data data --out _site/index.html
Stdlib only. No network.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from tools import prerender_text as pt
except ImportError:  # run as a script: tools/ is on the path
    import prerender_text as pt  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
HOME_TZ = "America/New_York"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
KIND_LABEL = {"ground_stop": "Ground stop", "ground_delay": "Ground delay", "closure": "Airport closed", "delay": "Delays"}
KIND_RANK = {"ground_stop": 4, "closure": 4, "ground_delay": 3, "delay": 2}


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def minutes_of(text: Any) -> int | None:
    """'1 hour and 20 minutes' -> 80. Same rule as lib.js minutesOf."""
    s = str(text or "")
    h = re.search(r"(\d+)\s*hours?", s, re.I)
    m = re.search(r"(\d+)\s*minutes?", s, re.I)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def fmt_minutes(minutes: int) -> str:
    h, m = divmod(round(minutes), 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"


def outside_lead(outside: list[dict[str, Any]] | None, stale: bool) -> str:
    """AN34 round 3: an FAA program at an airport outside the list leads the headline. Same rule as lib.js outsideLead."""
    seen: dict[str, dict[str, Any]] = {}
    for e in outside or []:
        c = str((e or {}).get("airport") or "")
        if c and c not in seen:
            seen[c] = e
    if not seen:
        return ""
    if len(seen) > 1:
        return f"{len(seen)} other airports {'had' if stale else 'have'} an FAA program. "
    c, e = next(iter(seen.items()))
    if e.get("kind") == "closure":
        return f"{c} was listed as closed. " if stale else f"{c} is closed. "
    if e.get("kind") == "ground_stop":
        return f"{c} {'had' if stale else 'has'} a ground stop. "
    return f"{c} {'had' if stale else 'has'} delays. "


def national_summary(airports: list[dict[str, Any]], as_of: str = "", outside: list[dict[str, Any]] | None = None) -> str:
    """The home headline: a verdict over every airport we cover. Same rule as lib.js nationalSummary.

    as_of is empty when the data is fresh. When it is set ('as of 1:50 AM EST (12 hours ago)') the line
    is dated and has no live words.
    """
    bad = sum(1 for a in airports if a.get("level") in ("stop", "delay"))
    lead = outside_lead(outside, bool(as_of))
    if not bad and lead:
        n = max(len(airports), 30)
        return f"{lead}The {n} busiest airports " + ("were clear" if as_of else "are clear right now")
    if not bad:
        n = max(len(airports), 30)
        return f"No delays or ground stops were listed at the {n} busiest airports" if as_of else f"No delays or ground stops at the {n} busiest airports right now"
    ok = len(airports) - bad
    if as_of:
        return f"{ok} of the {len(airports)} busiest US airports had no FAA delays at the last check"
    verb = "has" if ok == 1 else "have"
    return f"{ok} of the {len(airports)} busiest US airports {verb} no FAA delays right now"


def _is_closed(a: dict[str, Any]) -> bool:
    return a.get("level") == "stop" and any(isinstance(e, dict) and e.get("kind") == "closure" for e in a.get("events") or [])


def _trouble_rank(a: dict[str, Any]) -> int:
    avg = max([minutes_of(e.get("avg")) or 0 for e in a.get("events") or [] if isinstance(e, dict)] or [0])
    return (30000 if _is_closed(a) else 20000 if a.get("level") == "stop" else 10000) + avg


def trouble_line(airports: list[dict[str, Any]], stale: bool = False) -> str:
    """One plain sentence per airport with an FAA program, worst first, at most 3. Same rule as lib.js troubleLine."""
    bad = sorted((a for a in airports if a.get("level") in ("stop", "delay")), key=_trouble_rank, reverse=True)
    out = []
    for a in bad[:3]:
        name = f"{a.get('short') or a.get('name') or a.get('code')} ({a.get('code')})"
        if _is_closed(a):
            out.append(f"{name} was listed as closed." if stale else f"{name} is closed.")
            continue
        if a.get("level") == "stop":
            out.append(f"{name} had a ground stop." if stale else f"{name} has a ground stop.")
            continue
        evs = [e for e in a.get("events") or [] if isinstance(e, dict)]
        mins = [m for m in (minutes_of(e.get("avg")) for e in evs) if m is not None]
        avg = max(mins) if mins else None
        if any(e.get("kind") == "ground_delay" for e in evs):
            held = f" about {fmt_minutes(avg)}" if avg is not None else ""
            out.append(f"Flights to {name} {'were' if stale else 'are'} held{held}.")
        else:
            size = f" of about {fmt_minutes(avg)}" if avg is not None else ""
            out.append(f"{name} {'had' if stale else 'has'} delays{size}.")
    if len(bad) > 3:
        n = len(bad) - 3
        out.append(f"{n} more airport has an FAA program." if n == 1 else f"{n} more airports have an FAA program.")
    return " ".join(out)


def nbsp_units(text: str) -> str:
    """Keep '2 h 46 min' on one line: no break between a number and its unit."""
    return re.sub(r"\bh (\d)", "h\u00a0\\1", re.sub(r"(\d) (h|min)\b", "\\1\u00a0\\2", text))


def verdict_html(text: str) -> str:
    """The verdict with the count in the status colour: '<em>98 of the 100</em> busiest US airports ...'."""
    esc = _esc(text)
    return re.sub(r"^(\d+ of the \d+)", r'<em class="ok">\1</em>', esc, count=1)


def impact_text(ev: dict[str, Any], place: str, stale: bool = False) -> str:
    fields = ev.get("fields") or {}
    avg = ev.get("avg") or fields.get("avg") or ""
    mx = ev.get("max") or fields.get("max") or ""
    direction = ev.get("direction") or fields.get("direction") or ""
    avg_m, max_m = minutes_of(avg), minutes_of(mx)
    avg_t = fmt_minutes(avg_m) if avg_m is not None else str(avg)
    max_t = fmt_minutes(max_m) if max_m is not None else str(mx)
    kind = ev.get("kind")
    if kind == "ground_stop":
        return f"Flights bound for {place} are held at their departure airports until the stop ends."
    if kind == "closure":
        return f"{place} was listed as closed to flights." if stale else f"{place} is closed to flights right now."
    if kind == "ground_delay":
        text = f"Flights bound for {place} are held at their departure airports"
        if avg_t:
            text += f", about {avg_t} on average"
        if max_t:
            text += f" and up to {max_t}"
        return text + "."
    d = f"{str(direction).lower()} " if direction else ""
    text = f"Expect {d}delays at {place}"
    if avg_t:
        text += f" of about {avg_t}"
    return text + "."


_REASON_PREFIX = {"WX": "weather", "VOLUME": "traffic volume", "RWY/TWY": "runway or taxiway",
                  "EQUIPMENT": "equipment", "STAFFING": "staffing", "OTHER": "other"}


def reason_text(reason: Any) -> str:
    """Turn a raw FAA reason such as 'WX:Wind' into plain words ('weather, wind')."""
    text = str(reason or "").strip()
    m = re.match(r"^([A-Za-z/]+):\s*(.*)$", text)
    if not m or m.group(1).upper() not in _REASON_PREFIX:
        return text
    prefix = _REASON_PREFIX[m.group(1).upper()]
    rest = m.group(2).lower()
    return prefix if (not rest or rest in (prefix, "volume")) else f"{prefix}, {rest}"


def _short_dur(minutes: int) -> str:
    """'2 h 46' for the big number on a row (no 'min' after hours, like a departures board)."""
    h, m = divmod(int(minutes), 60)
    if not h:
        return f"{m} min"
    return f"{h} h {m}" if m else f"{h} h"


_REOPEN_RE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}) at (\d{2}):(\d{2}) UTC")


def event_figure(ev: dict[str, Any], tz: str, now: datetime) -> tuple[str, str]:
    """The big number and its small label for one program row. Same rule as app.js eventFigure."""
    f = ev.get("fields") or {}
    kind = ev.get("kind")
    if kind == "closure":
        m = _REOPEN_RE.search(str(f.get("reopen") or ""))
        if m and m.group(1) in MONTHS:
            from datetime import timezone as _tz
            year = now.year
            month = MONTHS.index(m.group(1)) + 1
            if month < now.month - 6:
                year += 1
            try:
                when = datetime(year, month, int(m.group(2)), int(m.group(3)), int(m.group(4)), tzinfo=_tz.utc)
                # AN34 r2: the big word is the state; the date goes in the small line, in the one zone the home page uses.
                local = when.astimezone(pt.ZoneInfo(HOME_TZ))
                day = f"{MONTHS[local.month - 1]} {local.day}"
                clock = pt.clock_label(when.isoformat().replace("+00:00", "Z"), HOME_TZ)
                if when <= now:
                    return "Closed", f"listed to reopen {day}, {clock}; that time has passed, so it may have reopened"
                return "Closed", f"listed to reopen {day}, {clock}"
            except Exception:  # unknown zone or bad date
                pass
        return "Closed", "no reopening time listed"
    if kind == "ground_stop":
        end = str(ev.get("end_utc") or "")
        clock = pt.clock_label(end, HOME_TZ) if end else ""
        end_dt = pt.parse_utc(end) if end else None
        if clock and end_dt and end_dt <= now:
            return "Stop", f"listed to end {clock}; that time has passed, so it may have lifted"
        if clock:
            return clock, "listed end"
        if f.get("end_time"):
            return str(f["end_time"]).rstrip("."), "listed end"
        return "Stop", "no end time listed"
    avg = minutes_of(f.get("avg") or ev.get("avg"))
    mx = minutes_of(f.get("max") or ev.get("max"))
    if avg is not None:
        small = "average hold" if kind == "ground_delay" else "average delay"
        if mx is not None:
            small += f" · longest {fmt_minutes(mx)}"
        return _short_dur(avg), small
    return "Delays", "no size listed"


def render_events(state: dict[str, Any], by_code: dict[str, Any], updated_utc: str, now: datetime, stale: bool = False) -> str:
    events = [e for e in (state.get("events") or []) if isinstance(e, dict) and e.get("source") == "FAA" and e.get("kind") in KIND_RANK]
    if not state:
        return ""
    if not events:
        if stale:
            return f'<p class="empty-state">No FAA delays or ground stops were listed {_esc(pt.as_of_text(updated_utc, HOME_TZ, now))}.</p>'
        return '<p class="empty-state">No FAA delays or ground stops are listed right now.</p>'
    events.sort(key=lambda e: (-KIND_RANK[e["kind"]], -(minutes_of((e.get("fields") or {}).get("avg")) or 0)))
    age = pt.ago_text(pt.age_minutes(updated_utc, now))
    out = []
    seen: set[str] = set()  # AN32: one row per airport, the worst program first
    for ev in events:
        code = str(ev.get("airport") or "").upper()
        if code in seen:
            continue
        seen.add(code)
        a = by_code.get(code) or {}
        place = a.get("short") or ev.get("display") or code
        full = a.get("name") or ev.get("display") or place
        stop = ev.get("kind") in ("ground_stop", "closure")
        cls = "event-card event-card--stop" if stop else "event-card"
        badge = "badge badge--stop" if stop else "badge badge--delay"
        big, small = event_figure(ev, str(ev.get("tz") or a.get("tz") or ""), now)
        href = f"airports/{code}.html" if re.fullmatch(r"[A-Z]{3}", code) else "airports/index.html"
        lines = [
            f'<article class="{cls}">',
            f'<div class="event-header"><h3 class="event-title"><a class="ev-link" href="{href}"><span class="ev-code">{_esc(code)}</span>'
            f'<span class="ev-place">{_esc(full)}</span></a></h3>'
            f'<span class="{badge}">{_esc(KIND_LABEL.get(ev["kind"], "Disruption"))}</span></div>',
            f'<p class="event-impact">{_esc(nbsp_units(impact_text(ev, str(place), stale)))}</p>',
        ]
        if ev.get("reason") and str(ev["reason"]).strip().lower() != "closed":
            lines.append(f'<p class="event-reason">Reason: {_esc(reason_text(ev["reason"]))}</p>')
        lines.append(f'<p class="event-big"><b>{_esc(nbsp_units(big))}</b><small>{_esc(small)}</small></p>')
        sources = ", ".join(str(x) for x in (ev.get("sources") or [])) or "FAA"
        lines.append(f'<p class="event-meta">Sources: {_esc(sources)} · Checked {_esc(age)}</p>')
        lines.append("</article>")
        out.append("".join(lines))
    return "".join(out)


def _fmt_day(iso: Any) -> str:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}" if m else ""


def render_tsa(tsa: dict[str, Any]) -> str:
    """The first TSA card: people screened on the latest day, with the same day last year."""
    if not tsa or not tsa.get("latest_count"):
        return ""
    latest = int(tsa["latest_count"])
    lines = []
    if tsa.get("ly_count"):
        ly = int(tsa["ly_count"])
        pct = (latest / ly - 1) * 100
        sign = "+" if pct > 0 else ""
        lines.append(
            f"Same weekday last year ({_fmt_day(tsa.get('ly_date'))}): {ly / 1e6:.2f} million ({sign}{pct:.1f}%)"
        )
    fetched = pt.parse_utc(str(tsa.get("fetched_utc") or ""))
    day = _fmt_day(fetched.astimezone(pt.ZoneInfo(HOME_TZ)).date().isoformat()) if fetched else _fmt_day(str(tsa.get("fetched_utc") or "")[:10])
    source = f"Source: TSA checkpoint numbers, updated {day}"
    body = "".join(f'<p class="compare-line">{_esc(x)}</p>' for x in lines)
    return (
        '<article class="compare-card">'
        f'<h3 class="compare-title">People screened, {_esc(_fmt_day(tsa.get("latest_date")))}</h3>'
        f'<p class="compare-big">{latest / 1e6:.2f} million</p>{body}'
        f'<p class="compare-source">{_esc(source)}</p></article>'
    )


def _slot(page: str, name: str, content: str) -> str:
    pattern = re.compile(rf"<!--pr:{name}-->.*?<!--/pr:{name}-->", re.S)
    if not pattern.search(page):
        raise ValueError(f"template has no pre-render slot '{name}'")
    return pattern.sub(lambda _m: content, page, count=1)


def prerender(template: str, data_dir: Path, now: datetime | None = None) -> str:
    """Return the template with the live text filled in. Slots with no data keep their fallback text."""
    now = now or pt.now_utc()
    airports_data = _load(data_dir / "airports.json")
    state = _load(data_dir / "state.json")
    tsa = _load(data_dir / "tsa.json")
    by_code = airports_data.get("airports") or {}
    airports = [a for a in by_code.values() if isinstance(a, dict)]
    state_utc = str(state.get("updated_utc") or "")

    stale = bool(state_utc) and pt.is_stale(pt.age_minutes(state_utc, now))
    as_of = pt.as_of_text(state_utc, HOME_TZ, now) if stale else ""
    page = template
    page = _slot(page, "nowtitle", "Last known status" if stale else "Right now")
    if airports:
        outside = [e for e in (state.get("events") or []) if isinstance(e, dict) and e.get("source") == "FAA"
                   and e.get("kind") in KIND_RANK and str(e.get("airport") or "") not in by_code]
        page = _slot(page, "summary", verdict_html(national_summary(airports, as_of, outside)))
        page = _slot(page, "trouble", _esc(nbsp_units(trouble_line(airports, stale))))
    else:
        page = re.sub(r"<!--/?pr:(summary|trouble)-->", "", page)
    if state_utc:
        line = f"FAA NAS status, {pt.checked_text(state_utc, HOME_TZ, now, last=stale)} · updates about every 5 minutes"
        page = _slot(page, "updated", _esc(line))
    else:
        page = re.sub(r"<!--/?pr:updated-->", "", page)
    events_html = render_events(state, by_code, state_utc, now, stale) if state else ""
    page = _slot(page, "events", events_html)
    page = _slot(page, "tsa", render_tsa(tsa))
    notice = pt.stale_notice_html(state_utc, now) if state_utc else ""
    if notice:
        page = page.replace(
            'role="status" hidden><!--pr:stale--><!--/pr:stale--></p>',
            f'role="status">{notice}</p>',
            1,
        )
    page = re.sub(r"<!--/?pr:stale-->", "", page)
    return page


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write index.html with live status as text (build step).")
    ap.add_argument("--template", default=str(ROOT / "index.html"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", required=True, help="Where to write the pre-rendered page (for example _site/index.html)")
    ap.add_argument("--now", default=None, help="Override the build time (ISO UTC) used for 'N min ago' text")
    args = ap.parse_args(argv)
    template = Path(args.template).read_text(encoding="utf-8")
    now = pt.parse_utc(args.now) if args.now else None
    try:
        page = prerender(template, Path(args.data), now)
        note = "pre-rendered"
    except Exception as exc:  # keep the build going with the fallback text
        page = re.sub(r"<!--/?pr:[a-z]+-->", "", template)
        note = f"fallback text only ({exc})"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"prerender_home: wrote {out} ({note})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
