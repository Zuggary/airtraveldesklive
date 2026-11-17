"""Build static airport pages (airports/<CODE>.html and airports/index.html) and update sitemap.xml.

Stdlib only; reads data/*.json with no network requests.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

try:
    from tools import prerender_text as pt
except ImportError:  # run as a script: tools/ is on the path
    import prerender_text as pt  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk import airports as desk_airports  # noqa: E402
from tools import an43_context  # noqa: E402

SITE_URL = "https://www.airtraveldesklive.com"
DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive"
CONTACT_EMAIL = "hello@airtraveldesklive.com"
BTS_DEFINITION_SHORT = "BTS counts a flight on time if it arrives less than 15 minutes late"

# AN17: airport type for the hero illustration. Every other airport is a hub.
# AN23: the other 70 airports are typed by hand from where the field sits. Coastal: on or next to open water or a bay.
# Mountain: in or beside mountains or on a high plateau. Desert: in a desert basin. Inland fields stay "hub".
AIRPORT_TYPE = {
    **{c: "coastal" for c in "SFO LAX SAN SEA MIA FLL TPA BOS JFK LGA EWR "
       "HNL OGG KOA LIH ANC OAK SNA LGB PBI SRQ RSW CHS SAV MYR PNS PVD ORF MSY".split()},
    **{c: "mountain" for c in "DEN SLC BOI COS RNO ABQ".split()},
    **{c: "desert" for c in "PHX LAS TUS ELP PSP".split()},
}


def airport_type(code: str) -> str:
    return AIRPORT_TYPE.get(code, "hub")


def _stable_index(code: str, n: int) -> int:
    """Stable choice from an airport code (no hash(), which changes between runs)."""
    return sum((i + 1) * ord(ch) for i, ch in enumerate(code)) % n


SITEMAP_BEGIN = "<!-- airports:begin -->"
SITEMAP_END = "<!-- airports:end -->"


def _load_json(path: Path) -> dict[str, Any]:
    """Read a JSON file as a dict, returning {} if missing."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _safe_http_url(raw: Any) -> str:
    """Return raw URL string only if it is an http(s) URL with a host and no whitespace."""
    url = str(raw or "").strip()
    if not url or any(ch.isspace() for ch in url):
        return ""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ("http", "https") and parts.netloc:
        return url
    return ""


ZONE_NAMES = {
    "America/New_York": "Eastern Time",
    "America/Detroit": "Eastern Time",
    "America/Chicago": "Central Time",
    "America/Denver": "Mountain Time",
    "America/Phoenix": "Arizona Time (no daylight saving)",
    "America/Los_Angeles": "Pacific Time",
    "America/Anchorage": "Alaska Time",
    "Pacific/Honolulu": "Hawaii Time",
}


def _zone_name(tz: str) -> str:
    """Plain zone name for an IANA zone id; falls back to the city part of the id."""
    if tz in ZONE_NAMES:
        return ZONE_NAMES[tz]
    return tz.rsplit("/", 1)[-1].replace("_", " ")


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _json_ld_script(obj: dict[str, Any]) -> str:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("</", "<\\/")
    return f'  <script type="application/ld+json">{raw}</script>'


NOTE_BLOCKED_LINKS = "Some airport sites block automatic checks, so we could not verify every link by script."
LINKS_ALL_CHECKED = "official airport pages, links checked {date}."
LINKS_NOT_ALL_CHECKED = "official airport pages. Some of these sites block automatic checks, so we could not verify every link by script."


# AN35: each airline's own flight-status page, for the "Check my flight" box. Keys are the airline ids in data/dot-commitments.json.
# 'codes' are the IATA and ICAO flight-number prefixes. The page only sends the visitor there; we fetch and hold no flight data.
# Checked 2026-11-16 (GET, status only): alaska, american, delta, southwest, hawaiian open; allegiant showed a maintenance
# page that day; spirit and united refuse scripts (open in a browser); frontier lists no status page address that opens, so it
# goes to its home page, where the Flight Status tab is.
# Status addresses confirmed to open on 2026-11-16: Alaska, American, Delta, Hawaiian, JetBlue, Southwest. Allegiant, Spirit, United and Frontier could not be confirmed
# from here (maintenance page, refused scripts, no address), so they open the airline home page, where the status lookup sits. Recheck before changing.
FLIGHT_STATUS = {
    "alaska": ("Alaska Airlines", ("AS", "ASA"), "https://www.alaskaair.com/flightstatus"),
    "allegiant": ("Allegiant", ("G4", "AAY"), "https://www.allegiantair.com/"),
    "american": ("American Airlines", ("AA", "AAL"), "https://www.aa.com/travelInformation/flights/status"),
    "delta": ("Delta Air Lines", ("DL", "DAL"), "https://www.delta.com/us/en/flight-status"),
    "frontier": ("Frontier Airlines", ("F9", "FFT"), "https://www.flyfrontier.com/"),
    "hawaiian": ("Hawaiian Airlines", ("HA", "HAL"), "https://www.hawaiianairlines.com/flight-status"),
    "jetblue": ("JetBlue", ("B6", "JBU"), "https://www.jetblue.com/flight-tracker-and-status/"),
    "southwest": ("Southwest Airlines", ("WN", "SWA"), "https://www.southwest.com/air/flight-status/"),
    "spirit": ("Spirit Airlines", ("NK", "NKS"), "https://www.spirit.com/"),
    "united": ("United Airlines", ("UA", "UAL"), "https://www.united.com/"),
}


SITE_NOTE = " (airline's own site)"
HOME_ONLY = ("allegiant", "frontier", "spirit", "united")      # no status address confirmed: these rows open the airline's own site


def _flight_check(code: str) -> list[str]:
    """AN35: the 'Check my flight' box. The visitor types a flight number (DL 123); a small script on the page picks the airline
    by its code and opens that airline's own status page in a new tab. Nothing is fetched or stored, and the flight number is
    never put in a URL of ours. Without JavaScript the airline list below the box still works."""
    table = {c: key for key, (_n, codes, _u) in FLIGHT_STATUS.items() for c in codes}
    data = {key: {"name": n, "url": u} for key, (n, _c, u) in FLIGHT_STATUS.items()}
    items = "".join(
        f'<li><a class="tap" href="{_esc(u)}" target="_blank" rel="noopener noreferrer">{_esc(n)}{SITE_NOTE if _k in HOME_ONLY else ""}</a></li>'
        for _k, (n, _c, u) in FLIGHT_STATUS.items()
    )
    return [
        '            <form id="flight-form" class="flight-form" action="#" autocomplete="off" novalidate>',
        '              <label for="flight-no">Flight number, like DL 123</label>',
        '              <span class="flight-row"><input id="flight-no" type="text" inputmode="text" maxlength="10" autocapitalize="characters" spellcheck="false" placeholder="DL 123">',
        '              <button type="submit" class="btn btn-accent">Open airline page</button></span>',
        '              <p id="flight-msg" class="small" role="status" hidden></p>',
        '            </form>',
        '            <p class="small flight-honest">Opens the airline\'s own status page or home page. We do not track individual flights.</p>',
        f'            <ul class="airline-links" id="flight-airlines" aria-label="Airline flight-status pages">{items}</ul>',
        '            <script>',
        '            (function () {',
        f'              var CODES = {json.dumps(table)}, AIRLINES = {json.dumps(data)};',
        '              var f = document.getElementById("flight-form"), msg = document.getElementById("flight-msg"), list = document.getElementById("flight-airlines");',
        '              if (!f) { return; }',
        '              if (list) { list.hidden = true; }',
        '              f.addEventListener("submit", function (e) {',
        '                e.preventDefault();',
        '                var m = /^\\s*([A-Za-z][A-Za-z0-9]|[A-Za-z]{3})\\s*-?\\s*(\\d{1,4})\\s*[A-Za-z]?\\s*$/.exec(document.getElementById("flight-no").value);',
        '                var key = m && CODES[m[1].toUpperCase()];',
        '                if (key) { msg.hidden = true; window.open(AIRLINES[key].url, "_blank", "noopener,noreferrer"); return; }',
        '                msg.textContent = m ? "We do not know the airline code " + m[1].toUpperCase() + ". Pick your airline below." : "Type the airline code and number, like DL 123, or pick your airline below.";',
        '                msg.hidden = false;',
        '                if (list) { list.hidden = false; }',
        '              });',
        '            })();',
        '            </script>',
    ]


def _src_link(text: str) -> str:
    return f'<a class="tap" href="/sources">{_esc(text)}</a>'


ICONS = {
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z"/>',
    "map": '<path d="M3 6.5l6-2.5 6 2.5 6-2.5v13.5l-6 2.5-6-2.5-6 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
    "bag": '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M9 8V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V8"/>',
    "car": '<path d="M5 16.5V12l2-5h10l2 5v4.5M3.5 12h17M5 16.5h14"/><circle cx="7.5" cy="17.5" r="1.7"/><circle cx="16.5" cy="17.5" r="1.7"/>',
    "bed": '<path d="M3 18V7M3 14h18v4M21 14v-2.5A2.5 2.5 0 0 0 18.5 9H11v5"/><circle cx="7" cy="11" r="1.8"/>',
    "shield": '<path d="M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "plane": '<path d="M10.5 3.5c.8 0 1.5.7 1.5 1.5v4.8l7 4v2l-7-2v3.7l2 1.5V21l-3.5-1-3.5 1v-2l2-1.5v-3.7l-7 2v-2l7-4V5c0-.8.7-1.5 1.5-1.5z"/>',
}


def icon(name: str, cls: str = "") -> str:
    """A drawn stroke icon (24 grid). Inline SVG with no namespace URL, so it adds no outside link."""
    classes = f"ic {cls}".strip()
    return f'<svg class="{classes}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{ICONS.get(name, "")}</svg>'


def _link_icon(label: str) -> str:
    low = label.lower()
    if "map" in low:
        return "map"
    if "park" in low or "transport" in low or "car" in low:
        return "car"
    if "security" in low or "tsa" in low:
        return "shield"
    if "food" in low or "shop" in low or "dining" in low:
        return "bag"
    if "lost" in low or "service" in low or "faq" in low or "help" in low:
        return "info"
    if "flight" in low:
        return "plane"
    return "globe"


def _k(label: str) -> str:
    """A tile label. It ends with a colon so the tile reads as one sentence with CSS off."""
    return f'<span class="fact-k">{_esc(label)}:</span> '


CAT_WORDS = {"MVFR": "reduced ceiling or visibility", "IFR": "low ceiling or poor visibility", "LIFR": "very low ceiling or visibility"}


def outlook_text(wx: dict[str, Any]) -> str:
    """AN35: the next-3-hours words from the TAF fields we hold (ceiling, visibility, wind, rain words come from the feed's own text).
    'clear likely after 5 am Eastern'; a non-VFR category adds its plain meaning; a storm flag adds 'Storms possible.'
    Same rule as outlookText in the page script."""
    text = str(wx.get("next3h_text") or "").strip()
    if not text:
        return ""
    out = text
    cat = str(wx.get("next3h_cat") or "").upper()
    if cat in CAT_WORDS and not re.search(r"cloud|ceiling|visib|fog|mist|haze", text, re.I):
        out += f" ({cat}: {CAT_WORDS[cat]})"
    if wx.get("next3h_storms") and not re.search(r"storm", text, re.I):
        out += ". Storms possible"
    return out


def _tsa_wait(entry: dict[str, Any] | None, now: Any) -> dict[str, Any] | None:
    """AN35: the checkpoint wait from data/security-waits.json, only when the entry holds a number (wait_minutes) with a time
    (updated_utc, at most 60 minutes old) and says whose number it is (source). Today the file holds links only, so this returns None
    and the page shows nothing for it."""
    e = entry if isinstance(entry, dict) else {}
    try:
        minutes = int(e.get("wait_minutes"))
    except (TypeError, ValueError):
        return None
    upd = e.get("updated_utc")
    age = pt.age_minutes(upd, now)
    source = str(e.get("source") or "").strip()
    if minutes < 0 or age is None or age > 60 or not source:
        return None
    return {"minutes": minutes, "utc": str(upd), "age": age, "source": source, "url": _safe_http_url(e.get("url"))}


def _render_glance(code: str, tsa: dict[str, Any] | None, live: dict[str, Any], now: Any) -> list[str]:
    """AN35: two lines in the hero, above the fold: the TSA checkpoint wait and the next 3 hours. Each shows its source and age.
    A line with no data is left out (the next-3-hours element stays, hidden, so the live refresh can fill it)."""
    out = ['        <div class="ap-glance" id="ap-glance">']
    if tsa:
        src = (f'<a class="tap" href="{_esc(tsa["url"])}" target="_blank" rel="noopener noreferrer">{_esc(tsa["source"])}</a>' if tsa["url"] else _esc(tsa["source"]))
        out.append(
            f'          <p id="ap-tsa" class="gl gl--tsa" data-utc="{_esc(tsa["utc"])}"><span class="gl-k">TSA checkpoint wait:</span> '
            f'<span class="gl-v">about {tsa["minutes"]} min</span> <span class="gl-src">{src}, <span class="gl-age">{_esc(pt.old_text(tsa["age"]))}</span></span></p>'
        )
    nxt = live.get("next3")
    if nxt:
        out.append(f'          <p id="ap-next3" class="gl gl--next">{nxt}</p>')
    else:
        out.append('          <p id="ap-next3" class="gl gl--next" hidden></p>')
    out.append("        </div>")
    return out


