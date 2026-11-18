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
sys.path.insert(0, str(ROOT))
from desk.airports import airport_rows, canonical_code  # noqa: E402

HOME_TZ = "America/New_York"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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


def _sched(ev: dict[str, Any] | None, tz: Any, now: datetime | None) -> dict[str, Any] | None:
    """AN35: the scheduled-closure facts for a daily closure event, else None. See prerender_text.closure_schedule."""
    return pt.closure_schedule(ev or {}, str(tz or ""), now or pt.now_utc())


def scheduled_only(a: dict[str, Any], now: datetime | None = None) -> bool:
    """True when every closure at this airport is a scheduled daily one and no ground stop is listed. Same rule as ATD.isScheduledOnly."""
    evs = [e for e in a.get("events") or [] if isinstance(e, dict)]
    cl = [e for e in evs if e.get("kind") == "closure"]
    return bool(cl) and all(_sched(e, a.get("tz"), now) for e in cl) and not any(e.get("kind") == "ground_stop" for e in evs)


def night_reopen(a: dict[str, Any], now: datetime | None = None) -> str:
    """The reopening clock ('6:15 AM') when this airport is inside a scheduled daily closure now, else ''."""
    if not scheduled_only(a, now):
        return ""
    for e in a.get("events") or []:
        sc = _sched(e, a.get("tz"), now)
        if sc and sc["in_window"]:
            return sc["reopen"]
    return ""


def outside_lead(outside: list[dict[str, Any]] | None, stale: bool, now: datetime | None = None) -> str:
    """AN34 round 3: an FAA program at an airport outside the list leads the headline. Same rule as lib.js outsideLead."""
    seen: dict[str, dict[str, Any]] = {}
    for e in outside or []:
        c = canonical_code((e or {}).get("airport"))
        sc = _sched(e, (e or {}).get("tz"), now)
        if sc and not sc["in_window"]:
            continue  # a daily closure outside its hours is not news
        if c and c not in seen:
            seen[c] = e
    if not seen:
        return ""
    if len(seen) > 1:
        return f"{len(seen)} other airports {'had' if stale else 'have'} an FAA program. "
    c, e = next(iter(seen.items()))
    sc1 = _sched(e, e.get("tz"), now) if e.get("kind") == "closure" else None
    if sc1:
        return f"{c} was listed as closed overnight. " if stale else f"{c} is closed overnight, reopens about {sc1['reopen']} local time. "
    if e.get("kind") == "closure":
        return f"{c} was listed as closed. " if stale else f"{c} is closed. "
    if e.get("kind") == "ground_stop":
        return f"{c} {'had' if stale else 'has'} a ground stop. "
    return f"{c} {'had' if stale else 'has'} delays. "


def home_programs(airports: list[dict[str, Any]], events: list[dict[str, Any]] | None,
                  now: datetime | None) -> list[tuple[str, str]]:
    """Match lib.js homePrograms, keeping the most severe program per airport."""
    ranks = {"delay": 1, "ground_delay": 1, "ground_stop": 2, "closure": 3}
    programs: dict[str, str] = {}
    zones = {}

    def add(code: str, kind: str) -> None:
        if code and ranks.get(kind, 0) > ranks.get(programs.get(code), 0):
            programs[code] = kind

    for airport in airports:
        code = canonical_code(airport.get("code"))
        zones[code] = airport.get("tz")
        if scheduled_only(airport, now):
            if night_reopen(airport, now):
                add(code, "closure")
        elif airport.get("level") in ("stop", "delay"):
            add(code, "closure" if _is_closed(airport) else "ground_stop" if airport["level"] == "stop" else "delay")

    for event in events or []:
        if not event:
            continue
        code = canonical_code(event.get("airport"))
        schedule = _sched(event, event.get("tz") or zones.get(code), now)
        if not schedule or schedule["in_window"]:
            add(code, event.get("kind"))
    return sorted(programs.items(), key=lambda item: (-ranks[item[1]], item[0]))


