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


def national_summary(airports: list[dict[str, Any]]) -> str:
    """One line for the top of the page. Same rule as lib.js nationalSummary."""
    stops = delays = 0
    best: tuple[int, str] | None = None
    for a in airports:
        if a.get("level") == "stop":
            stops += 1
        elif a.get("level") == "delay":
            delays += 1
        for ev in a.get("events") or []:
            mins = minutes_of(ev.get("avg") if isinstance(ev, dict) else None)
            if mins is not None and (best is None or mins > best[0]):
                best = (mins, str(a.get("short") or a.get("code") or ""))
    if not stops and not delays:
        return "No delays or ground stops at the 30 busiest airports right now"
    parts = []
    if stops:
        parts.append(f"{stops} airport with a ground stop" if stops == 1 else f"{stops} airports with ground stops")
    if delays:
        parts.append(f"{delays} airport with delays" if delays == 1 else f"{delays} airports with delays")
    line = " · ".join(parts)
    if best:
        line += f" · longest: {best[1]}, avg {fmt_minutes(best[0])}"
    return line


def impact_text(ev: dict[str, Any], place: str) -> str:
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
        return f"{place} is closed to flights right now."
    if kind == "ground_delay":
        text = f"Flights bound for {place} are leaving late"
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


def render_events(state: dict[str, Any], by_code: dict[str, Any], updated_utc: str, now: datetime) -> str:
    events = [e for e in (state.get("events") or []) if isinstance(e, dict) and e.get("source") == "FAA" and e.get("kind") in KIND_RANK]
    if not state:
        return ""
    if not events:
        return '<p class="empty-state">No FAA delays or ground stops are listed right now.</p>'
    events.sort(key=lambda e: (-KIND_RANK[e["kind"]], -(minutes_of((e.get("fields") or {}).get("avg")) or 0)))
    age = pt.ago_text(pt.age_minutes(updated_utc, now))
    out = []
    for ev in events:
        code = str(ev.get("airport") or "").upper()
        a = by_code.get(code) or {}
        place = a.get("short") or ev.get("display") or code
        stop = ev.get("kind") in ("ground_stop", "closure")
        cls = "event-card event-card--stop" if stop else "event-card"
        badge = "badge badge--stop" if stop else "badge badge--delay"
        lines = [
            f'<article class="{cls}">',
            f'<div class="event-header"><h3 class="event-title">{_esc(place)} ({_esc(code)})</h3>'
            f'<span class="{badge}">{_esc(KIND_LABEL.get(ev["kind"], "Disruption"))}</span></div>',
            f'<p class="event-impact">{_esc(impact_text(ev, str(place)))}</p>',
        ]
        if ev.get("reason"):
            lines.append(f'<p class="event-reason">Reason: {_esc(ev["reason"])}</p>')
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
    source = f"Source: TSA checkpoint numbers, updated {_fmt_day(str(tsa.get('fetched_utc') or '')[:10])}"
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

    page = template
    if airports:
        page = _slot(page, "summary", _esc(national_summary(airports)))
    else:
        page = re.sub(r"<!--/?pr:summary-->", "", page)
    if state_utc:
        line = f"FAA NAS status, {pt.checked_text(state_utc, HOME_TZ, now)} · updates about every 5 minutes"
        page = _slot(page, "updated", _esc(line))
    else:
        page = re.sub(r"<!--/?pr:updated-->", "", page)
    events_html = render_events(state, by_code, state_utc, now) if state else ""
    page = _slot(page, "events", events_html)
    page = _slot(page, "tsa", render_tsa(tsa))
    stale = pt.stale_text(state_utc, now) if state_utc else ""
    if stale:
        link = (
            ' <a class="stale-link" href="https://nasstatus.faa.gov" target="_blank" rel="noopener noreferrer">nasstatus.faa.gov</a>'
        )
        page = page.replace(
            'role="status" hidden><!--pr:stale--><!--/pr:stale--></p>',
            f'role="status">{_esc(stale)}{link}</p>',
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