def _render_live(
    code: str,
    tz: str,
    entry: dict[str, Any] | None,
    updated_utc: str,
    now: Any,
) -> dict[str, Any]:
    """Pre-rendered live text for one airport page, from data/airports.json values only.

    AN34: the box is a row of tiles (FAA, weather now, next 3 hours), each with its source and age.
    Returns HTML pieces that match what the browser script writes, so the refresh replaces them in place.
    With no data for the airport, returns the plain fallback text.
    """
    if not entry:
        return {
            "has": False,
            "stale": False,
            "stale_notice": "",
            "as_of": "",
            "chip_class": "badge status-chip",
            "chip": "Status loads here",
            "wx_chip": "",
            "checked": f"FAA NAS status loads here. {pt.FALLBACK_STATUS}.",
            "box": [f'          <div class="fact fact--faa"><p class="updated-text">{_esc(pt.FALLBACK_STATUS)}</p></div>'],
            "word": "",
            "wx": "",
            "clock": "",
            "level": "none",
        }
    age = pt.age_minutes(updated_utc, now)
    stale = pt.is_stale(age) or bool(entry.get("_feed_stale"))
    unknown = entry.get("level") not in ("clear", "delay", "stop", "closed")
    at = (pt.parse_utc(updated_utc) or now) if stale else now  # a scheduled closure is judged at the data's own time when stale
    lvl = pt.effective_level(entry, at)
    word = pt.status_word(entry, at)
    wx = entry.get("wx") if isinstance(entry.get("wx"), dict) else {}
    clock = pt.clock_label(updated_utc, tz)
    checked_pre, checked_post = pt.faa_age_parts(updated_utc, tz, now, stale)
    checked = checked_pre + "FAA NAS status" + checked_post
    chip_wx = ""
    if wx.get("now_text") and not stale:
        chip_wx = f"Weather: {wx['now_text']}"
        wind = pt.wind_text(wx, gusts=False)
        if wind:
            chip_wx += f", wind {wind}"
    badge_cls = "badge badge--stale" if stale else pt.BADGE_CLASS[lvl]
    badge_text = pt.stale_chip_text(entry, updated_utc, tz) if stale else word
    if unknown:
        word = badge_text = "Last known status: unavailable"
        badge_cls = "badge badge--stale"
    # AN34 round 3: the hero H1 and its checked line are the one status block; the tiles hold weather and daylight.
    box: list[str] = []
    if wx.get("now_text"):
        wind = pt.wind_text(wx)
        obs = pt.clock_label(wx.get("obs_utc"), tz)
        obs_age = pt.age_minutes(wx.get("obs_utc") or updated_utc, now)
        value = pt.weather_summary(wx)
        if stale or pt.is_stale(obs_age):
            label = "Last weather report"
            seen = f"observed {obs}, " if obs else ""
            after = f", {seen}{pt.ago_text(obs_age)}"
        else:
            label = "Weather now"
            after = f", observed {obs}, updated {pt.ago_text(obs_age)}" if obs else f", updated {pt.ago_text(obs_age)}"
        box.append(
            f'          <div class="fact fact--wx"><p>{_k(label)}<span class="fact-v">{_esc(value)}</span> '
            f'<span class="fact-src">{_src_link("aviationweather.gov METAR")}{_esc(after)}</span></p></div>'
        )
    next3 = ""
    if wx.get("next3h_text") and outlook_text(wx):
        taf_iso = wx.get("taf_issue_utc") or updated_utc
        label = ""
        if not stale:
            label = "Next 3 hours"
        elif not pt.forecast_expired(wx["next3h_text"], taf_iso, tz, now):
            label = f"Forecast issued {pt.clock_label(taf_iso, tz)}"
        if label:
            issued = pt.clock_label(taf_iso, tz)
            taf_age = pt.age_minutes(taf_iso, now)
            when = f", issued {issued} ({pt.old_text(taf_age)})" if issued and not stale else ""
            next3 = (f'<span class="gl-k">{_esc(label)}:</span> <span class="gl-v">{_esc(outlook_text(wx))}</span> '
                     f'<span class="gl-src">{_src_link("aviationweather.gov TAF")}{_esc(when)}</span>')
    alerts = [str(a) for a in (entry.get("alerts") or [])]
    box.append(
        '          <div class="fact-foot">'
        f'<p>{_esc("Alerts: " + ", ".join(alerts) if alerts else "Alerts: none listed.")}</p>'
        f'<p class="credit">Sources: {_src_link("FAA NAS status, aviationweather.gov METAR and TAF")}.</p></div>'
    )
    return {
        "has": True,
        "stale": stale,
        "updated_utc": updated_utc,
        "next3": next3,
        "checked_pre": checked_pre,
        "checked_post": checked_post,
        "chip_class": f"{badge_cls} status-chip",
        "chip": badge_text,
        "wx_chip": chip_wx,
        "checked": checked,
        "stale_notice": pt.stale_text(updated_utc, now),
        "stale_html": pt.stale_notice_html(updated_utc, now),
        "box": box,
        "word": word,
        "wx": pt.weather_summary(wx),
        "clock": clock,
        "as_of": pt.as_of_text(updated_utc, tz, now),
        "level": "stale" if stale else lvl,
    }


def _avg_minutes(entry: dict[str, Any] | None) -> tuple[int | None, int | None, str]:
    """Largest FAA average and longest delay in minutes, and the program kind that carries them."""
    best: tuple[int | None, int | None, str] = (None, None, "")
    for ev in (entry or {}).get("events") or []:
        if not isinstance(ev, dict):
            continue
        avg = _minutes(ev.get("avg"))
        if avg is not None and (best[0] is None or avg > best[0]):
            best = (avg, _minutes(ev.get("max")), str(ev.get("kind") or ""))
    return best


def _minutes(text: Any) -> int | None:
    s = str(text or "")
    h = re.search(r"(\d+)\s*hours?", s, re.I)
    m = re.search(r"(\d+)\s*minutes?", s, re.I)
    if not h and not m:
        return None
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)


def _dur(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    out = f"{h} h {m} min" if h and m else (f"{h} h" if h else f"{m} min")
    return out


def _verdict(entry: dict[str, Any] | None, name: str, short: str, live: dict[str, Any], now: Any, tz: str) -> str:
    """The H1: the answer in plain words. Same rule as the browser script's verdict()."""
    if not entry or not live.get("has"):
        return f"{_esc(name)}: delays, weather and traveler help"
    lvl = pt.effective_level(entry, now)
    place = _esc(short)
    if entry.get("level") not in ("clear", "delay", "stop", "closed"):
        return "Last known status: FAA status unavailable."
    if live.get("stale"):
        word = pt.status_word(entry, pt.parse_utc(live.get("updated_utc")) or now)
        return f"{_esc(word)} at {place}, {_esc(live['as_of'])}."
    if lvl == "night":
        return f"{place} is <em>closed overnight</em>."
    if lvl == "closed":
        return f"{place} is <em>closed</em> to flights."
    if lvl == "stop":
        return f"<em>Ground stop:</em> flights to {place} are held where they are."
    if lvl == "delay":
        return f"The FAA lists <em>delays</em> at {place}."
    return f"No FAA delays at {place} <em>right now</em>."


def _night_schedule(entry: dict[str, Any] | None, now: Any) -> dict[str, Any] | None:
    """The scheduled-closure facts (reopen and close clock, in the airport's zone) for the first daily closure in this entry."""
    tz = str((entry or {}).get("tz") or "")
    for e in (entry or {}).get("events") or []:
        sched = pt.closure_schedule(e, tz, now)
        if sched:
            return sched
    return None


def _status_meaning(entry: dict[str, Any] | None, lvl: str, stale: bool) -> str:
    """Airport-wide FAA program meaning, without individual-flight claims."""
    if stale or not entry or entry.get("level") not in ("clear", "delay", "stop", "closed"):
        return "Last known status: current arrivals and departures are unconfirmed; this is airport-wide, not the status of any individual flight."
    kinds = {e.get("kind") for e in entry.get("events", []) if e}
    directions = {str(e.get("direction", "")).lower() for e in entry.get("events", []) if e and e.get("kind") == "delay"}
    departure = "departure_delay" in kinds or "departure" in directions
    if lvl in ("closed", "night"):
        meaning = "the FAA lists a closure affecting arrivals and departures"
    elif lvl == "stop":
        meaning = "departures to this airport are held at their origin airports, rather than departures from here"
    elif "ground_delay" in kinds:
        meaning = "arrivals are held at their origin airports, rather than departures from here"
        if departure:
            meaning += "; departure delays are also listed here"
    elif departure and "arrival" in directions:
        meaning = "the FAA lists both arrival and departure delays"
    elif departure:
        meaning = "departures from this airport are delayed; this does not describe arrivals"
    elif "arrival" in directions:
        meaning = "arrivals at this airport are delayed; this does not describe departures"
    elif lvl == "clear":
        meaning = "no FAA arrival or departure programs are listed"
    else:
        meaning = "the FAA lists delays without a confirmed arrival or departure direction"
    return "Airport-wide status: " + meaning + "; this is not the status of any individual flight."


def _lead(entry: dict[str, Any] | None, short: str, code: str, live: dict[str, Any], now: Any = None) -> list[str]:
    lvl = pt.effective_level(entry, now or pt.now_utc()) if entry else "unknown"
    return [f'        <p id="ap-meaning" class="ap-lead">{_esc(_status_meaning(entry, lvl, bool(live.get("stale") or not live.get("has"))))}</p>']


_PLAIN_REASON = {"low ceilings": "low clouds", "ceilings": "low clouds", "low visibility": "poor visibility",
                 "volume": "more flights than the runways can take", "traffic volume": "more flights than the runways can take",
                 "weather, thunderstorms": "thunderstorms", "tstms": "thunderstorms", "weather, wind": "wind",
                 "runway or taxiway": "runway or taxiway work"}


def _plain_reason(reason: str) -> str:
    """FAA words a traveler may not know, in everyday words ('low ceilings' becomes 'low clouds')."""
    return "; ".join(_PLAIN_REASON.get(part.strip().lower(), part.strip()) for part in str(reason or "").split(";") if part.strip())


def _help_card(code: str, lvl: str) -> list[str]:
    """The stuck help, scaled to the state: a quiet card when clear, three steps when delayed or closed.
    AN34 r2: the steps are always in the page (hidden when calm), so the live refresh can scale the card up or down.
    Wording follows kits/desk/CHARTER.md: 'may be owed', never 'must cover'; the airline decides each claim."""
    hot = lvl in ("delay", "stop", "closed")
    tone = "red" if lvl in ("stop", "closed") else "amber"
    cls = f"airport-section help-card help-card--hot help-card--{tone}" if hot else "airport-section help-card"
    head = f"Flying through {_esc(code)} today?" if hot else "If your flight is hit"
    return [
        f'      <section id="help-card" class="{cls}" aria-labelledby="stuck-heading" data-code="{_esc(code)}">',
        f'        <h2 id="stuck-heading">{head}</h2>',
        f'        <div class="help-hot"{"" if hot else " hidden"}>',
        '        <p class="help-sub">Three things to do now.</p>',
        '        <ol class="steps">',
        "          <li><span><strong>Check your own flight in the airline's app.</strong> The FAA figure is an average, not your flight.</span></li>",
        "          <li><span><strong>Ask about rebooking early.</strong> Seats on later flights go fast when many flights run late.</span></li>",
        "          <li><span><strong>Keep your receipts.</strong> Airline meal and hotel commitments cover delays the airline causes; "
        "a cancellation can still mean a refund, whatever the cause.</span></li>",
        "        </ol>",
        "        </div>",
        '        <div class="stuck-note">',
        (
            '          <p>Delayed or cancelled? The <a class="tap" href="/stuck">step-by-step guide</a> covers airline commitments, '
            'refund rules under 14 CFR 260.6, what to say at the counter and an email draft. Or '
            f'<a class="tap" href="{DOWNTIME_URL}" target="_blank" rel="noopener noreferrer">'
            "check what you may be owed</a>. This is plain-language help, not legal advice; your airline decides "
            "every claim, voucher or reimbursement.</p>"
        ),
        "        </div>",
        "      </section>",
    ]


ART_SIZES = (1440, 2880)
ART_STATE_SIZES = (720, 1440)
ART_NOTE = "Pictures on this site are generated illustrations, not photos of real events or airports."


def solar_is_day(lat: float, lon: float, when: datetime) -> bool:
    """AN38: True when the sun is above the horizon at lat/lon (NOAA low-precision formula, good to about a degree)."""
    import math
    utc = when.astimezone(timezone.utc)
    n = utc.timetuple().tm_yday
    hours = utc.hour + utc.minute / 60.0
    g = 2 * math.pi / 365.0 * (n - 1 + (hours - 12) / 24.0)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    tst = (hours * 60 + eq + 4 * lon) % 1440
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    alt = math.degrees(math.asin(math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)))
    return alt > -0.833


def _hero_is_day(airport_info: dict[str, Any], now: Any) -> bool:
    """Day or night at the airport at build time. The page script corrects it on load. No position: night art."""
    try:
        return solar_is_day(float(airport_info.get("lat")), float(airport_info.get("lon")), now)
    except (TypeError, ValueError, AttributeError):
        return False


def hero_art_key(kind: str, lvl: str, is_day: bool) -> str:
    """AN38: which hero picture the airport state and the time of day choose. Same rule as ATDHeroArt in the page script."""
    if lvl == "night":
        return "ap-sched-night"
    if lvl in ("delay", "stop", "closed"):
        return f"ap-{lvl}-{'day' if is_day else 'night'}"
    return "ap-clear-day" if is_day else f"airport-{kind}"


def hero_preload(kind: str, lvl: str = "clear", is_day: bool = False, prefix: str = "../") -> str:
    """AN38 LCP fix: the hero picture is the largest thing on the first screen, so it is the LCP element. Fetch its small
    AVIF (3 to 9 KB) early from the head instead of late (fetchpriority low), so LCP lands with the text."""
    key = hero_art_key(kind, lvl, is_day)
    base = f"{prefix}assets/art/{key}"
    sizes = ART_SIZES if key.startswith("airport-") else ART_STATE_SIZES
    avif = ", ".join(f"{base}-{w}.avif {w}w" for w in sizes)
    return f'  <link rel="preload" as="image" type="image/avif" imagesrcset="{avif}" imagesizes="100vw" fetchpriority="high">'


def _hero_art(kind: str, lvl: str = "clear", is_day: bool = False, prefix: str = "../") -> list[str]:
    """AN34 r2 and AN38: the GPU-made airfield picture behind a hero band. It follows the airport's state (clear, delay,
    ground stop, closed, closed overnight) and the time of day; airport-type night art is the clear-night picture
    (design/art-log.md). Decoration only (empty alt): it shows a kind of airfield, never this airport or an event."""
    key = hero_art_key(kind, lvl, is_day)
    base = f"{prefix}assets/art/{key}"
    sizes = ART_SIZES if key.startswith("airport-") else ART_STATE_SIZES
    avif = ", ".join(f"{base}-{w}.avif {w}w" for w in sizes)
    jpg = ", ".join(f"{base}-{w}.jpg {w}w" for w in sizes)
    return [
        f'        <div class="band-art" aria-hidden="true" data-art="{key}"><picture>',
        f'          <source type="image/avif" srcset="{avif}" sizes="100vw">',
        f'          <img src="{base}-{sizes[0]}.jpg" srcset="{jpg}" sizes="100vw" alt="" '
        'width="1440" height="810" decoding="async" fetchpriority="high">',
        "        </picture></div>",
    ]