def national_summary(airports: list[dict[str, Any]], as_of: str = "", events: list[dict[str, Any]] | None = None,
                     now: datetime | None = None) -> str:
    """Match lib.js nationalSummary, dating stale data before making any current claims."""
    if as_of:
        return "Last FAA check " + as_of.removeprefix("as of ")
    programs = home_programs(airports, events, now)
    if not programs:
        return "No FAA delays at the 100 busiest airports." if airports else "Airport readings unavailable"
    closures = sum(kind == "closure" for _, kind in programs)
    labels = {"closure": "Closure", "ground_stop": "Ground stop", "delay": "Delays", "ground_delay": "Delays"}
    if len(programs) > 2:
        label = "Closures" if closures == len(programs) else "Delays and closures" if closures else "Delays"
        headline = f"{label} at {len(programs)} airports."
    elif len(programs) == 2 and labels[programs[0][1]] == labels[programs[1][1]]:
        label = {"closure": "Closures", "ground_stop": "Ground stops"}.get(programs[0][1], "Delays")
        headline = f"{label} at {programs[0][0]} and {programs[1][0]}."
    else:
        headline = " ".join(f"{labels[kind]} at {code}." for code, kind in programs)
    covered = {canonical_code(airport.get("code")) for airport in airports}
    if airports and not any(code in covered for code, _ in programs):
        headline += " The 100 busiest are clear."
    return headline


def _is_closed(a: dict[str, Any]) -> bool:
    return a.get("level") == "stop" and any(isinstance(e, dict) and e.get("kind") == "closure" for e in a.get("events") or []) and not scheduled_only(a)


def _trouble_rank(a: dict[str, Any]) -> int:
    avg = max([minutes_of(e.get("avg")) or 0 for e in a.get("events") or [] if isinstance(e, dict)] or [0])
    return (30000 if _is_closed(a) else 20000 if a.get("level") == "stop" else 10000) + avg


# AN34 round 4: the FAA reason in everyday words, only for reasons we know. Same table as lib.js REASON_WORDS.
REASON_WORDS = {"low ceilings": "low clouds", "ceilings": "low clouds", "low visibility": "poor visibility", "fog": "fog",
                "thunderstorms": "thunderstorms", "tstms": "thunderstorms", "wind": "wind", "snow": "snow", "snow/ice": "snow and ice",
                "rain": "rain", "volume": "heavy traffic", "traffic volume": "heavy traffic", "runway construction": "runway work",
                "rwy/twy": "runway work"}


def reason_words(reason: Any) -> str:
    key = re.sub(r"^(wx|weather)\s*[:,]\s*", "", str(reason or "").lower()).strip()
    return REASON_WORDS.get(key, "")


def dateline(local: datetime) -> str:
    """'Sunday night, 10:27 PM': the dated line over the home verdict. Same rule as lib.js dateline."""
    return pt.dateline(local)


def trouble_line(airports: list[dict[str, Any]], stale: bool = False, now: datetime | None = None) -> str:
    """One plain sentence per airport with an FAA program, worst first, at most 3. Same rule as lib.js troubleLine."""
    bad = sorted((a for a in airports if a.get("level") in ("stop", "delay") and not scheduled_only(a, now)), key=_trouble_rank, reverse=True)
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
        why = reason_words(a.get("reason"))
        if any(e.get("kind") == "ground_delay" for e in evs):
            held = f" about {fmt_minutes(avg)}" if avg is not None else ""
            out.append(f"Flights to {name} {'were' if stale else 'are'} held{held}" + (f" for {why}" if why else "") + ".")
        else:
            size = f" of about {fmt_minutes(avg)}" if avg is not None else ""
            out.append(f"{name} {'had' if stale else 'has'} delays{size}" + (f", {why}" if why else "") + ".")
    # AN35: an airport inside its daily closed hours gets one calm sentence, not a count. Same rule as lib.js troubleLine.
    for a in ([] if stale else [x for x in airports if night_reopen(x, now)])[:2]:
        out.append(f"{a.get('short') or a.get('name') or a.get('code')} ({a.get('code')}) is closed overnight, reopens about {night_reopen(a, now)} local time.")
    if len(bad) > 3:
        n = len(bad) - 3
        out.append(f"{n} more airports had an FAA program." if stale else (f"{n} more airport has an FAA program." if n == 1 else f"{n} more airports have an FAA program."))
    return " ".join(out)


def nbsp_units(text: str) -> str:
    """Keep '2 h 46 min' on one line: no break between a number and its unit."""
    return re.sub(r"\bh (\d)", "h\u00a0\\1", re.sub(r"(\d) (h|min)\b", "\\1\u00a0\\2", text))