HERO_ART_JS = r"""  <script>
  (function () {
    "use strict";
    var KIND = __KIND__, LAT = __LAT__, LON = __LON__;
    var box = document.querySelector("#ap-hero .band-art");
    var hero = document.getElementById("ap-hero");
    if (!box || !hero) { return; }
    var lvlNow = (/\bap-hero--(\w+)/.exec(hero.className) || [])[1] || "clear";
    function isDay() {
      try { if (LAT === null || !window.Sun) { return null; } var ms = Date.now(); return window.Sun.altitude(LAT, LON, ms, window.Sun.subsolar(ms)) > -0.833; } catch (e) { return null; }
    }
    function keyFor(lvl, day) {
      if (lvl === "night") { return "ap-sched-night"; }
      if (lvl === "delay" || lvl === "stop" || lvl === "closed") { return "ap-" + lvl + (day ? "-day" : "-night"); }
      return day ? "ap-clear-day" : "airport-" + KIND;
    }
    function paint(key) {
      if (box.getAttribute("data-art") === key) { return; }
      var sizes = key.indexOf("airport-") === 0 ? [1440, 2880] : [720, 1440];
      var base = "../assets/art/" + key;
      function set(ext) { return sizes.map(function (w) { return base + "-" + w + "." + ext + " " + w + "w"; }).join(", "); }
      var src = box.querySelector("source"), img = box.querySelector("img");
      if (!src || !img) { return; }
      src.setAttribute("srcset", set("avif"));
      img.setAttribute("srcset", set("jpg"));
      img.setAttribute("src", base + "-" + (key.indexOf("airport-") === 0 ? 1440 : 720) + ".jpg");
      box.setAttribute("data-art", key);
    }
    function update(lvl) {
      if (lvl) { lvlNow = lvl; }
      var d = isDay();
      if (d === null) { return; }
      paint(keyFor(lvlNow, d));
    }
    window.ATDHeroArt = update;
    update();
  })();
  </script>"""


def _hero_art_script(kind: str, lat: Any, lon: Any) -> str:
    """AN38: swaps the hero picture when the airport state changes (the status script calls ATDHeroArt) and at dusk or dawn."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        la = lo = None
    return HERO_ART_JS.replace("__KIND__", json.dumps(kind)).replace("__LAT__", json.dumps(la)).replace("__LON__", json.dumps(lo))


def _airline_home(url: Any) -> str:
    """The airline's home page (scheme and host) from its checked commitments link; '' when unusable."""
    u = _safe_http_url(url)
    if not u:
        return ""
    parts = urllib.parse.urlsplit(u)
    return f"{parts.scheme}://{parts.netloc}/"


def _actions(code: str, airlines: list[dict[str, Any]] | None, airport_site: str, lvl: str = "clear") -> list[str]:
    """AN34 r2: one action strip under the answer: the stuck guide, and 'Check my flight'.
    AN35: 'Check my flight' is a box: type a flight number and the page opens that airline's own status page.
    We hold no flight data, so the box says where a flight's own time lives instead of guessing it."""
    site = (
        f' The <a class="tap" href="{_esc(airport_site)}" target="_blank" rel="noopener noreferrer">airport\'s own site</a> lists its departures too.'
        if airport_site else ""
    )
    # Check the airline in every FAA state; keep the stuck guide alongside it.
    return [
        '        <div class="ap-actions">',
        f'          <a id="stuck-btn" class="btn btn-ghost" href="/stuck">I\'m stuck guide</a>',
        '          <details class="flight-check">',
        f'            <summary id="flight-btn" class="btn btn-accent">Check my flight</summary>',
        '            <div class="flight-pop">',
        f"              <p class=\"small\">Your flight's own time is on your airline's page.{site}</p>",
        *_flight_check(code),
        "            </div>",
        "          </details>",
        "        </div>",
    ]


def _render_history(code: str, tz: str, history: dict[str, Any] | None) -> list[str]:
    """Past hours at this airport, from data/history-summary.json (a copy of our own hourly archive). Past facts only."""
    row = ((history or {}).get("airports") or {}).get(code)
    hours = (history or {}).get("hours") or []
    if not row or len(row) != len(hours):
        return []
    try:
        zone = ZoneInfo(tz) if tz else timezone.utc
    except Exception:  # unknown zone name
        zone = timezone.utc
    seen = [c for c in row if c != "-"]
    if len(seen) < 24:
        return []
    n_stop, n_delay = seen.count("s"), seen.count("d")
    n_prog = n_stop + n_delay
    first = pt.parse_utc(str((history or {}).get("first_reading_utc") or ""))
    last = pt.parse_utc(str((history or {}).get("last_reading_utc") or ""))

    def day_hour(dt: Any) -> str:
        local = dt.astimezone(zone)
        return local.strftime("%a %b ") + str(local.day) + local.strftime(" %-I %p").replace(" 0", " ")

    word = {"c": "no program", "d": "delay", "s": "ground stop or closure", "-": "no reading"}
    # AN34: start the strip at the first hour we have a reading for, so it does not open on a grey block.
    lead_gap = 0
    while lead_gap < len(row) and row[lead_gap] == "-":
        lead_gap += 1
    hours, row = hours[lead_gap:], row[lead_gap:]
    cells = []
    for h, c in zip(hours, row):
        dt = pt.parse_utc(h)
        label = f"{day_hour(dt)} local: {word[c]}" if dt else word[c]
        cells.append(f'<span class="hh hh--{ {"c": "clear", "d": "delay", "s": "stop", "-": "none"}[c] }" title="{_esc(label)}"></span>')
    start = pt.parse_utc(hours[0]) if hours else None
    since = day_hour(start) if start else (day_hour(first) if first else "")
    if n_prog == 0:
        # AN34 round 4: a calm record is one sentence, not a strip of identical green bars.
        head = f"Clear the whole time: no FAA delay or stop in {len(seen)} hourly checks" + (f" since {since}." if since else ".")
    else:
        parts = []
        if n_stop:
            parts.append(f"{n_stop} with a ground stop or closure")
        if n_delay:
            parts.append(f"{n_delay} with a delay")
        head = f"An FAA program was on in {n_prog} of {len(seen)} hourly checks" + (f" since {since}" if since else "") + f" ({', '.join(parts)})."
    gen = pt.parse_utc(str((history or {}).get("generated_utc") or ""))
    age = pt.ago_text(pt.age_minutes(str((history or {}).get("generated_utc") or ""), pt.now_utc())) if gen else ""
    out = [
        '          <div class="today-cell today-hist" aria-labelledby="history-heading">',
        '            <h3 id="history-heading" class="fact-k">Last 3 days</h3>',
        f'            <p class="hist-lead">{_esc(head)}</p>',
    ]
    if n_prog:
        out += [
            f'            <div class="hist-strip" role="img" aria-label="{_esc(head)} One cell per hour, oldest first, newest on the right.">{"".join(cells)}</div>',
            '            <p class="hist-key"><span class="hh hh--clear"></span>no program <span class="hh hh--delay"></span>delay <span class="hh hh--stop"></span>ground stop or closure'
            + (' <span class="hh hh--none"></span>no reading' if "-" in row else "") + '</p>',
        ]
    out += [
        '            <p class="fact-src">Our hourly record of the FAA feed' + (f", updated {_esc(age)}" if age else "") + '.</p>',
        "          </div>",
    ]
    return out


def _what_to_do(chip_class: str, live: dict[str, Any]) -> list[str]:
    """Two or three plain lines for the traveler. Wording follows kits/desk/CHARTER.md: 'possibly owed', never 'must cover'."""
    if not live.get("has") or live.get("stale"):
        return []
    if "badge--stop" in chip_class:
        lines = ["Flights are held or the airport is shut right now. Check your airline's app or text alerts before you leave for the airport.",
                 "Your airline decides how to rebook you. The stuck guide lists what each airline has committed to."]
    elif "badge--delay" in chip_class:
        lines = ["Expect late departures. Check your airline's app for your flight's new time before you leave for the airport.",
                 "Ask before you pay for a meal or a hotel; some airlines have committed to cover them."]
    else:
        lines = ["No FAA program is listed for this airport now. A flight can still be late for airline reasons, so check your airline's app.",
                 "Leave for the airport as you normally would."]
    return ['        <ul class="ap-do" aria-label="What to do now">', *[f"          <li>{_esc(x)}</li>" for x in lines], "        </ul>"]


def _delay_sizes(entry: dict[str, Any] | None) -> str:
    """'Flights are leaving about 2 hours and 20 minutes late on average, up to 7 hours and 7 minutes.' from FAA program fields."""
    for ev in (entry or {}).get("events") or []:
        if not isinstance(ev, dict) or ev.get("kind") not in ("ground_delay", "delay"):
            continue
        avg, mx = str(ev.get("avg") or "").strip(), str(ev.get("max") or "").strip()
        if avg and mx:
            return f"The FAA lists delays of about {avg} on average, up to {mx}."
        if avg or mx:
            return f"The FAA lists delays of {'about ' + avg + ' on average' if avg else 'up to ' + mx}."
    return ""


def _nearby(code: str, airports_map: dict[str, Any], live_cards: dict[str, Any], limit: int = 3, max_miles: int = 150) -> list[tuple[str, str, int, str]]:
    """Closest other airports of the 100, with straight-line miles and their FAA word now. For a closed airport."""
    import math
    me = airports_map.get(code) or {}
    try:
        la, lo = float(me["lat"]), float(me["lon"])
    except (KeyError, TypeError, ValueError):
        return []
    out = []
    for c, info in airports_map.items():
        if c == code:
            continue
        try:
            lb, ln = float(info["lat"]), float(info["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        p1, p2 = math.radians(la), math.radians(lb)
        a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(ln - lo) / 2) ** 2
        miles = int(round(3958.8 * 2 * math.asin(math.sqrt(a))))
        if miles > max_miles:
            continue
        card = live_cards.get(c)
        level = (card or {}).get("level") if isinstance(card, dict) else None
        word = {"clear": "clear", "delay": "delays", "stop": "ground stop", "closed": "closed"}.get(str(level), "")
        out.append((c, str(info.get("name") or c), miles, word))
    out.sort(key=lambda x: x[2])
    return out[:limit]


THEME_SNIPPET = '<script>(function(){try{var t=localStorage.getItem("atd-theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})()</script>'
THEME_BUTTON = '<button class="theme-toggle" type="button" data-theme-toggle data-mode="system" aria-label="Theme: System. Press to change."><svg viewBox="0 0 24 24" aria-hidden="true"><g class="ti ti-system"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></g><g class="ti ti-light"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></g><g class="ti ti-dark"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></g></svg></button>'


def _render_head(
    *,
    title: str,
    description: str,
    canonical: str,
    breadcrumb: dict[str, Any],
    preload: str = "",
) -> str:
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">',
        f"  <title>{_esc(title)}</title>",
        f'  <meta name="description" content="{_esc(description)}">',
        f'  <link rel="canonical" href="{_esc(canonical)}">',
        f'  <meta property="og:title" content="{_esc(title)}">',
        f'  <meta property="og:description" content="{_esc(description)}">',
        f'  <meta property="og:image" content="{SITE_URL}/og.png">',
        f'  <meta property="og:url" content="{_esc(canonical)}">',
        '  <meta property="og:type" content="website">',
        '  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:title" content="{_esc(title)}">',
        f'  <meta name="twitter:description" content="{_esc(description)}">',
        f'  <meta name="twitter:image" content="{SITE_URL}/og.png">',
        '  <meta name="theme-color" content="#080b0f" media="(prefers-color-scheme: dark)">',
        '  <meta name="theme-color" content="#f6f4ef" media="(prefers-color-scheme: light)">',
        '  <link rel="icon" href="../favicon.svg" type="image/svg+xml">',
        '  <link rel="icon" href="../favicon.png" type="image/png">',
        *([preload] if preload else []),
        '  ' + THEME_SNIPPET,
        '  <script src="../theme.js" defer></script>',
        '  <script src="../watch.js" defer></script>',
        '  <link rel="stylesheet" href="../tokens.css">',
        '  <link rel="stylesheet" href="../style.css">',
        _json_ld_script(breadcrumb),
        "</head>",
    ])


def _nav_chip(label: str, href: str, current: bool, extra: str = "") -> str:
    attrs = ' aria-current="page"' if current else ""
    cls = f"chip {extra}".strip()
    return f'        <a class="{cls}" href="{href}"{attrs}>{label}</a>'


def _render_header(current: str = "airports", airports_href: str = "/airports/") -> str:
    """The one site header (AN34): brand, then Live board · Airports · Airlines · Stuck? · About.
    On phones only Airports and Stuck? show; the rest are in the footer."""
    airlines_href = "/airlines/"
    return "\n".join([
        '  <a class="skip-link" href="#main-content">Skip to main content</a>',
        '  <header class="site-header">',
        '    <div class="header-in">',
        '      <a class="brand" href="/">',
        '        <img class="brand-logo" src="../brand/logo.svg" width="30" height="30" alt="">',
        '        <span class="brand-title">Air Travel Desk</span>',
        "      </a>",
        '      <nav class="header-nav" aria-label="Site navigation">',
        _nav_chip("Live board", "/", current == "board", "nav-wide"),
        _nav_chip("Airports", airports_href, current == "airports"),
        _nav_chip("Airlines", airlines_href, current == "airlines", "nav-wide"),
        _nav_chip("Stuck?", "/stuck", current == "stuck"),
        _nav_chip("About", "/about", current == "about", "nav-wide"),
        "      </nav>",
        "      " + THEME_BUTTON,
        "    </div>",
        "  </header>",
        '  <div class="container">',
    ])


def _render_footer(
    airports_href: str = "/airports/",
    airlines_href: str = "/airlines/",
    note: str = "Updated automatically from public data. Not affiliated with any airline or government agency.",
) -> str:
    return "\n".join([
        "  </div>",
        '    <footer class="site-footer">',
        '      <div class="container foot-grid">',
        '        <div class="foot-col">',
        '          <p class="foot-h">Air Travel Desk</p>',
        f"          <p>{_esc(note)}</p>",
        f'          <p class="foot-art">{ART_NOTE}</p>',
        "        </div>",
        '        <div class="foot-col">',
        (
            '          <ul class="foot-links"><li><a class="tap" href="/">Live board</a></li>'
            f'<li><a class="tap" href="{airports_href}">Airports</a></li>'
            f'<li><a class="tap" href="{airlines_href}">Airline commitments</a></li>'
            '<li><a class="tap" href="/about">About</a></li>'
            '<li><a class="tap" href="/sources">Data and sources</a></li>'
            '<li><a class="tap" href="/privacy">Privacy</a></li></ul>'
        ),
        f'          <p class="foot-contact">Contact: <a class="tap" href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>',
        "        </div>",
        "      </div>",
        "    </footer>",
    ])


def _sun_now_script() -> str:
    """Inline script: fills the daylight tile from ../sun.js. No network request. Any failure leaves it hidden."""
    return "\n".join([
        '  <script src="../sun.js"></script>',
        "  <script>",
        "  (function () {",
        '    "use strict";',
        '    var p = document.getElementById("sun-now");',
        '    var src = document.getElementById("sun-now-source");',
        '    var tile = document.getElementById("sun-tile");',
        "    if (!p || !window.Sun) { return; }",
        "    function paint() {",
        "      try {",
        '        var tz = p.getAttribute("data-tz"), now = Date.now();',
        '        var s = window.Sun.hubSun(parseFloat(p.getAttribute("data-lat")), parseFloat(p.getAttribute("data-lon")), tz, now);',
        "        var F = function (ms) { return window.Sun.fmtTime(ms, tz); };",
        '        var head = "", sub = "";',
        '        if (s.state === "polar_day") { head = "Sun stays up"; }',
        '        else if (s.state === "polar_night") { head = "Sun stays down"; }',
        '        else if (s.sunrise !== null && s.sunrise > now) { head = "Sunrise " + F(s.sunrise); sub = "Sunset " + F(s.sunset); }',
        '        else if (s.sunset !== null && s.sunset > now) { head = "Sunset " + F(s.sunset); sub = "Sunrise was " + F(s.sunrise); }',
        '        else { head = "Sunrise " + F(s.sunrise + 86400000); sub = "Sunset was " + F(s.sunset); }',
        "        var zone = new Intl.DateTimeFormat(\"en-US\", { timeZone: tz, timeZoneName: \"short\" }).formatToParts(new Date()).filter(function (x) { return x.type === \"timeZoneName\"; })[0];",
        "        p.textContent = head;",
        '        p.hidden = false;',
        '        if (src) { src.textContent = (sub ? sub + ". " : "") + "Local time at the airport" + (zone ? " (" + zone.value + ")" : "") + "."; src.hidden = false; }',
        "        if (tile) { tile.hidden = false; }",
        "      } catch (e) { p.hidden = true; if (src) { src.hidden = true; } if (tile) { tile.hidden = true; } }",
        "    }",
        "    paint();",
        "  })();",
        "  </script>",
    ])


AIRPORT_JS_NAME = "airport.js"
AIRPORT_JS_HEAD = ("/* Air Travel Desk airport pages: daylight tile and live status. Built by tools/build_airport_pages.py; do not edit.\n"
                   "   AN43: one shared, cached, deferred file in place of 26 KB of inline script per page. It reads the airport\n"
                   "   from its own script tag (data-code, data-tz, data-short). It paints once; no timer refreshes the page. */\n")


def _strip_script_tags(block: str) -> str:
    return "\n".join(ln for ln in block.split("\n") if ln.strip() not in ("<script>", "</script>") and 'src="../sun.js"' not in ln)


def airport_js() -> str:
    """The text of airport.js: the sun tile script, then the live status script with its airport read from data attributes."""
    sentinel = "\u0000AIRPORT\u0000"
    live = _strip_script_tags(_right_now_script(sentinel, sentinel + "TZ", sentinel + "SHORT"))
    live = live.replace(f"    var CODE = {json.dumps(sentinel)};", '    var CODE = (ATD_ME && ATD_ME.getAttribute("data-code")) || "";')
    live = live.replace(f"    var TZ = {json.dumps(sentinel + 'TZ')};", '    var TZ = (ATD_ME && ATD_ME.getAttribute("data-tz")) || "";')
    live = live.replace(f"    var SHORT = {json.dumps(sentinel + 'SHORT')};", '    var SHORT = (ATD_ME && ATD_ME.getAttribute("data-short")) || CODE;')
    if "\u0000" in live or "AIRPORT\u0000" in live:
        raise ValueError("airport.js: a per-airport value was left in the shared script")
    sun = _strip_script_tags(_sun_now_script())
    hero = _strip_script_tags(HERO_ART_JS).replace(
        "var KIND = __KIND__, LAT = __LAT__, LON = __LON__;",
        'var KIND = (ATD_ME && ATD_ME.getAttribute("data-kind")) || "inland";\n'
        '    var LAT = ATD_ME && ATD_ME.getAttribute("data-lat") ? parseFloat(ATD_ME.getAttribute("data-lat")) : null;\n'
        '    var LON = ATD_ME && ATD_ME.getAttribute("data-lon") ? parseFloat(ATD_ME.getAttribute("data-lon")) : null;')
    if "__KIND__" in hero or "__LAT__" in hero:
        raise ValueError("airport.js: hero art placeholders were left in the shared script")
    return AIRPORT_JS_HEAD + "var ATD_ME = document.currentScript;\n" + sun + "\n" + hero + "\n" + live + "\n"


# LCP: the page scripts (sun, status, map) are fetched and run in order after the load event, so the hero picture can paint first
# (they ran before first paint when they were `defer`, which cost about 0.5 s of mobile Lighthouse LCP). Same files, same order.
LATE_LOADER = (
    '  <script>(function(){var done=false;function go(){if(done){return;}done=true;var s=document.querySelectorAll(\'script[type="text/atd-late"]\'),i=0;(function n(){if(i>=s.length){return;}'
    'var o=s[i++],e=document.createElement("script");for(var a=0;a<o.attributes.length;a++){var t=o.attributes[a];if(t.name!=="type"){e.setAttribute(t.name,t.value);}}'
    'e.onload=e.onerror=n;o.parentNode.replaceChild(e,o);})();}'
    'function later(){setTimeout(go,150);}'
    'try{new PerformanceObserver(function(l,ob){ob.disconnect();later();}).observe({type:"largest-contentful-paint",buffered:true});}catch(x){}'
    'if(document.readyState==="complete"){later();}else{addEventListener("load",later);}setTimeout(go,4000);})();</script>'
)



def _airport_js_tag(code: str, tz: str, short: str, kind: str = "", lat: Any = None, lon: Any = None) -> str:
    extra = ""
    try:
        if lat is not None and lon is not None:
            extra = f' data-lat="{float(lat):.4f}" data-lon="{float(lon):.4f}"'
    except (TypeError, ValueError):
        extra = ""
    return (f'  <script src="../{AIRPORT_JS_NAME}" data-code="{_esc(code)}" data-tz="{_esc(tz)}" '
            f'data-short="{_esc(short or code)}"' + (f' data-kind="{_esc(kind)}"' if kind else "") + extra + ' type="text/atd-late"></script>')