def impact_text(ev: dict[str, Any], place: str, stale: bool = False, tz: Any = "", now: datetime | None = None) -> str:
    fields = ev.get("fields") or {}
    avg = ev.get("avg") or fields.get("avg") or ""
    mx = ev.get("max") or fields.get("max") or ""
    direction = ev.get("direction") or fields.get("direction") or ""
    avg_m, max_m = minutes_of(avg), minutes_of(mx)
    avg_t = fmt_minutes(avg_m) if avg_m is not None else str(avg)
    max_t = fmt_minutes(max_m) if max_m is not None else str(mx)
    kind = ev.get("kind")
    sc = _sched(ev, tz, now) if kind == "closure" else None
    if sc:
        if stale:
            return f"{place} was listed with a daily closure."
        if sc["in_window"]:
            return f"{place} is closed overnight. The FAA lists a daily closure; it reopens about {sc['reopen']} local time."
        return f"{place} is open now. The FAA lists a daily closure; it closes again about {sc['close']} local time."
    if kind == "ground_stop":
        return f"Flights bound for {place} were held at their departure airports." if stale else f"Flights bound for {place} are held at their departure airports until the stop ends."
    if kind == "closure":
        return f"{place} was listed as closed to flights." if stale else f"{place} is closed to flights right now."
    if kind == "ground_delay":
        text = f"Flights bound for {place} {'were' if stale else 'are'} held at their departure airports"
        if avg_t:
            text += f", about {avg_t} on average"
        if max_t:
            text += f" and up to {max_t}"
        return text + "."
    d = f"{str(direction).lower()} " if direction else ""
    text = f"{'FAA listed' if stale else 'Expect'} {d}delays at {place}"
    if avg_t:
        text += f" of about {avg_t}"
    return text + "."


reason_text = pt.reason_text


def closure_listing(ev: dict[str, Any], now: datetime) -> str:
    end = pt.listed_utc(ev.get("reopen") or (ev.get("fields") or {}).get("reopen"), now)
    if not end:
        return ""
    local = end.astimezone(pt.ZoneInfo(HOME_TZ))
    day = f"{MONTHS[local.month - 1]} {local.day}"
    if (end - now).total_seconds() > 86400:
        return f"FAA listing runs to {day}. Long listings often cover nightly closures."
    passed = " (time passed)" if end <= now else ""
    return f"Listed reopening {day}, {pt.clock_label(end.isoformat(), HOME_TZ)}{passed}"