def _right_now_script(code: str, tz: str = "", short: str = "") -> str:
    """Inline client-side script: refreshes the status chip, the verdict and the tiles in #right-now from ../data/airports.json."""
    code_json = json.dumps(code)
    tz_json = json.dumps(tz)
    short_json = json.dumps(short or code)
    return "\n".join([
        "  <script>",
        "  (function () {",
        '    "use strict";',
        f"    var CODE = {code_json};",
        f"    var TZ = {tz_json};",
        f"    var SHORT = {short_json};",
        '    var box = document.getElementById("right-now");',
        '    var statusChip = document.getElementById("status-chip");',
        '    var wxChip = document.getElementById("weather-chip");',
        '    var verdictEl = document.getElementById("ap-verdict");',
        '    var hero = document.getElementById("ap-hero");',
        "    if (!box) { return; }",
        '    var INITIAL_LVL = hero ? ((/\\bap-hero--(\\w+)/.exec(hero.className) || [])[1] || "") : "";',
        '    var LEVEL_TEXT = { clear: "Clear: no FAA delay or ground stop listed.", delay: "Delays: FAA delay program in effect.", stop: "Ground stop: FAA ground stop in effect.", closed: "Closed: FAA airport closure in effect.", night: "Closed overnight: the FAA lists a daily closure." };',
        '    var BADGE_CLASS = { clear: "badge badge--clear", delay: "badge badge--delay", stop: "badge badge--stop", closed: "badge badge--stop", night: "badge badge--night" };',
        '    var BADGE_LABEL = { clear: "No FAA delays reported", delay: "Delays", stop: "Ground stop", closed: "Closed", night: "Closed overnight" };',
        '    // AN35: a closure the FAA lists as daily (events[].daily, UTC hours "0730-1415") is calm. Same rule as prerender_text.closure_schedule.',
        '    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];',
        '    function listedUtc(t) {',
        '      var m = /([A-Z][a-z]{2}) (\\d{1,2}) at (\\d{2}):(\\d{2}) UTC/.exec(String(t || "")), mo = m ? MONTHS.indexOf(m[1]) : -1;',
        '      if (mo < 0) { return null; }',
        '      var n = new Date();',
        '      return Date.UTC(n.getUTCFullYear() + (mo < n.getUTCMonth() - 6 ? 1 : 0), mo, +m[2], +m[3], +m[4]);',
        '    }',
        '    function localClock(ms) {',
        '      try { var o = { hour: "numeric", minute: "2-digit" }; if (TZ) { o.timeZone = TZ; } return new Intl.DateTimeFormat("en-US", o).format(new Date(ms)).replace(/\\u202f/g, " "); } catch (e) { return ""; }',
        '    }',
        '    function closureSchedule(ev, atMs) {',
        '      if (!ev || ev.kind !== "closure") { return null; }',
        '      var m = /^(\\d{2})(\\d{2})-(\\d{2})(\\d{2})$/.exec(String(ev.daily || ""));',
        '      if (!m) { return null; }',
        '      var s = +m[1] * 60 + +m[2], e = +m[3] * 60 + +m[4];',
        '      if (s === e || s >= 1440 || e >= 1440) { return null; }',
        '      var now = atMs == null ? Date.now() : atMs, d = new Date(now), t = d.getUTCHours() * 60 + d.getUTCMinutes();',
        '      var inW = s < e ? (t >= s && t < e) : (t >= s || t < e);',
        '      var st = listedUtc(ev.start), en = listedUtc(ev.reopen);',
        '      if ((st && now < st - 864e5) || (en && now >= en)) { inW = false; }',
        '      function nextAt(min) { var b = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), Math.floor(min / 60), min % 60); return b > now ? b : b + 864e5; }',
        '      return { in_window: inW, reopen: localClock(nextAt(e)), close: localClock(nextAt(s)) };',
        '    }',
        '    function nightSchedule(a) { var r = null; (a.events || []).forEach(function (ev) { var x = !r && closureSchedule(ev); if (x) { r = x; } }); return r; }',
        '    function effLevel(a, atMs) {',
        '      var evs = (a.events || []).filter(Boolean), cl = evs.filter(function (ev) { return ev.kind === "closure"; });',
        '      if (cl.length || a.level === "closed") {',
        '        var sc = cl.map(function (ev) { return closureSchedule(ev, atMs); });',
        '        if (cl.length && sc.every(Boolean)) {',
        '          if (sc.some(function (x) { return x.in_window; })) { return "night"; }',
        '          var rest = evs.filter(function (ev) { return ev.kind !== "closure"; });',
        '          if (rest.some(function (ev) { return ev.kind === "ground_stop"; })) { return "stop"; }',
        '          return rest.length ? "delay" : "clear";',
        '        }',
        '        return "closed";',
        '      }',
        '      return LEVEL_TEXT[a.level] && a.level !== "night" ? a.level : "clear";',
        '    }',
        '    var WX_LABEL = { fresh: "Weather now: ", stale: "Last weather report: " };',
        "    function badgeLabel(a, lvl) {",
        "      if (lvl === \"delay\" && Array.isArray(a.events) && a.events.some(function (ev) { return ev && ev.kind === \"ground_delay\"; })) { return \"Ground delay program\"; }",
        "      return BADGE_LABEL[lvl];",
        "    }",
        '    var RP = { WX: "weather", VOLUME: "traffic volume", "RWY/TWY": "runway or taxiway", EQUIPMENT: "equipment", STAFFING: "staffing", OTHER: "other" };',
        '    function reasonPlain(r) {',
        '      return String(r || "").split(";").map(function (x) {',
        '        x = x.trim(); var m = /^([A-Za-z/]+):\\s*(.*)$/.exec(x); var p = m && RP[m[1].toUpperCase()];',
        '        if (!p) { return x; }',
        '        var rest = m[2].toLowerCase(); return !rest || rest === p || rest === "volume" ? p : p + ", " + rest;',
        '      }).filter(Boolean).join("; ");',
        '    }',
        "    function el(tag, cls, text) {",
        "      var n = document.createElement(tag);",
        "      if (cls) { n.className = cls; }",
        "      if (text != null) { n.textContent = text; }",
        "      return n;",
        "    }",
        "    function srcLine(cls, before, linkText, after) {",
        '      var p = el("p", cls);',
        '      if (before) { p.appendChild(document.createTextNode(before)); }',
        '      var a = el("a", "tap", linkText);',
        '      a.href = "/sources";',
        "      p.appendChild(a);",
        '      if (after) { p.appendChild(document.createTextNode(after)); }',
        "      return p;",
        "    }",
        "    // One tile: a label, the value, then the source in brackets.",
        "    function tile(cls, label, value, linkText, after) {",
        '      var d = el("div", "fact " + cls), p = el("p");',
        '      p.appendChild(el("span", "fact-k", label.replace(/ $/, "")));',
        '      p.appendChild(document.createTextNode(" "));',
        '      p.appendChild(el("span", "fact-v", value));',
        '      p.appendChild(document.createTextNode(" "));',
        '      var s = el("span", "fact-src");',
        '      var a = el("a", "tap", linkText); a.href = "/sources"; s.appendChild(a);',
        '      s.appendChild(document.createTextNode(after));',
        '      p.appendChild(s);',
        '      d.appendChild(p);',
        '      return d;',
        "    }",
        '    // AN34 r2: wind in miles per hour, same rule as prerender_text.wind_text.',
        '    function mph(kt) { return Math.round(kt * 1.15078); }',
        '    function windText(w, gusts) { if (Math.round(w.wind_kt) === 0) { return "calm"; } return mph(w.wind_kt) + " mph" + (gusts && w.gust_kt ? " gusting " + mph(w.gust_kt) + " mph" : ""); }',
        '    // AN34 r2: the help card follows the live state (three steps when delayed or closed, quiet when clear).',
        '    function scaleHelp(lvl) {',
        '      var card = document.getElementById("help-card");',
        '      if (!card) { return; }',
        '      var hot = lvl === "delay" || lvl === "stop" || lvl === "closed";',
        '      card.className = "airport-section help-card" + (hot ? " help-card--hot help-card--" + (lvl === "delay" ? "amber" : "red") : "");',
        '      var hh = document.getElementById("stuck-heading");',
        '      if (hh) { hh.textContent = hot ? "Flying through " + CODE + " today?" : "If your flight is hit"; }',
        '      var steps = card.querySelector(".help-hot");',
        '      if (steps) { steps.hidden = !hot; }',
        '      // Checking the airline leads in every state.',
        '      var sb = document.getElementById("stuck-btn"), fb = document.getElementById("flight-btn");',
        '      if (sb) { sb.className = "btn btn-ghost"; }',
        '      if (fb) { fb.className = "btn btn-accent"; }',
        '    }',
        '    var STALE_MIN = 30;',
        '    function ageMin(iso) {',
        '      var ms = Date.parse(iso || "");',
        '      return isFinite(ms) ? Math.max(0, Math.floor((Date.now() - ms) / 60000)) : null;',
        '    }',
        '    function isStale(m) { return m == null || m > STALE_MIN; }',
        '    function durText(m) {',
        '      if (m < 60) { return m + " min"; }',
        '      if (m < 1440) { var h = Math.floor(m / 60); return h === 1 ? "1 hour" : h + " hours"; }',
        '      var d = Math.floor(m / 1440);',
        '      return d === 1 ? "1 day" : d + " days";',
        '    }',
        '    function agoText(m) {',
        '      if (m == null) { return "age unknown"; }',
        '      return m < 1 ? "less than 1 min ago" : durText(m) + " ago";',
        '    }',
        '    function oldText(m) {',
        '      if (m == null) { return "of unknown age"; }',
        '      if (m < 60) { return m === 1 ? "1 minute old" : m + " minutes old"; }',
        '      return durText(m) + " old";',
        '    }',
        '    function ageLabel(iso, stale) {',
        '      var m = ageMin(iso);',
        '      return m == null ? "update time unknown" : (stale ? "last updated " : "updated ") + agoText(m);',
        '    }',
        '    function minutesOf(t) {',
        '      var h = /(\\d+)\\s*hours?/i.exec(t || ""), m = /(\\d+)\\s*minutes?/i.exec(t || "");',
        '      return (!h && !m) ? null : (h ? parseInt(h[1], 10) * 60 : 0) + (m ? parseInt(m[1], 10) : 0);',
        '    }',
        '    function dur(min) { var h = Math.floor(min / 60), m = min % 60; return h && m ? h + "\\u00a0h " + m + "\\u00a0min" : h ? h + "\\u00a0h" : m + "\\u00a0min"; }',
        '    var ZONES = { eastern: "America/New_York", central: "America/Chicago", mountain: "America/Denver", pacific: "America/Los_Angeles", alaska: "America/Anchorage", hawaii: "Pacific/Honolulu" };',
        '    function zoneParts(ms, zone) {',
        '      var f = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" });',
        '      var o = {};',
        '      f.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = parseInt(p.value, 10); });',
        '      return o;',
        '    }',
        '    function localToMs(y, mo, d, h, mi, zone) {',
        '      var guess = Date.UTC(y, mo - 1, d, h, mi);',
        '      for (var i = 0; i < 2; i++) {',
        '        var p = zoneParts(guess, zone);',
        '        guess += Date.UTC(y, mo - 1, d, h, mi) - Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);',
        '      }',
        '      return guess;',
        '    }',
        '    function forecastEnd(text, issuedIso, tz) {',
        '      var m = /\\b(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)\\b(?:\\s+(eastern|central|mountain|pacific|alaska|hawaii))?/i.exec(String(text || ""));',
        '      var issued = Date.parse(issuedIso || "");',
        '      if (!m || !isFinite(issued)) { return null; }',
        '      var zone = (m[4] && ZONES[m[4].toLowerCase()]) || tz;',
        '      if (!zone) { return null; }',
        '      try {',
        '        var h = parseInt(m[1], 10) % 12 + (m[3].toLowerCase() === "pm" ? 12 : 0), mi = m[2] ? parseInt(m[2], 10) : 0;',
        '        var base = zoneParts(issued, zone);',
        '        for (var add = 0; add < 3; add++) {',
        '          var day = new Date(Date.UTC(base.year, base.month - 1, base.day + add));',
        '          var c = localToMs(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), h, mi, zone);',
        '          if (c > issued) { return c; }',
        '        }',
        '      } catch (e) { return null; }',
        '      return null;',
        '    }',
        '    function forecastExpired(text, issuedIso) {',
        '      var end = forecastEnd(text, issuedIso, TZ);',
        '      return end == null || end <= Date.now();',
        '    }',
        '    function showStale(iso, forced) {',
        '      var n = document.getElementById("stale-notice");',
        '      if (!n) { return; }',
        '      var m = ageMin(iso);',
        '      if (!forced && !isStale(m)) { n.hidden = true; return; }',
        '      n.textContent = "This data is " + oldText(m) + ", not live. ";',
        '      n.appendChild(el("span", "sn-long", "FAA\'s own page: "));',
        '      var l = el("a", "stale-link");',
        '      l.appendChild(el("span", "sn-wide", "nasstatus.faa.gov"));',
        '      l.appendChild(el("span", "sn-short", "FAA status"));',
        '      l.href = "https://nasstatus.faa.gov";',
        '      l.target = "_blank";',
        '      l.rel = "noopener noreferrer";',
        '      n.appendChild(l);',
        '      n.hidden = false;',
        '    }',
        '    // AN34 round 4: "Early Monday, 1:27 AM in Atlanta", the FAA check time in the airport zone. Same rule as prerender_text.airport_dateline.',
        '    function datelineText(iso) {',
        '      var ms = Date.parse(iso || "");',
        '      if (!isFinite(ms)) { return ""; }',
        '      try {',
        '        var o = { weekday: "long", hour: "numeric", hourCycle: "h23" }; if (TZ) { o.timeZone = TZ; }',
        '        var parts = {}; new Intl.DateTimeFormat("en-US", o).formatToParts(new Date(ms)).forEach(function (x) { parts[x.type] = x.value; });',
        '        var h = parseInt(parts.hour, 10) % 24, d = parts.weekday, c = clockLabel(iso).replace(/ [A-Z]{2,5}$/, "");',
        '        var lead = h < 5 ? "Early " + d : d + " " + (h < 12 ? "morning" : h < 17 ? "afternoon" : h < 21 ? "evening" : "night");',
        '        return lead + ", " + c + " in " + SHORT;',
        '      } catch (e) { return ""; }',
        '    }',
        '    function clockLabel(iso) {',
        '      var ms = Date.parse(iso || "");',
        '      if (!isFinite(ms)) { return ""; }',
        '      try {',
        '        var opts = { hour: "numeric", minute: "2-digit", timeZoneName: "short" };',
        '        if (TZ) { opts.timeZone = TZ; }',
        '        return new Intl.DateTimeFormat("en-US", opts).format(new Date(ms));',
        '      } catch (e) { return ""; }',
        '    }',
        '    function checkedText(iso, stale) {',
        '      var c = clockLabel(iso);',
        '      var m = ageMin(iso);',
        '      return c ? (stale ? "last checked " : "checked ") + c + " (" + agoText(m == null ? 0 : m) + ")" : "check time unknown";',
        '    }',
        "    // The H1 in plain words. Same rule as _verdict in tools/build_airport_pages.py.",
        '    function verdict(a, lvl, stale, label, asOf) {',
        '      var h = el("span"), em = function (t) { return el("em", null, t); }, tx = function (t) { return document.createTextNode(t); };',
        '      if (["clear", "delay", "stop", "closed"].indexOf(a.level) < 0) { h.appendChild(tx("Last known status: FAA status unavailable.")); return h; } if (stale) { h.appendChild(tx(label + " at " + SHORT + ", " + asOf + ".")); return h; }',
        '      if (lvl === "night") { h.appendChild(tx(SHORT + " is ")); h.appendChild(em("closed overnight")); h.appendChild(tx(".")); return h; }',
        '      if (lvl === "closed") { h.appendChild(tx(SHORT + " is ")); h.appendChild(em("closed")); h.appendChild(tx(" to flights.")); return h; }',
        '      if (lvl === "stop") { h.appendChild(em("Ground stop:")); h.appendChild(tx(" flights to " + SHORT + " are held where they are.")); return h; }',
        '      if (lvl === "delay") { h.appendChild(tx("The FAA lists ")); h.appendChild(em("delays")); h.appendChild(tx(" at " + SHORT + ".")); return h; }',
        '      h.appendChild(tx("No FAA delays at " + SHORT + " ")); h.appendChild(em("right now")); h.appendChild(tx(".")); return h;',
        '    }',
        '    // AN35: the one place the FAA data age is stated (the stale banner states it when the data is old). Same rule as prerender_text.faa_age_parts.',
        '    function faaParts(iso, stale) {',
        '      var c = clockLabel(iso), m = ageMin(iso);',
        '      if (!c) { return ["Source: ", ", check time unknown."]; }',
        '      return stale ? ["Source: ", ", last checked " + c + "."] : ["FAA data " + (m < 1 ? "under 1 min" : durText(m)) + " old, checked " + c + ". Source: ", "."];',
        '    }',
        '    var CAT_WORDS = { MVFR: "reduced ceiling or visibility", IFR: "low ceiling or poor visibility", LIFR: "very low ceiling or visibility" };',
        '    // Same rule as outlook_text in tools/build_airport_pages.py.',
        '    function outlookText(w) {',
        '      var t = String(w.next3h_text || "").trim();',
        '      if (!t) { return ""; }',
        '      var cat = String(w.next3h_cat || "").toUpperCase();',
        '      if (CAT_WORDS[cat] && !/cloud|ceiling|visib|fog|mist|haze/i.test(t)) { t += " (" + cat + ": " + CAT_WORDS[cat] + ")"; }',
        '      if (w.next3h_storms && !/storm/i.test(t)) { t += ". Storms possible"; }',
        '      return t;',
        '    }',
        '    // The TSA wait line is built with the page; only its age text moves on.',
        '    var tsaLine = document.getElementById("ap-tsa");',
        '    if (tsaLine) {',
        '      var tsaAge = tsaLine.querySelector(".gl-age"), tsaMin = ageMin(tsaLine.getAttribute("data-utc"));',
        '      if (tsaAge && tsaMin != null) { if (tsaMin > 60) { tsaLine.hidden = true; } else { tsaAge.textContent = oldText(tsaMin); } }',
        '    }',
        '    var checkedLine = document.getElementById("checked-line");',
        '    var heading = document.getElementById("ap-now-word");',
        '    function statusMeaning(a, lvl, stale) {',
        '      if (stale || !a || ["clear", "delay", "stop", "closed"].indexOf(a.level) < 0) { return "Last known status: current arrivals and departures are unconfirmed; this is airport-wide, not the status of any individual flight."; }',
        '      var kinds = (a.events || []).filter(Boolean).map(function (e) { return e.kind; }), meaning; var directions = (a.events || []).filter(Boolean).filter(function (e) { return e.kind === "delay"; }).map(function (e) { return String(e.direction || "").toLowerCase(); }); var departure = kinds.indexOf("departure_delay") >= 0 || directions.indexOf("departure") >= 0;',
        '      if (lvl === "closed" || lvl === "night") { meaning = "the FAA lists a closure affecting arrivals and departures"; }',
        '      else if (lvl === "stop") { meaning = "departures to this airport are held at their origin airports, rather than departures from here"; }',
        '      else if (kinds.indexOf("ground_delay") >= 0) { meaning = "arrivals are held at their origin airports, rather than departures from here"; if (departure) { meaning += "; departure delays are also listed here"; } }',
        '      else if (departure && directions.indexOf("arrival") >= 0) { meaning = "the FAA lists both arrival and departure delays"; }',
        '      else if (departure) { meaning = "departures from this airport are delayed; this does not describe arrivals"; }',
        '      else if (directions.indexOf("arrival") >= 0) { meaning = "arrivals at this airport are delayed; this does not describe departures"; }',
        '      else if (lvl === "clear") { meaning = "no FAA arrival or departure programs are listed"; }',
        '      else { meaning = "the FAA lists delays without a confirmed arrival or departure direction"; }',
        '      return "Airport-wide status: " + meaning + "; this is not the status of any individual flight.";',
        '    }',
        '    function meaningElement() {',
        '      var n = document.getElementById("ap-meaning");',
        '      if (!n && checkedLine && checkedLine.parentNode) {',
        '        n = el("p", "ap-lead"); n.id = "ap-meaning";',
        '        checkedLine.parentNode.insertBefore(n, checkedLine);',
        '      }',
        '      // Shared JS also upgrades pages generated before the explanation was added.',
        '      var old = hero ? hero.querySelectorAll(".ap-lead, .ap-out, .ap-explain") : [];',
        '      for (var i = 0; i < old.length; i++) { if (old[i] !== n) { old[i].hidden = true; } }',
        '      return n;',
        '    }',
        '    function setUnavailable() {',
        '      scaleHelp("stale");',
        '      if (heading) { heading.textContent = "Last known status"; }',
        '      var meaning = meaningElement(); if (meaning) { meaning.textContent = statusMeaning(null, "unknown", true); meaning.hidden = false; }',
        '      if (verdictEl) { verdictEl.textContent = "Last known status: FAA status unavailable."; }',
        '      if (checkedLine) { checkedLine.textContent = "FAA NAS status: not available right now."; }',
        '      if (statusChip) {',
        '        statusChip.className = "badge status-chip";',
        '        statusChip.textContent = "Status unavailable";',
        '      }',
        '      if (wxChip) { wxChip.hidden = true; }',
        '    }',
        '    function render(data) {',
        '      var updMin = ageMin(data && data.updated_utc);',
        '      var stale = isStale(updMin) || ((data && data.stale_feeds) || []).indexOf("FAA") >= 0;',
        '      showStale(data && data.updated_utc, stale);',
        '      if (heading) { heading.textContent = stale ? "Last known status" : (datelineText(data && data.updated_utc) || "Latest FAA check"); }',
        '      var a = data && data.airports && data.airports[CODE];',
        '      if (checkedLine && a) {',
        '        checkedLine.textContent = "";',
        '        var fp = faaParts(data.updated_utc, stale);',
        '        var cl = el("a", "tap", "FAA NAS status");',
        '        cl.href = "/sources";',
        '        checkedLine.appendChild(document.createTextNode(fp[0]));',
        '        checkedLine.appendChild(cl);',
        '        checkedLine.appendChild(document.createTextNode(fp[1]));',
        '      }',
        '      if (!a) {',
        '        setUnavailable();',
        '        box.textContent = "";',
        '        box.appendChild(el("p", null, "Airport status is not available right now. See nasstatus.faa.gov."));',
        '        return;',
        '      }',
        '      var lvl = effLevel(a, stale ? Date.parse(data.updated_utc) : null);',
        '      var meaning = meaningElement(); if (meaning) { meaning.textContent = statusMeaning(a, lvl, stale); meaning.hidden = false; }',
        '      var unknown = ["clear", "delay", "stop", "closed"].indexOf(a.level) < 0; if (unknown && heading) { heading.textContent = "Last known status"; } var label = unknown ? "Last known status: unavailable" : badgeLabel(a, lvl);',
        '      var asClock = clockLabel(data.updated_utc);',
        '      var chipText = stale ? "As of " + (asClock || "an unknown time") + ": " + label.charAt(0).toLowerCase() + label.slice(1) : label;',
        '      var badgeCls = stale || unknown ? "badge badge--stale" : BADGE_CLASS[lvl];',
        '      if (statusChip) {',
        '        statusChip.className = badgeCls + " status-chip";',
        '        statusChip.textContent = chipText;',
        '      }',
        '      var asOf = "as of " + (asClock || "an unknown time") + " (" + agoText(updMin) + ")";',
        '      if (verdictEl) { verdictEl.textContent = ""; verdictEl.appendChild(verdict(a, lvl, stale, label, asOf)); }',
        '      if (hero) { hero.className = hero.className.replace(/\\bap-hero--\\w+/, "ap-hero--" + (stale ? "stale" : lvl)); }',
        '      if (window.ATDHeroArt) { window.ATDHeroArt(stale ? "clear" : lvl); }',
        '      scaleHelp(stale ? "stale" : lvl);',
        '      var pulse = document.querySelector("#ap-now-title .pulse");',
        '      if (pulse) { pulse.className = "pulse pulse--" + (stale ? "stale" : lvl); }',
        '      var w = a.wx;',
        '      if (wxChip) {',
        '        if (w && w.now_text && !stale) {',
        '          var chipWx = "Weather: " + w.now_text;',
        '          if (w.wind_kt != null) { chipWx += ", wind " + windText(w, false); }',
        '          wxChip.textContent = chipWx;',
        '          wxChip.hidden = false;',
        '        } else {',
        '          wxChip.hidden = true;',
        '        }',
        '      }',
        '      box.textContent = "";',
        '      // AN34 round 3: the H1 is the one status block; a stale page names the last FAA reason under it.',
        '      var reasonEl = document.getElementById("ap-reason");',
        '      // The pre-rendered lead under the H1 explains the build-time state; when the state has changed since, drop it and name the reason here.',
        '      var leads = hero ? hero.querySelectorAll(".ap-out, .ap-explain, .ap-alt") : [];',
        '      var changed = (stale ? "stale" : lvl) !== INITIAL_LVL;',
        '      if (changed) { for (var li = 0; li < leads.length; li++) { leads[li].hidden = true; } }',
        '      var hasLead = !changed && leads.length > 0;',
        '      if (reasonEl) { reasonEl.textContent = a.reason && lvl !== "clear" && lvl !== "night" ? "Reason listed: " + reasonPlain(a.reason) + "." : ""; reasonEl.hidden = !reasonEl.textContent; }',
        '      if (w && w.now_text) {',
        '        var wxText = w.now_text + (w.temp_f != null ? ", " + Math.round(w.temp_f) + "\\u00b0F" : "");',
        '        if (w.wind_kt != null) { wxText += ", wind " + windText(w, true); }',
        '        var obsIso = w.obs_utc || data.updated_utc;',
        '        var wxStale = stale || isStale(ageMin(obsIso));',
        '        var wxAfter = wxStale',
        '          ? ", " + (clockLabel(w.obs_utc) ? "observed " + clockLabel(w.obs_utc) + ", " : "") + agoText(ageMin(obsIso))',
        '          : ", observed " + clockLabel(w.obs_utc) + ", " + ageLabel(obsIso, false);',
        '        box.appendChild(tile("fact--wx", wxStale ? WX_LABEL.stale : WX_LABEL.fresh, wxText, "aviationweather.gov METAR", wxAfter));',
        '      }',
        '      // AN35: the next 3 hours sit in the hero (above the fold), with the TAF source and its age. Same rule as _render_live.',
        '      var nx = document.getElementById("ap-next3");',
        '      if (nx) {',
        '        var label = "", taf = w && (w.taf_issue_utc || data.updated_utc);',
        '        if (w && w.next3h_text && outlookText(w)) {',
        '          if (!stale) { label = "Next 3 hours"; } else if (!forecastExpired(w.next3h_text, taf)) { label = "Forecast issued " + clockLabel(taf); }',
        '        }',
        '        nx.textContent = "";',
        '        if (label) {',
        '          nx.appendChild(el("span", "gl-k", label + ":")); nx.appendChild(document.createTextNode(" "));',
        '          nx.appendChild(el("span", "gl-v", outlookText(w))); nx.appendChild(document.createTextNode(" "));',
        '          var gs = el("span", "gl-src"), ga = el("a", "tap", "aviationweather.gov TAF"); ga.href = "/sources"; gs.appendChild(ga);',
        '          if (!stale && clockLabel(taf)) { gs.appendChild(document.createTextNode(", issued " + clockLabel(taf) + " (" + oldText(ageMin(taf)) + ")")); }',
        '          nx.appendChild(gs);',
        '        }',
        '        nx.hidden = !label;',
        '      }',
        '      var alerts = Array.isArray(a.alerts) ? a.alerts : [];',
        '      var foot = el("div", "fact-foot");',
        '      foot.appendChild(el("p", null, alerts.length ? "Alerts: " + alerts.join(", ") : "Alerts: none listed."));',
        '      foot.appendChild(srcLine("credit", "Sources: ", "FAA NAS status, aviationweather.gov METAR and TAF", "."));',
        '      box.appendChild(foot);',
        '    }',
        '    fetch("../data/airports.json?ts=" + Date.now(), { cache: "no-store" })',
        '      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })',
        "      .then(render)",
        "      .catch(function () {",
        "        if (box.getAttribute(\"data-prerendered\") === \"1\") { return; }",
        "        setUnavailable();",
        "        box.textContent = \"\";",
        '        box.appendChild(el("p", null, "Could not load live status right now. See nasstatus.faa.gov."));',
        "      });",
        "  })();",
        "  </script>",
    ])


def _render_place_ul(items: list[dict[str, Any]], extra_cls: str = "") -> str:
    cls = f"airport-places {extra_cls}".strip()
    lines = [f'          <ul class="{cls}">']
    for item in items:
        name = str(item.get("name") or "").strip()
        km = item.get("km")
        dist = f"{float(km) * 0.621371:.1f} mi" if km is not None else "Within 3.1 miles"
        website = _safe_http_url(item.get("website"))
        lines.append('            <li class="place-row">')
        lines.append(f'              <span class="place-name">{_esc(name)}</span>')
        lines.append(f'              <span class="place-dist-chip">{_esc(dist)}</span>')
        if website:
            lines.append(
                f'              <a class="tap place-link" href="{_esc(website)}" target="_blank" rel="noopener noreferrer">Website</a>'
            )
        lines.append("            </li>")
    lines.append("          </ul>")
    return "\n".join(lines)


def _render_place_list(items: list[dict[str, Any]], empty_text: str, show_all_label: str) -> str:
    valid = [item for item in items if isinstance(item, dict) and str(item.get("name") or "").strip()]
    if not valid:
        return f'          <p class="places-empty">{_esc(empty_text)}</p>'
    head = valid[:5]
    rest = valid[5:]
    parts = [_render_place_ul(head)]
    if rest:
        parts.append('          <details class="places-more">')
        parts.append(f'            <summary class="tap places-more-summary">Show all {len(valid)} {_esc(show_all_label)}</summary>')
        parts.append(_render_place_ul(rest, "airport-places--more"))
        parts.append("          </details>")
    return "\n".join(parts)


def _bts_comparison_text(ontime: Any, ly_ontime: Any, ly_month: str) -> str:
    """Compute exact point difference vs last year's month from bts.json values."""
    if ly_ontime is None or not ly_month:
        return ""
    diff = round(float(ontime) - float(ly_ontime))
    if diff == 0:
        return f"About the same as {ly_month}"
    pts = str(abs(diff))
    unit = "point" if pts == "1" else "points"
    direction = "better" if diff > 0 else "worse"
    return f"{pts} {unit} {direction} than {ly_month}"