def render_events(state: dict[str, Any], by_code: dict[str, Any], updated_utc: str, now: datetime, stale: bool = False, at: datetime | None = None) -> str:
    at = at or now  # a scheduled closure is judged at the data's own time when the data is stale
    events = [e for e in (state.get("events") or []) if isinstance(e, dict) and e.get("source") == "FAA" and e.get("kind") in KIND_RANK]
    # AN35: a daily closure outside its hours is not a row.
    events = [e for e in events if not ((sc := _sched(e, e.get("tz") or
              by_code.get(canonical_code(e.get("airport")), {}).get("tz"), at)) and not sc["in_window"])]
    if not state:
        return ""
    if not events:
        if stale:
            return '<p class="empty-state">No FAA programs were listed at the last check.</p>'
        return '<p class="empty-state">No FAA delays or ground stops are listed right now.</p>'
    events.sort(key=lambda e: (-KIND_RANK[e["kind"]], -(minutes_of((e.get("fields") or {}).get("avg")) or 0)))
    out = []
    seen: set[str] = set()  # AN32: one row per airport, the worst program first
    for ev in events:
        code = canonical_code(ev.get("airport"))
        if code in seen:
            continue
        seen.add(code)
        a = by_code.get(code) or {}
        name = a.get("name") or ev.get("display") or a.get("short") or code
        kind = ev["kind"]
        fields = ev.get("fields") or {}
        night = _sched(ev, ev.get("tz") or a.get("tz"), at) if kind == "closure" else None
        stop = kind in ("ground_stop", "closure") and not night
        cls = "event-card event-card--night" if night else "event-card event-card--stop" if stop else "event-card"
        badge = "badge badge--night" if night else "badge badge--stop" if stop else "badge badge--delay"
        status = "Ground stop" if kind == "ground_stop" else "Delays"
        detail = ""
        if kind == "closure":
            status = "Closure listed" if stale else "Closed overnight" if night else "Closed"
        elif kind == "ground_stop":
            end = pt.parse_utc(ev.get("end_utc"))
            if end:
                detail = "listed end " + pt.clock_label(end.isoformat(), HOME_TZ)
        else:
            avg = minutes_of(fields.get("avg") or ev.get("avg"))
            maximum = minutes_of(fields.get("max") or ev.get("max"))
            if avg is not None:
                detail = "avg " + fmt_minutes(avg)
            elif maximum is not None:
                detail = "max " + fmt_minutes(maximum)
        if stale and kind != "closure":
            status += " listed"
        if detail:
            status += " · " + detail

        why = reason_text(ev.get("reason"))
        if why.lower() == "closed":
            why = ""
        if not why and kind == "closure":
            why = f"Listed reopening about {night['reopen']} local time" if night else closure_listing(ev, now)
        reason_title = f' title="{_esc(why)}"' if why else ""
        # Only airports in the data file (the 100 busiest) have a page; other FAA codes (OPF) link to the index, never a 404.
        href = f"/airports/{code}" if re.fullmatch(r"[A-Z]{3}", code) and code in by_code else "/airports/"
        slug, label = {
            "ground_stop": ("ground-stop.html", "What is a ground stop?"),
            "ground_delay": ("ground-delay.html", "What is a ground delay?"),
        }.get(kind, ("", "Disruption guides"))
        out.append(
            f'<article class="{cls}"><h3 class="event-title"><a class="ev-link" href="{href}">'
            f'<span class="ev-code">{_esc(code)}</span><span class="ev-place" title="{_esc(name)}">{_esc(name)}</span></a></h3>'
            f'<span class="{badge}">{_esc(status)}</span>'
            f'<p class="event-reason"{reason_title}>{_esc(why)}</p>'
            f'<a class="event-help" href="/help/{slug}">{label}</a></article>'
        )
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
    by_code = airport_rows(airports_data.get("airports"))
    airports = [dict(a, code=code) for code, a in by_code.items() if isinstance(a, dict)]
    state_utc = str(state.get("faa_updated_utc") or state.get("updated_utc") or "")

    stale = pt.is_stale(pt.age_minutes(state_utc, now)) or "FAA" in state.get("stale_feeds", []) or "FAA" in airports_data.get("stale_feeds", [])
    at = (pt.parse_utc(state_utc) or now) if stale else now  # AN35: a scheduled closure is judged at the data's own time when it is stale
    as_of = pt.short_check_text(state_utc, HOME_TZ, now) if stale else ""
    page = template.replace("Delays and closures</h2>", ("Delays and closures (last check)" if stale else "Delays and closures now") + "</h2>")
    page = page.replace('id="summary"', 'id="summary" data-stale="' + str(stale).lower() + '"')
    checked = pt.parse_utc(state_utc) if state_utc else None
    title = "Latest FAA check"
    if checked:
        local = checked.astimezone(pt.ZoneInfo(HOME_TZ))
        title = dateline(local) + " " + local.strftime("%Z")
    for slot in ("boarddate", "mapdate"):
        if f"<!--pr:{slot}-->" in page:
            page = _slot(page, slot, "")
    page = _slot(page, "nowtitle", "Last known status" if stale else title)
    events = [e for e in (state.get("events") or []) if isinstance(e, dict) and e.get("source") == "FAA"
              and e.get("kind") in KIND_RANK]
    programs = home_programs(airports, events, at)
    page = _slot(page, "summary", _esc(national_summary(airports, as_of, events, at)))
    lede = trouble_line(airports, stale, at)
    if stale:
        covered = {canonical_code(airport.get("code")) for airport in airports}
        outside = [e for e in events if canonical_code(e.get("airport")) not in covered]
        lede = outside_lead(outside, True, at) + lede
        if not lede and programs:
            lede = "FAA programs were listed at " + ", ".join(code for code, _ in programs) + "."
        if not lede and airports:
            lede = "No FAA programs were listed at the 100 busiest airports."
        lede = (lede.strip() + " Current conditions unknown.").strip()
    elif len(programs) > 2:
        lede = ", ".join(code for code, _ in programs) + "."
    page = _slot(page, "trouble", _esc(nbsp_units(lede)))
    note = "No FAA program does not mean your flight is on time." if not stale and airports and not programs else ""
    page = _slot(page, "verdictnote", _esc(note))
    if state_utc:
        line = "FAA NAS status. See last check above." if stale else pt.faa_age_plain(state_utc, HOME_TZ, now, stale)
        page = _slot(page, "updated", _esc(line))
    else:
        page = re.sub(r"<!--/?pr:updated-->", "", page)
    events_html = render_events(state, by_code, state_utc, now, stale, at) if state else ""
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