def render_airport_page(
    code: str,
    *,
    guide_entry: dict[str, Any],
    guide_checked_date: str,
    airport_info: dict[str, Any],
    places_entry: dict[str, Any] | None,
    places_fetched_date: str,
    bts_data: dict[str, Any],
    build_date: str,
    live_entry: dict[str, Any] | None = None,
    live_updated_utc: str = "",
    now: Any = None,
    history: dict[str, Any] | None = None,
    alternates: list[tuple[str, str, int, str]] | None = None,
    security_entry: dict[str, Any] | None = None,
    airlines: list[dict[str, Any]] | None = None,
    an43_profile: dict[str, Any] | None = None,
) -> str:
    """Render HTML for a single airport page.

    live_entry is this airport's record from data/airports.json; with it the page holds the live status,
    the weather and a timestamp as text (no JavaScript needed). Without it the page holds fallback text.
    """
    now = now or pt.now_utc()
    guide_checked_date = str(guide_entry.get("checked") or guide_checked_date or "")
    has_places = places_entry is not None
    name = str(airport_info.get("name") or code)
    city = str(airport_info.get("city") or "")
    tz = str(airport_info.get("tz") or "")
    operator = str(guide_entry.get("operator") or "")

    live = _render_live(code, tz, live_entry, live_updated_utc, now)
    prerendered_attr = ' data-prerendered="1"' if live["has"] else ""
    title = f"{code} airport status: is {code} delayed? Live FAA status"
    if live["has"] and live["stale"]:
        description = (
            f"{name} ({code}) {live['as_of']}: {live['word']}. "
            "Source: FAA NAS status. Official links and delay help."
        )
    elif live["has"]:
        wx_part = f" Weather: {live['wx']}." if live["wx"] else ""
        clock_part = f" Checked {live['clock']}." if live["clock"] else ""
        description = (
            f"{name} ({code}) right now: {live['word']}.{wx_part}{clock_part} "
            "Source: FAA NAS status. Official links and delay help."
        )
    else:
        description = (
            f"Live FAA delay status, airport weather, official {code} operator links, "
            + ("nearby hotels and car rental, " if has_places else "")
            + f"and delay help for {name} ({code})."
        )
    canonical = f"{SITE_URL}/airports/{code}"
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Air Travel Desk", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Airports", "item": f"{SITE_URL}/airports/"},
            {"@type": "ListItem", "position": 3, "name": f"{name} ({code})", "item": canonical},
        ],
    }

    bts_airports = bts_data.get("airports") or {}
    bts_entry = bts_airports.get(code)
    bts_month = str(bts_data.get("month_label") or "")
    bts_ly_month = str(bts_data.get("ly_month_label") or "")
    has_bts = bool(isinstance(bts_entry, dict) and bts_entry.get("ontime") is not None and bts_month)

    glance_rows: list[tuple[str, str]] = []
    if city:
        glance_rows.append(("City", city))
    if tz:
        glance_rows.append(("Time zone", _zone_name(tz)))
    if operator:
        glance_rows.append(("Operator", operator))

    glance_facts = ['          <dl class="glance-list">']
    for label, val in glance_rows:
        glance_facts.append('            <div class="glance-row">')
        glance_facts.append(f"              <dt>{_esc(label)}</dt>")
        glance_facts.append(f"              <dd>{_esc(val)}</dd>")
        glance_facts.append("            </div>")
    glance_facts.append("          </dl>")

    if has_bts:
        comp_text = _bts_comparison_text(bts_entry["ontime"], bts_entry.get("ly_ontime"), bts_ly_month)
        ontime_lines = [
            '          <div class="glance-ontime">',
            '            <h3 class="fact-k">On-time record</h3>',
            f'            <p class="glance-ontime-num">{_esc(round(float(bts_entry["ontime"])))}%</p>',
            f'            <p class="glance-ontime-label">On-time arrivals, {_esc(bts_month)}, BTS</p>',
        ]
        if comp_text:
            ontime_lines.append(f'            <p class="glance-ontime-comp">{_esc(comp_text)}</p>')
        if bts_entry.get("flights") is not None:
            ontime_lines.append(
                f'            <p class="glance-ontime-flights">{int(bts_entry["flights"]):,} flights counted</p>'
            )
        ontime_lines.append(
            f'            <p class="small">{BTS_DEFINITION_SHORT}; source BTS, {_esc(bts_month)}.</p>'
        )
        ontime_lines.append("          </div>")
        ontime_html = ['        <div class="today-cell ap-ontime" aria-label="On-time arrivals">', *ontime_lines, "        </div>"]
    else:
        ontime_html = []
    if glance_rows:
        glance_html = [
            '        <details class="glance-details">',
            "          <summary>Airport facts</summary>",
            *glance_facts,
            "        </details>",
        ]
    else:
        glance_html = []

    # "Sun now": filled in by the browser (sun.js). Hidden and empty when JavaScript is off.
    sun_now_html: list[str] = []
    try:
        sun_lat = float(airport_info.get("lat"))
        sun_lon = float(airport_info.get("lon"))
    except (TypeError, ValueError):
        sun_lat = sun_lon = None
    if tz and sun_lat is not None and sun_lon is not None:
        sun_now_html = [
            '        <div id="sun-tile" class="fact fact--sun" hidden>',
            '          <p class="fact-k">Daylight</p>',
            f'          <p id="sun-now" class="sun-now" data-lat="{sun_lat}" data-lon="{sun_lon}" data-tz="{_esc(tz)}" hidden></p>',
            '          <p id="sun-now-source" class="small" hidden>Sun times calculated for the airport\'s location.</p>',
            "        </div>",
        ]

    # Official pages from airport-guide.json
    guide_links = [
        item for item in (guide_entry.get("links") or [])
        if isinstance(item, dict) and _safe_http_url(item.get("url"))
    ]
    # AN34: official pages as an icon grid; the "could not verify" note lives with the sources below.
    official_lines = ['        <ul class="guide-pills">']
    for item in guide_links:
        url = _safe_http_url(item.get("url"))
        label = str(item.get("label") or "Airport website").strip()
        official_lines.append('          <li class="guide-pill-item">')
        official_lines.append(
            f'            <a class="tap guide-pill" href="{_esc(url)}" target="_blank" rel="noopener noreferrer">'
            f'{icon(_link_icon(label))}{_esc(label)}</a>'
        )
        official_lines.append("          </li>")
    official_lines.append("        </ul>")
    sec = security_entry if isinstance(security_entry, dict) else {}
    sec_url = _safe_http_url(sec.get("url"))
    if sec_url:
        # AN34 r2: the security line link (we show no wait numbers; the airport's own page may).
        sec_label = "Security wait times" if sec.get("verified") and sec_url.rstrip("/") not in {_safe_http_url(i.get("url")).rstrip("/") for i in guide_links} else "Security lines"
        official_lines.insert(1, '          <li class="guide-pill-item">')
        official_lines.insert(2, f'            <a class="tap guide-pill" href="{_esc(sec_url)}" target="_blank" rel="noopener noreferrer">'
                                 f'{icon("clock")}{_esc(sec_label)}</a>')
        official_lines.insert(3, "          </li>")
    has_blocked_links = any(item.get("verified") is False for item in guide_links)
    if not guide_links:
        official_lines.append(f'        <p class="small">We do not list an official link for {_esc(code)} yet.</p>')
    elif guide_entry.get("origin") == "ourairports":
        official_lines.append(
            f'        <p class="small">Only the airport\'s own website is listed for {_esc(code)}. '
            'The address comes from OurAirports (public domain).</p>'
        )
    elif len(guide_links) < 4:
        official_lines.append(
            f'        <p class="small">Fewer than 4 official links were available for {_esc(code)} when checked on {_esc(guide_checked_date or build_date)}.</p>'
        )
    elif operator:
        hosts = sorted({urllib.parse.urlsplit(_safe_http_url(i.get("url"))).netloc.removeprefix("www.") for i in guide_links} - {""})
        where = f" Every link goes to {hosts[0]}." if len(hosts) == 1 else ""
        official_lines.append(f'        <p class="small">Official pages from {_esc(operator)}.{_esc(where)}</p>')

    # Places within 3.1 miles
    hotels = list((places_entry or {}).get("hotels") or [])
    cars = list((places_entry or {}).get("cars") or [])
    places_credit_date = places_fetched_date or "unknown date"

    # Sources section
    op_label = f"{operator}'s website" if operator else "The airport operator's website"
    source_items = [
        f"FAA NAS status: {'' if live['stale'] else 'live '}airport delays, ground delays, ground stops and closures.",
        f"aviationweather.gov: {'' if live['stale'] else 'live '}airport weather observations (METAR) and 3-hour forecasts (TAF).",
    ]
    if has_bts:
        source_items.append(f"BTS ({bts_month}): monthly on-time arrival rate and flight count.")
    elif bts_month:
        source_items.append(f"BTS ({bts_month}): monthly on-time arrival data (no entry for {code}).")
    if an43_profile and code in (an43_profile.get("airports") or {}):
        source_items.append(f"BTS ({_esc(an43_profile.get('period', ''))}): 12-month departure, cancellation, delay-cause, airline and route figures in \"How flights at {_esc(code)} usually run\".")
    if has_places:
        source_items.append(
            f"OpenStreetMap (&copy; OpenStreetMap contributors): hotels and car rental within 3.1 miles, fetched {places_credit_date}."
        )
    if guide_entry.get("origin") == "ourairports":
        source_items.append("OurAirports (public domain): the address of the airport's website.")
    source_items.append("Our hourly copy of the FAA feed: the last 3 days. Sun times are calculated for the airport's location.")
    if has_blocked_links:
        source_items.append(f"{_esc(op_label)}: {_esc(LINKS_NOT_ALL_CHECKED)} {_esc(NOTE_BLOCKED_LINKS)}")
    else:
        source_items.append(
            f"{_esc(op_label)}: {_esc(LINKS_ALL_CHECKED.format(date=guide_checked_date or build_date))}"
        )

    places_html: list[str] = []
    if has_places:
        n_h = len([h for h in hotels if isinstance(h, dict) and str(h.get("name") or "").strip()])
        n_c = len([c for c in cars if isinstance(c, dict) and str(c.get("name") or "").strip()])
        places_html = [
            '      <section class="airport-section" aria-labelledby="places-heading">',
            '        <details class="more">',
            f'          <summary>{icon("bed")}<h2 id="places-heading">Hotels and car rental within 3.1 miles</h2>'
            f'<span class="cnt">{n_h} {"hotel" if n_h == 1 else "hotels"} · {n_c} rental {"desk" if n_c == 1 else "desks"}</span></summary>',
            '        <div class="places-columns">',
            '          <div class="places-col">',
            "            <h3>Hotels</h3>",
            _render_place_list(hotels, "No hotels with a name are listed in OpenStreetMap within 3.1 miles.", "hotels"),
            "          </div>",
            '          <div class="places-col">',
            "            <h3>Car rental</h3>",
            _render_place_list(cars, "No car rental places are listed in OpenStreetMap within 3.1 miles.", "car rental places"),
            "          </div>",
            "        </div>",
            (
                f'        <p class="credit">&copy; OpenStreetMap contributors. Data from {_esc(places_credit_date)}. '
                "Distances are in a straight line. We show no prices and do not know what is available.</p>"
            ),
            "        </details>",
            "      </section>",
        ]

    lvl = live.get("level", "none")
    short = str((live_entry or {}).get("short") or desk_airports.SHORT.get(code) or city.split(",")[0] or code)
    try:
        map_lat = float(airport_info.get("lat"))
        map_lon = float(airport_info.get("lon"))
        regional = [
            f'      <figure class="ap-map" id="ap-map" data-code="{_esc(code)}" data-lat="{map_lat}" data-lon="{map_lon}" hidden>',
            f'        <canvas id="ap-map-canvas" role="img" aria-label="Map of the area around {_esc(code)} with radar and the status of nearby airports"></canvas>',
            '        <figcaption id="ap-map-cap">Radar: NOAA MRMS. Status: FAA. Tap an airport to open it.</figcaption>',
            "      </figure>",
        ]
    except (TypeError, ValueError):
        regional = []

    parts = [
        _render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb,
                     preload=hero_preload(airport_type(code), lvl, _hero_is_day(airport_info, now))),
        f'<body class="page-airport">',
        _render_header(),
        f'    <main id="main-content" class="airport-main">',
        f'      <p class="crumb"><a href="/airports/">All airports</a> <span aria-hidden="true">/</span> {_esc(code)}</p>',
        (
            f'      <p id="stale-notice" class="stale-notice" role="status">{live["stale_html"]}</p>'
            if live["has"] and live["stale"]
            else '      <p id="stale-notice" class="stale-notice" role="status" hidden></p>'
        ),
        f'      <section id="ap-hero" class="ap-hero band ap-hero--{_esc(lvl)}" aria-labelledby="ap-verdict">',
        *_hero_art(airport_type(code), lvl, _hero_is_day(airport_info, now)),
        '       <div class="ap-hero-main">',
        f'        <p id="ap-now-title" class="dateline ap-eyebrow"><span id="ap-now-word">{"Last known status" if live["stale"] or not live["has"] or (live_entry or {}).get("level") not in ("clear", "delay", "stop", "closed") else _esc(pt.airport_dateline(live_updated_utc, tz, short) or "Latest FAA check")}</span></p>',
        '        <div class="lockup">',
        f'          <span class="big-code" aria-hidden="true">{_esc(code)}</span>',
        f'          <p class="ap-name"><strong>{_esc(name)} ({_esc(code)})</strong><span>{_esc(city)}</span></p>',
        "        </div>",
        f'        <h1 id="ap-verdict" class="airport-page-title ap-verdict">{_verdict(live_entry, name, short, live, now, tz)}</h1>',
        '        <p class="small">No FAA program does not guarantee your flight is on time: check your airline.</p>',
        *_lead(live_entry, short, code, live, now),
        (
            f'        <p id="checked-line" class="last-checked">{_esc(live["checked_pre"])}{_src_link("FAA NAS status")}{_esc(live["checked_post"])}</p>'
            if live["has"]
            else f'        <p id="checked-line" class="last-checked">{_esc(live["checked"])}</p>'
        ),
        (
            f'        <p id="ap-reason" class="ap-reason">Reason listed: {_esc(pt.reason_plain(live_entry["reason"]))}.</p>'
            if live["has"] and (live_entry or {}).get("reason") and pt.effective_level(live_entry, now) not in ("clear", "night")
            else '        <p id="ap-reason" class="ap-reason" hidden></p>'
        ),
        '        <div class="airport-summary-chips">',
        f'          <span id="status-chip" class="{live["chip_class"]}" aria-live="polite">{_esc(live["chip"])}</span>',
        (
            f'          <span id="weather-chip" class="badge weather-chip">{_esc(live["wx_chip"])}</span>'
            if live["wx_chip"]
            else '          <span id="weather-chip" class="badge weather-chip" hidden></span>'
        ),
        "        </div>",
        *_render_glance(code, _tsa_wait(security_entry, now), live, now),
        (
            '        <p class="ap-alt">Other airports nearby, straight-line miles: '
            + ", ".join(f'<a class="tap" href="/airports/{_esc(c)}">{_esc(c)}</a> ({m} mi{", " + w if w else ""})' for c, _n, m, w in (alternates or []))
            + ". Status is from the FAA feed, checked as shown above. We know nothing about fares or seats there; ask your airline what it can rebook.</p>"
            if alternates and live["has"] and not live["stale"] and "badge--stop" in live["chip_class"]
            else ""
        ),
        *_actions(code, airlines, _safe_http_url((guide_links[0] if guide_links else {}).get("url")), lvl),
        "       </div>",
        *regional,
        "      </section>",
        # AN35: official, security and parking links sit right under the status block.
        '      <section class="airport-section ap-official" aria-labelledby="official-heading">',
        '        <h2 id="official-heading">Official pages: airport, security, parking</h2>',
        *official_lines,
        "      </section>",
        '      <section class="airport-section ap-now ap-today" aria-labelledby="right-now-heading">',
        f'        <h2 id="right-now-heading">Today at {_esc(code)}</h2>',
        '        <div class="today-grid">',
        '        <div class="facts">',
        f'        <div id="right-now" class="right-now-box" data-code="{_esc(code)}"{prerendered_attr}>',
        *live["box"],
        "        </div>",
        *sun_now_html,
        "        </div>",
        *(['        <div class="today-record">', *_render_history(code, tz, history), *ontime_html, "        </div>"]
          if (_render_history(code, tz, history) or ontime_html) else []),
        "        </div>",
        "        <noscript>",
        f'          <p class="noscript-note">{"Refreshing" if live["stale"] else "Live refresh"} needs JavaScript. The status above is from the last site build; for the FAA\'s own page, see nasstatus.faa.gov.</p>',
        "        </noscript>",
        "      </section>",
        '    <div class="ap-cols">',
        *_help_card(code, lvl),
        "    </div>",
        *an43_context.render_context(code, short, an43_profile, city),
        '    <div class="ap-folds">',
        *places_html,
        '      <section class="airport-section" aria-labelledby="sources-heading">',
        '        <details class="more">',
        f'          <summary>{icon("clock")}<h2 id="sources-heading">Where this page\'s data comes from</h2><span class="cnt">every source and its age</span></summary>',
        '        <ul class="airport-sources">',
        *[f"          <li>{line}</li>" for line in source_items],
        "        </ul>",
        "        </details>",
        "      </section>",
        '      <section class="airport-section airport-about-note" aria-labelledby="about-page-heading">',
        '        <h2 id="about-page-heading">About this page</h2>',
        '        <p class="small">This traveler page is independent and not affiliated with the airport, the FAA or any airline. Data sources and dates are listed above. Read <a class="tap" href="/about">About Air Travel Desk</a> for how these pages are made.</p>',
        *glance_html,
        "      </section>",
        "    </div>",
        "    </main>",
        _render_footer(),
        '  <script src="../sun.js" type="text/atd-late"></script>' if tz else "",
        _airport_js_tag(code, tz, short, airport_type(code), airport_info.get("lat") if tz else None, airport_info.get("lon") if tz else None),
        '  <script src="../apmap.js" type="text/atd-late"></script>' if regional else "",
        LATE_LOADER,
        '<script src="/count.js" defer></script>',
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MO": "Missouri",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WI": "Wisconsin",
}


def _state_of(city: str) -> str:
    """Two-letter state from a 'City, ST' label; '' when there is none."""
    tail = city.rsplit(",", 1)[-1].strip() if "," in city else ""
    return tail if tail in STATE_NAMES else ""


def render_index_page(
    codes: list[str],
    *,
    guide_checked_date: str,
    airports_map: dict[str, Any],
    places_fetched_date: str,
    bts_data: dict[str, Any],
    build_date: str,
    live_cards: dict[str, Any] | None = None,
    live_updated_utc: str = "",
    now: Any = None,
) -> str:
    """Render HTML for airports/index.html: all airports, grouped by state. The list is static HTML; a small
    script only filters it as you type. Each card shows the FAA word at build time (the site rebuilds every 5 minutes)."""
    n = len(codes)
    title = f"US airport status: {n} busiest airports, live delays"
    description = (
        f"Directory of the {n} busiest US airports on Air Travel Desk with city, "
        "monthly BTS on-time arrival rate, live status links and traveler guides."
    )
    canonical = f"{SITE_URL}/airports/"
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Air Travel Desk", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Airports", "item": canonical},
        ],
    }

    bts_airports = bts_data.get("airports") or {}
    bts_month = str(bts_data.get("month_label") or "")

    groups: dict[str, list[str]] = {}
    for code in codes:
        info = airports_map.get(code) or {}
        groups.setdefault(_state_of(str(info.get("city") or "")), []).append(code)
    states = sorted((st for st in groups if st), key=lambda st: STATE_NAMES[st])
    if "" in groups:
        states.append("")

    def group_id(st: str) -> str:
        return f"state-{st.lower()}" if st else "state-other"

    jump = ['        <nav class="airport-jump" aria-label="Jump to a state">', "          <p class=\"small\">Jump to: " + " ".join(
        f'<a class="tap" href="#{group_id(st)}">{_esc(st or "Other")}</a>' for st in states) + "</p>", "        </nav>"]
    live_cards = live_cards or {}
    now = now or pt.now_utc()
    live_age = pt.age_minutes(live_updated_utc, now) if live_updated_utc else None
    live_ok = bool(live_cards) and not pt.is_stale(live_age) and not any(c.get("_feed_stale") for c in live_cards.values() if isinstance(c, dict))
    trouble = []
    for code in codes:
        card = live_cards.get(code)
        if live_ok and isinstance(card, dict) and pt.effective_level(card, now) != "clear":
            trouble.append(code)

    sections: list[str] = []
    for st in states:
        sections.append(f'        <h3 id="{group_id(st)}" class="airport-index-state">{_esc(STATE_NAMES.get(st, "Other"))}</h3>')
        sections.append('        <ul class="airport-index-list">')
        for code in sorted(groups[st], key=lambda c: codes.index(c)):
            info = airports_map.get(code) or {}
            name = str(info.get("name") or code)
            city = str(info.get("city") or "")
            b = bts_airports.get(code)
            if isinstance(b, dict) and b.get("ontime") is not None and bts_month:
                rate_line = f"{round(float(b['ontime']))}% on time in {bts_month}"
            else:
                rate_line = ""      # no BTS number for this airport: show nothing instead of 'unavailable' on every card
            card = live_cards.get(code)
            lv = pt.effective_level(card, now) if live_ok and isinstance(card, dict) else "none"
            word = {"clear": "No FAA program listed", "delay": "Delays", "stop": "Ground stop", "closed": "Closed", "night": "Closed overnight"}.get(lv, "")
            hay = " ".join([code, name, city, STATE_NAMES.get(st, "")]).lower()
            sections.append(f'          <li class="airport-index-card idx--{lv}" data-q="{_esc(hay)}">')
            sections.append(
                f'            <a class="tap airport-index-link" href="/airports/{_esc(code)}"><span class="idx-code">{_esc(code)}</span>'
                f'<span class="idx-name">{_esc(name)} ({_esc(code)})</span></a>'
            )
            meta = " · ".join(x for x in (city, rate_line) if x)
            sections.append(
                '            <p class="idx-status">'
                + (f'<span class="dot dot--{lv}"></span><b>{_esc(word)}</b>' if word else "")
                + (f'<span class="airport-index-meta">{_esc(meta)}</span>' if meta else "")
                + "</p>"
            )
            sections.append("          </li>")
        sections.append("        </ul>")

    source_items = [
        "FAA NAS status and aviationweather.gov: live delays and weather on each airport page.",
        f"BTS ({bts_month or 'monthly'}): monthly on-time arrival rate where available.",
        f"OpenStreetMap (&copy; OpenStreetMap contributors): nearby hotels and car rental where we have them, fetched {places_fetched_date or 'unknown date'}.",
        "Airport operators' own websites: official airport links. Some sites block automatic checks, so not every link is verified by script.",
        "OurAirports (public domain): the website address for airports outside the first 30.",
    ]

    parts = [
        _render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        '<body class="page-index">',
        _render_header(),
        '    <main id="main-content" class="airport-main">',
        '      <div class="idx-hero">',
        '      <h1 class="idx-title">US Airports: delays, weather and traveler help</h1>',
        f'      <p class="airport-purpose">Each of the {n} busiest US airports has its own page: live FAA status, weather, the last 3 days, '
        'official links and help if you are stuck. The <a href="/">live board</a> has the national picture.</p>',
        (
            f'      <p class="idx-now"><span class="dot dot--{"delay" if trouble else "clear"}"></span>'
            + (f'FAA programs at {len(trouble)} of {n} now: ' + ", ".join(f'<a href="/airports/{_esc(c)}">{_esc(c)}</a>' for c in trouble)
               if trouble else f"No FAA programs at any of the {n} now")
            + f'. FAA NAS status, {_esc(pt.checked_text(live_updated_utc, "America/New_York", now))}.</p>'
            if live_ok else ""
        ),
        '      <div class="search idx-search"><label for="idx-filter">Find an airport</label>'
        '<div class="field">' + icon("search") + '<input id="idx-filter" type="search" autocomplete="off" spellcheck="false" placeholder="Code, city or state"></div>'
        '<p id="idx-none" class="search-empty" hidden>No match among the 100 busiest airports.</p></div>',
        "      </div>",
        '      <section class="airport-section" aria-labelledby="directory-heading">',
        f'        <h2 id="directory-heading">{n} busiest US airports, by state</h2>',
        *jump,
        *sections,
        "      </section>",
        '      <section class="airport-section" aria-labelledby="sources-heading">',
        '        <h2 id="sources-heading">Where this page\'s data comes from</h2>',
        '        <ul class="airport-sources">',
        *[f"          <li>{line}</li>" for line in source_items],
        "        </ul>",
        f'        <p class="last-checked">Page built {_esc(build_date)}.</p>',
        "      </section>",
        "    </main>",
        _render_footer(),
        "  <script>",
        "  (function () {",
        '    var f = document.getElementById("idx-filter"), none = document.getElementById("idx-none");',
        "    if (!f) { return; }",
        '    var cards = [].slice.call(document.querySelectorAll(".airport-index-card")), heads = [].slice.call(document.querySelectorAll(".airport-index-state"));',
        '    f.addEventListener("input", function () {',
        '      var q = f.value.trim().toLowerCase(), shown = 0;',
        '      cards.forEach(function (c) { var hit = !q || c.getAttribute("data-q").indexOf(q) >= 0; c.hidden = !hit; if (hit) { shown++; } });',
        '      heads.forEach(function (h) { var ul = h.nextElementSibling; h.hidden = !!q && !(ul && ul.querySelector(".airport-index-card:not([hidden])")); if (ul) { ul.hidden = h.hidden; } });',
        "      none.hidden = shown > 0;",
        "    });",
        "  })();",
        "  </script>",
        '<script src="/count.js" defer></script>',
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def render_sitemap_block(codes: list[str], build_date: str) -> str:
    """Render the managed <!-- airports:begin --> ... <!-- airports:end --> sitemap block."""
    urls = [f"{SITE_URL}/airports/"] + [f"{SITE_URL}/airports/{code}" for code in codes]
    lines = [f"  {SITEMAP_BEGIN}"]
    for url in urls:
        lines.append(f"  <url><loc>{_esc(url)}</loc><lastmod>{_esc(build_date)}</lastmod></url>")
    lines.append(f"  {SITEMAP_END}")
    return "\n".join(lines)


def update_sitemap_block(sitemap_path: Path, block: str, begin: str, end: str) -> None:
    """Insert or replace one managed <!-- x:begin --> ... <!-- x:end --> block in sitemap.xml."""
    if sitemap_path.is_file():
        content = sitemap_path.read_text(encoding="utf-8")
    else:
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "</urlset>\n"
        )

    pattern = re.compile(
        r"[ \t]*" + re.escape(begin) + r".*?" + re.escape(end),
        re.DOTALL,
    )
    if pattern.search(content):
        updated = pattern.sub(lambda _m: block, content, count=1)
    elif "</urlset>" in content:
        updated = content.replace("</urlset>", f"{block}\n</urlset>", 1)
    else:
        updated = content.rstrip() + "\n" + block + "\n"
    sitemap_path.write_text(updated, encoding="utf-8")


def update_sitemap(sitemap_path: Path, codes: list[str], build_date: str) -> None:
    """Insert or replace the airports sitemap block in sitemap.xml."""
    update_sitemap_block(sitemap_path, render_sitemap_block(codes, build_date), SITEMAP_BEGIN, SITEMAP_END)


def build_pages(
    *,
    data_dir: Path,
    out_dir: Path,
    sitemap_path: Path | None = None,
    build_date: str | None = None,
    now: Any = None,
) -> list[Path]:
    """Generate the pages for the 100 busiest airports and airports/index.html, and optionally update sitemap.xml."""
    now = now or pt.now_utc()
    date_str = build_date or now.strftime("%Y-%m-%d")

    guide_data = _load_json(data_dir / "airport-guide.json")
    links_data = _load_json(data_dir / "airports-links.json")
    airports_data = _load_json(data_dir / "airports.json")
    places_data = _load_json(data_dir / "places.json")
    bts_data = _load_json(data_dir / "bts.json")
    history_data = _load_json(data_dir / "history-summary.json")
    an43_path = data_dir / "an43" / "bts-profile.json"
    an43_profile = _load_json(an43_path) if an43_path.exists() else None

    live_updated = str(airports_data.get("updated_utc") or "")
    guide_airports = dict(guide_data.get("airports") or {})
    if not guide_airports:
        raise ValueError(f"No airports found in {data_dir / 'airport-guide.json'}")
    links_checked = str(links_data.get("checked_utc") or "")[:10]
    for code, item in (links_data.get("airports") or {}).items():
        url = _safe_http_url((item or {}).get("home_link"))
        if code in guide_airports or not url:
            continue
        checked = str((item or {}).get("checked") or links_checked)[:10]
        guide_airports[code] = {
            "operator": "",
            "origin": "ourairports",
            "checked": checked if (item or {}).get("verified") else "",
            "links": [{"label": "Airport website", "url": url, "verified": bool((item or {}).get("verified"))}],
        }

    # Static facts come from desk/airports.py; the live data file adds the live parts.
    airports_map: dict[str, Any] = {}
    live_cards = airports_data.get("airports") or {}
    if "FAA" in airports_data.get("stale_feeds", []):
        for card in live_cards.values():
            if isinstance(card, dict):
                card["_feed_stale"] = True
    for code in desk_airports.BUSIEST_100:
        _, lat, lon = desk_airports.AIRPORTS[code]
        info = {
            "code": code, "name": desk_airports.display(code), "city": desk_airports.CITY.get(code, ""),
            "tz": desk_airports.TZ.get(code, ""), "lat": lat, "lon": lon,
        }
        card = live_cards.get(code)
        if isinstance(card, dict):
            info.update({k: v for k, v in card.items() if v not in (None, "") and k in ("name", "city", "tz", "lat", "lon")})
        airports_map[code] = info
    places_airports = dict(places_data.get("airports") or {})
    # The other 70 airports have their own places file, filled in small batches. A missing entry means no list on the page.
    more = _load_json(data_dir / "places-more.json")
    places_dates: dict[str, str] = {}
    for code, entry in (more.get("airports") or {}).items():
        if code not in places_airports and isinstance(entry, dict):
            places_airports[code] = entry
            places_dates[code] = str(entry.get("fetched_utc") or "")[:10]
    guide_checked_date = str(guide_data.get("checked_utc") or "")[:10]
    security_data = _load_json(data_dir / "security-waits.json")
    airlines_list = [a for a in (_load_json(data_dir / "dot-commitments.json").get("airlines") or []) if isinstance(a, dict)]
    places_fetched_date = str(places_data.get("fetched_utc") or "")[:10]

    # Pages for the 100 busiest airports, in rank order. An airport with no link entry still gets a page.
    codes = list(desk_airports.BUSIEST_100)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    (out_dir.parent / AIRPORT_JS_NAME).write_text(airport_js(), encoding="utf-8")   # AN43: shared script for every airport page
    for code in codes:
        live_card = live_cards.get(code)
        page_html = render_airport_page(
            code,
            guide_entry=guide_airports.get(code) or {},
            guide_checked_date=guide_checked_date,
            airport_info=airports_map[code],
            places_entry=places_airports.get(code),
            places_fetched_date=places_dates.get(code) or places_fetched_date,
            bts_data=bts_data,
            build_date=date_str,
            live_entry=live_card if isinstance(live_card, dict) else None,
            live_updated_utc=live_updated,
            now=now,
            history=history_data,
            alternates=_nearby(code, airports_map, live_cards),
            security_entry=security_data.get(code),
            airlines=airlines_list,
            an43_profile=an43_profile,
        )
        dest = out_dir / f"{code}.html"
        dest.write_text(page_html, encoding="utf-8")
        written.append(dest)

    index_html = render_index_page(
        codes,
        guide_checked_date=guide_checked_date,
        airports_map=airports_map,
        places_fetched_date=places_fetched_date,
        bts_data=bts_data,
        build_date=date_str,
        live_cards=live_cards,
        live_updated_utc=live_updated,
        now=now,
    )
    index_dest = out_dir / "index.html"
    index_dest.write_text(index_html, encoding="utf-8")
    written.append(index_dest)

    if sitemap_path is not None:
        update_sitemap(sitemap_path, codes, date_str)

    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build static airport pages and update sitemap.xml.")
    ap.add_argument("--data", default=str(ROOT / "data"), help="Directory containing data/*.json")
    ap.add_argument("--out", default=None, help="Output directory for airport HTML pages (default: airports/)")
    ap.add_argument("--sitemap", default=None, help="Path to sitemap.xml (default: sitemap.xml when --out is default)")
    ap.add_argument("--date", default=None, help="Override UTC build date (YYYY-MM-DD)")
    ap.add_argument("--now", default=None, help="Override the build time (ISO UTC) used for 'N min ago' text")
    args = ap.parse_args(argv)

    data_dir = Path(args.data)
    default_out = ROOT / "airports"
    out_dir = Path(args.out) if args.out is not None else default_out

    if args.sitemap is not None:
        sitemap_path: Path | None = Path(args.sitemap) if args.sitemap else None
    elif args.out is None:
        sitemap_path = ROOT / "sitemap.xml"
    else:
        sitemap_path = None

    written = build_pages(
        data_dir=data_dir,
        out_dir=out_dir,
        sitemap_path=sitemap_path,
        build_date=args.date,
        now=pt.parse_utc(args.now) if args.now else None,
    )
    print(f"build_airport_pages: wrote {len(written)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
