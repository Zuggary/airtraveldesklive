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
from pathlib import Path
from typing import Any

try:
    from tools import prerender_text as pt
except ImportError:  # run as a script: tools/ is on the path
    import prerender_text as pt  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from desk import airports as desk_airports  # noqa: E402

SITE_URL = "https://www.airtraveldesklive.com"
DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive"
CONTACT_EMAIL = "hello@airtraveldesklive.com"
BTS_DEFINITION_SHORT = "BTS counts a flight on time if it arrives less than 15 minutes late"

ILLUS_DIR = ROOT / "assets" / "illustrations"

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


def pick_hero_illustration(code: str, library: dict[str, Any]) -> dict[str, Any] | None:
    """Choose a 'meaning' image of the airport's type from library.json, or None when there is none."""
    kind = airport_type(code)
    pool = sorted(
        (i for i in library.get("images") or []
         if i.get("category") == f"airport-{kind}" and i.get("role") == "meaning"),
        key=lambda i: i.get("file", ""),
    )
    return pool[_stable_index(code, len(pool))] if pool else None


def _render_hero_illustration(code: str) -> list[str]:
    """Hero figure for an airport page. A missing library or image gives no figure."""
    library = _load_json(ILLUS_DIR / "library.json")
    img = pick_hero_illustration(code, library)
    if not img or not (ILLUS_DIR / img["file"]).is_file():
        return []
    kind = airport_type(code)
    return [
        '      <div class="illus-card">',
        '      <figure class="illus illus--hero">',
        f'        <img src="../assets/illustrations/{_esc(img["file"])}" alt="{_esc(img["alt"])}" '
        f'width="{int(library.get("width", 1280))}" height="{int(library.get("height", 720))}" loading="lazy" decoding="async">',
        '        <figcaption class="illus-tag">Illustration</figcaption>',
        "      </figure>",
        f'      <p class="illus-caption">Illustration of a {kind} airport. It does not show {_esc(code)}.</p>',
        "      </div>",
    ]


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


def _src_link(text: str) -> str:
    return f'<a class="tap" href="../sources.html">{_esc(text)}</a>'


def _render_live(
    code: str,
    tz: str,
    entry: dict[str, Any] | None,
    updated_utc: str,
    now: Any,
) -> dict[str, Any]:
    """Pre-rendered live text for one airport page, from data/airports.json values only.

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
            "box": [f'          <p class="updated-text">{_esc(pt.FALLBACK_STATUS)}</p>'],
            "word": "",
            "wx": "",
            "clock": "",
        }
    lvl = pt.effective_level(entry)
    word = pt.status_word(entry)
    wx = entry.get("wx") if isinstance(entry.get("wx"), dict) else {}
    clock = pt.clock_label(updated_utc, tz)
    age = pt.age_minutes(updated_utc, now)
    stale = pt.is_stale(age)
    checked = f"FAA NAS status, {pt.checked_text(updated_utc, tz, now, last=stale)}."
    chip_wx = ""
    if wx.get("now_text") and not stale:
        chip_wx = f"Weather: {wx['now_text']}"
        wind = pt.wind_text(wx, gusts=False)
        if wind:
            chip_wx += f", {wind}"
    badge_cls = "badge badge--stale" if stale else pt.BADGE_CLASS[lvl]
    badge_text = pt.stale_chip_text(entry, updated_utc, tz) if stale else word
    if stale:
        status_line = f'          <p>{_esc(word)} {_esc(pt.as_of_text(updated_utc, tz, now))}. Source: {_src_link("FAA NAS status")}.</p>'
    else:
        status_line = f'          <p>{_esc(pt.LEVEL_TEXT[lvl])} ({_src_link("FAA NAS status")})</p>'
    box: list[str] = [
        f'          <p class="card-status"><span class="{badge_cls}">{_esc(badge_text)}</span></p>',
        status_line,
    ]
    if entry.get("reason"):
        box.append(f'          <p class="event-reason">Reason: {_esc(entry["reason"])}</p>')
    if wx.get("now_text"):
        wind = pt.wind_text(wx)
        obs = pt.clock_label(wx.get("obs_utc"), tz)
        obs_age = pt.age_minutes(wx.get("obs_utc") or updated_utc, now)
        if stale:
            wtxt = f"Last weather report: {wx['now_text']}"
            if wind:
                wtxt += f", wind {wind}"
            seen = f"observed {obs}, " if obs else ""
            after = f", {seen}{pt.ago_text(obs_age)})"
        else:
            wtxt = f"Weather now: {wx['now_text']}"
            if wind:
                wtxt += f", wind {wind}"
            after = f", observed {obs}, updated {pt.ago_text(obs_age)})" if obs else f", updated {pt.ago_text(obs_age)})"
        box.append(f'          <p>{_esc(wtxt)} ({_src_link("aviationweather.gov METAR")}{_esc(after)}</p>')
    if wx.get("next3h_text"):
        if not stale:
            box.append(
                f'          <p>Next 3 hours: {_esc(wx["next3h_text"])} ({_src_link("aviationweather.gov TAF")})</p>'
            )
        elif not pt.forecast_expired(wx["next3h_text"], wx.get("taf_issue_utc") or updated_utc, tz, now):
            issued = pt.clock_label(wx.get("taf_issue_utc") or updated_utc, tz)
            box.append(
                f'          <p>Forecast issued {_esc(issued)}: {_esc(wx["next3h_text"])} ({_src_link("aviationweather.gov TAF")})</p>'
            )
    alerts = [str(a) for a in (entry.get("alerts") or [])]
    box.append(f'          <p>{_esc("Alerts: " + ", ".join(alerts) if alerts else "Alerts: none listed.")}</p>')
    upd = f"last updated {pt.ago_text(age)}" if stale and age is not None else (
        f"updated {pt.ago_text(age)}" if age is not None else "update time unknown")
    box.append(
        f'          <p class="credit">Sources: {_src_link("FAA NAS status, aviationweather.gov METAR and TAF")}. Data {_esc(upd)}.</p>'
    )
    return {
        "has": True,
        "stale": stale,
        "chip_class": f"{badge_cls} status-chip",
        "chip": badge_text,
        "wx_chip": chip_wx,
        "checked": checked,
        "stale_notice": pt.stale_text(updated_utc, now),
        "box": box,
        "word": word,
        "wx": pt.weather_summary(wx),
        "clock": clock,
        "as_of": pt.as_of_text(updated_utc, tz, now),
    }


def _render_head(
    *,
    title: str,
    description: str,
    canonical: str,
    breadcrumb: dict[str, Any],
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
        '  <meta name="theme-color" content="#0d1722">',
        '  <link rel="icon" href="../favicon.svg" type="image/svg+xml">',
        '  <link rel="icon" href="../favicon.png" type="image/png">',
        '  <link rel="stylesheet" href="../tokens.css">',
        '  <link rel="stylesheet" href="../style.css">',
        _json_ld_script(breadcrumb),
        "</head>",
    ])


def _nav_chip(label: str, href: str, current: bool) -> str:
    attrs = ' aria-current="page"' if current else ""
    return f'        <a class="chip" href="{href}"{attrs}>{label}</a>'


def _render_header(current: str = "airports") -> str:
    return "\n".join([
        '  <a class="skip-link" href="#main-content">Skip to main content</a>',
        '  <div class="container">',
        '    <header class="site-header">',
        '      <div class="brand-row">',
        '        <a class="brand" href="../index.html">',
        '          <img class="brand-logo" src="../brand/logo.svg" width="36" height="36" alt="Air Travel Desk logo">',
        '          <span class="brand-title">Air Travel Desk</span>',
        "        </a>",
        "      </div>",
        '      <nav class="header-nav" aria-label="Site navigation">',
        _nav_chip("Live board", "../index.html", current == "board"),
        _nav_chip("Airports", "index.html", current == "airports"),
        _nav_chip("About", "../about.html", current == "about"),
        _nav_chip("Privacy", "../privacy.html", current == "privacy"),
        "      </nav>",
        "    </header>",
    ])


def _render_footer() -> str:
    return "\n".join([
        '    <footer class="site-footer">',
        "      <p>Updated automatically from public data. Not affiliated with any airline or government agency.</p>",
        (
            '      <p><a class="tap" href="../index.html">Live board</a> &middot; '
            '<a class="tap" href="index.html">Airports</a> &middot; '
            '<a class="tap" href="../about.html">About</a> &middot; '
            '<a class="tap" href="../sources.html">Data and sources</a> &middot; '
            '<a class="tap" href="../privacy.html">Privacy</a> &middot; '
            f'Contact: <a class="tap" href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a></p>'
        ),
        "    </footer>",
        "  </div>",
    ])


def _sun_now_script() -> str:
    """Inline script: fills #sun-now from ../sun.js. No network request. Any failure leaves the line hidden."""
    return "\n".join([
        '  <script src="../sun.js"></script>',
        "  <script>",
        "  (function () {",
        '    "use strict";',
        '    var p = document.getElementById("sun-now");',
        '    var src = document.getElementById("sun-now-source");',
        "    if (!p || !window.Sun) { return; }",
        "    function paint() {",
        "      try {",
        "        var t = window.Sun.hubCardText(parseFloat(p.getAttribute(\"data-lat\")), parseFloat(p.getAttribute(\"data-lon\")), p.getAttribute(\"data-tz\"), Date.now());",
        '        t = String(t).replace(/^Sun: /, "Sun now: ").replace(/ \\u00b7 computed$/, "");',
        "        var zone = new Intl.DateTimeFormat(\"en-US\", { timeZone: p.getAttribute(\"data-tz\"), timeZoneName: \"short\" }).formatToParts(new Date()).filter(function (x) { return x.type === \"timeZoneName\"; })[0];",
        '        p.textContent = t + (zone ? ". Times are local to the airport (" + zone.value + ")." : ".");',
        "        p.hidden = false;",
        "        if (src) { src.hidden = false; }",
        "      } catch (e) { p.hidden = true; if (src) { src.hidden = true; } }",
        "    }",
        "    paint();",
        "    setInterval(paint, 60000);",
        "  })();",
        "  </script>",
    ])


def _right_now_script(code: str, tz: str = "") -> str:
    """Inline client-side script that populates #status-chip, #weather-chip, and #right-now from ../data/airports.json."""
    code_json = json.dumps(code)
    tz_json = json.dumps(tz)
    return "\n".join([
        "  <script>",
        "  (function () {",
        '    "use strict";',
        f"    var CODE = {code_json};",
        f"    var TZ = {tz_json};",
        '    var box = document.getElementById("right-now");',
        '    var statusChip = document.getElementById("status-chip");',
        '    var wxChip = document.getElementById("weather-chip");',
        "    if (!box) { return; }",
        '    var LEVEL_TEXT = { clear: "Clear — no FAA delay or ground stop listed.", delay: "Delays — FAA delay program in effect.", stop: "Ground stop — FAA ground stop in effect.", closed: "Closed — FAA airport closure in effect." };',
        '    var BADGE_CLASS = { clear: "badge badge--clear", delay: "badge badge--delay", stop: "badge badge--stop", closed: "badge badge--stop" };',
        '    var BADGE_LABEL = { clear: "No FAA delays reported", delay: "Delays", stop: "Ground stop", closed: "Closed" };',
        "    function badgeLabel(a, lvl) {",
        "      if (lvl === \"delay\" && Array.isArray(a.events) && a.events.some(function (ev) { return ev && ev.kind === \"ground_delay\"; })) { return \"Ground delay program\"; }",
        "      return BADGE_LABEL[lvl];",
        "    }",
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
        '      a.href = "../sources.html";',
        "      p.appendChild(a);",
        '      if (after) { p.appendChild(document.createTextNode(after)); }',
        "      return p;",
        "    }",
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
        '    function showStale(iso) {',
        '      var n = document.getElementById("stale-notice");',
        '      if (!n) { return; }',
        '      var m = ageMin(iso);',
        '      if (!isStale(m)) { n.hidden = true; return; }',
        '      n.textContent = "This data is " + oldText(m) + ". It normally updates about every 5 minutes. For the FAA\'s own page, go to ";',
        '      var l = el("a", "stale-link", "nasstatus.faa.gov");',
        '      l.href = "https://nasstatus.faa.gov";',
        '      l.target = "_blank";',
        '      l.rel = "noopener noreferrer";',
        '      n.appendChild(l);',
        '      n.hidden = false;',
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
        '    var checkedLine = document.getElementById("checked-line");',
        '    var heading = document.getElementById("right-now-heading");',
        '    function setUnavailable() {',
        '      if (checkedLine) { checkedLine.textContent = "FAA NAS status: not available right now."; }',
        '      if (statusChip) {',
        '        statusChip.className = "badge status-chip";',
        '        statusChip.textContent = "Status unavailable";',
        '      }',
        '      if (wxChip) { wxChip.hidden = true; }',
        '    }',
        '    function render(data) {',
        '      var updMin = ageMin(data && data.updated_utc);',
        '      var stale = isStale(updMin);',
        '      showStale(data && data.updated_utc);',
        '      if (heading) { heading.textContent = stale ? "Last known status" : "Right now"; }',
        '      var a = data && data.airports && data.airports[CODE];',
        '      if (checkedLine && a) {',
        '        checkedLine.textContent = "";',
        '        var cl = el("a", "tap", "FAA NAS status");',
        '        cl.href = "../sources.html";',
        '        checkedLine.appendChild(cl);',
        '        checkedLine.appendChild(document.createTextNode(", " + checkedText(data.updated_utc, stale) + "."));',
        '      }',
        '      if (!a) {',
        '        setUnavailable();',
        '        box.textContent = "";',
        '        box.appendChild(el("p", null, "Airport status is not available right now. See nasstatus.faa.gov."));',
        '        return;',
        '      }',
        '      var hasClosure = Array.isArray(a.events) && a.events.some(function (ev) { return ev && ev.kind === "closure"; });',
        '      var lvl = (a.level === "closed" || hasClosure) ? "closed" : (LEVEL_TEXT[a.level] ? a.level : "clear");',
        '      var label = badgeLabel(a, lvl);',
        '      var asClock = clockLabel(data.updated_utc);',
        '      var chipText = stale ? "As of " + (asClock || "an unknown time") + ": " + label.charAt(0).toLowerCase() + label.slice(1) : label;',
        '      var badgeCls = stale ? "badge badge--stale" : BADGE_CLASS[lvl];',
        '      if (statusChip) {',
        '        statusChip.className = badgeCls + " status-chip";',
        '        statusChip.textContent = chipText;',
        '      }',
        '      var w = a.wx;',
        '      if (wxChip) {',
        '        if (w && w.now_text && !stale) {',
        '          var chipWx = "Weather: " + w.now_text;',
        '          if (w.wind_kt != null) {',
        '            chipWx += ", " + (Math.round(w.wind_kt) === 0 ? "calm (0 kt)" : Math.round(w.wind_kt) + " kt");',
        '          }',
        '          wxChip.textContent = chipWx;',
        '          wxChip.hidden = false;',
        '        } else {',
        '          wxChip.hidden = true;',
        '        }',
        '      }',
        '      box.textContent = "";',
        '      var statusRow = el("p", "card-status");',
        '      statusRow.appendChild(el("span", badgeCls, chipText));',
        '      box.appendChild(statusRow);',
        '      if (stale) {',
        '        box.appendChild(srcLine(null, label + " as of " + (asClock || "an unknown time") + " (" + agoText(updMin) + "). Source: ", "FAA NAS status", "."));',
        '      } else {',
        '        box.appendChild(srcLine(null, LEVEL_TEXT[lvl] + " (", "FAA NAS status", ")"));',
        '      }',
        '      if (a.reason) {',
        '        box.appendChild(el("p", "event-reason", "Reason: " + a.reason));',
        '      }',
        '      if (w && w.now_text) {',
        '        var wxText = (stale ? "Last weather report: " : "Weather now: ") + w.now_text;',
        '        if (w.wind_kt != null) {',
        '          wxText += ", wind " + (Math.round(w.wind_kt) === 0 ? "calm (0 kt)" : Math.round(w.wind_kt) + " kt" + (w.gust_kt ? " gusting " + Math.round(w.gust_kt) + " kt" : ""));',
        '        }',
        '        var obsIso = w.obs_utc || data.updated_utc;',
        '        var wxAfter = stale',
        '          ? ", " + (clockLabel(w.obs_utc) ? "observed " + clockLabel(w.obs_utc) + ", " : "") + agoText(ageMin(obsIso)) + ")"',
        '          : ", observed " + clockLabel(w.obs_utc) + ", " + ageLabel(obsIso, false) + ")";',
        '        box.appendChild(srcLine(null, wxText + " (", "aviationweather.gov METAR", wxAfter));',
        '      }',
        '      if (w && w.next3h_text) {',
        '        if (!stale) {',
        '          box.appendChild(srcLine(null, "Next 3 hours: " + w.next3h_text + " (", "aviationweather.gov TAF", ")"));',
        '        } else if (!forecastExpired(w.next3h_text, w.taf_issue_utc || data.updated_utc)) {',
        '          box.appendChild(srcLine(null, "Forecast issued " + clockLabel(w.taf_issue_utc || data.updated_utc) + ": " + w.next3h_text + " (", "aviationweather.gov TAF", ")"));',
        '        }',
        '      }',
        '      var alerts = Array.isArray(a.alerts) ? a.alerts : [];',
        '      box.appendChild(el("p", null, alerts.length ? "Alerts: " + alerts.join(", ") : "Alerts: none listed."));',
        '      box.appendChild(srcLine("credit", "Sources: ", "FAA NAS status, aviationweather.gov METAR and TAF", ". Data " + ageLabel(data.updated_utc, stale) + "."));',
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
        dist = f"{km} km" if km is not None else "Within 5 km"
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
    diff = round(float(ontime) - float(ly_ontime), 2)
    if abs(diff) < 0.005:
        return f"Same as {ly_month}"
    pts = f"{abs(diff):.2f}".rstrip("0").rstrip(".")
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
    canonical = f"{SITE_URL}/airports/{code}.html"
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Air Travel Desk", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Airports", "item": f"{SITE_URL}/airports/index.html"},
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
            f'            <p class="glance-ontime-num">{_esc(bts_entry["ontime"])}%</p>',
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
        ontime_html = ['      <section class="airport-section" aria-label="On-time arrivals">', *ontime_lines, "      </section>"]
    else:
        ontime_html = []
    if glance_rows:
        glance_html = [
            '      <section class="airport-section" aria-labelledby="glance-heading">',
            '        <h2 id="glance-heading">At a glance</h2>',
            '        <details class="glance-details"' + (" open" if len(glance_rows) <= 3 else "") + ">",
            "          <summary>Airport facts</summary>",
            *glance_facts,
            "        </details>",
            "      </section>",
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
            f'        <p id="sun-now" class="sun-now" data-lat="{sun_lat}" data-lon="{sun_lon}" data-tz="{_esc(tz)}" hidden></p>',
            '        <p id="sun-now-source" class="small" hidden>Computed from NOAA solar equations.</p>',
        ]

    # Official pages from airport-guide.json
    guide_links = [
        item for item in (guide_entry.get("links") or [])
        if isinstance(item, dict) and _safe_http_url(item.get("url"))
    ]
    official_lines = ['        <ul class="guide-pills">']
    for item in guide_links:
        url = _safe_http_url(item.get("url"))
        label = str(item.get("label") or "Airport website").strip()
        official_lines.append('          <li class="guide-pill-item">')
        official_lines.append(
            f'            <a class="tap guide-pill" href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_esc(label)}</a>'
        )
        official_lines.append("          </li>")
    official_lines.append("        </ul>")
    has_blocked_links = any(item.get("verified") is False for item in guide_links)
    if has_blocked_links:
        official_lines.append(f'        <p class="small guide-note">{_esc(NOTE_BLOCKED_LINKS)}</p>')
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

    # Places within 5 km
    hotels = list((places_entry or {}).get("hotels") or [])
    cars = list((places_entry or {}).get("cars") or [])
    places_credit_date = places_fetched_date or "unknown date"

    # Sources section
    op_label = f"{operator}'s website" if operator else "The airport operator's website"
    source_items = [
        f"FAA NAS status — {'' if live['stale'] else 'live '}airport delays, ground delays, ground stops and closures.",
        f"aviationweather.gov — {'' if live['stale'] else 'live '}airport weather observations (METAR) and 3-hour forecasts (TAF).",
    ]
    if has_bts:
        source_items.append(f"BTS ({bts_month}) — monthly on-time arrival rate and flight count.")
    elif bts_month:
        source_items.append(f"BTS ({bts_month}) — monthly on-time arrival data (no entry for {code}).")
    if has_places:
        source_items.append(
            f"OpenStreetMap (&copy; OpenStreetMap contributors) — hotels and car rental within 5 km, fetched {places_credit_date}."
        )
    if guide_entry.get("origin") == "ourairports":
        source_items.append("OurAirports (public domain) — the address of the airport's website.")
    if has_blocked_links:
        source_items.append(f"{_esc(op_label)} — {_esc(LINKS_NOT_ALL_CHECKED)}")
    else:
        source_items.append(
            f"{_esc(op_label)} — {_esc(LINKS_ALL_CHECKED.format(date=guide_checked_date or build_date))}"
        )

    places_html: list[str] = []
    if has_places:
        places_html = [
            '      <section class="airport-section" aria-labelledby="places-heading">',
            '        <h2 id="places-heading">Hotels and car rental within 5 km</h2>',
            '        <div class="places-columns">',
            '          <div class="places-col">',
            "            <h3>Hotels</h3>",
            _render_place_list(hotels, "No hotels with a name are listed in OpenStreetMap within 5 km.", "hotels"),
            "          </div>",
            '          <div class="places-col">',
            "            <h3>Car rental</h3>",
            _render_place_list(cars, "No car rental places are listed in OpenStreetMap within 5 km.", "car rental places"),
            "          </div>",
            "        </div>",
            (
                f'        <p class="credit">&copy; OpenStreetMap contributors. Data from {_esc(places_credit_date)}. '
                "Distances are straight-line. We show no prices and do not know what is available.</p>"
            ),
            "      </section>",
        ]

    parts = [
        _render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        "<body>",
        _render_header(),
        '    <main id="main-content" class="airport-main">',
        f'      <h1 class="airport-page-title">{_esc(name)} ({_esc(code)}): delays, weather and traveler help</h1>',
        (
            f'      <p id="stale-notice" class="stale-notice" role="status">{_esc(live["stale_notice"])} '
            '<a class="stale-link" href="https://nasstatus.faa.gov" target="_blank" rel="noopener noreferrer">nasstatus.faa.gov</a></p>'
            if live["has"] and live["stale"]
            else '      <p id="stale-notice" class="stale-notice" role="status" hidden></p>'
        ),
        '      <div class="airport-summary-band">',
        '        <div class="airport-summary-chips">',
        f'          <span id="status-chip" class="{live["chip_class"]}" aria-live="polite">{_esc(live["chip"])}</span>',
        (
            f'          <span id="weather-chip" class="badge weather-chip">{_esc(live["wx_chip"])}</span>'
            if live["wx_chip"]
            else '          <span id="weather-chip" class="badge weather-chip" hidden></span>'
        ),
        "        </div>",
        (
            f'        <p id="checked-line" class="last-checked">{_src_link("FAA NAS status")}{_esc(live["checked"][len("FAA NAS status"):])}</p>'
            if live["has"]
            else f'        <p id="checked-line" class="last-checked">{_esc(live["checked"])}</p>'
        ),
        '        <div class="airport-summary-actions">',
        '          <a class="btn btn-accent" href="../stuck.html">I\'m stuck guide</a>',
        "        </div>",
        "      </div>",
        '      <section class="airport-section" aria-labelledby="right-now-heading">',
        f'        <h2 id="right-now-heading">{"Last known status" if live["stale"] else "Right now"}</h2>',
        f'        <div id="right-now" class="right-now-box" data-code="{_esc(code)}"{prerendered_attr}>',
        *live["box"],
        "        </div>",
        *sun_now_html,
        "        <noscript>",
        f'          <p class="noscript-note">{"Refreshing" if live["stale"] else "Live refresh"} needs JavaScript. The status above is from the last site build; for the FAA\'s own page, see nasstatus.faa.gov.</p>',
        "        </noscript>",
        "      </section>",
        *ontime_html,
        *_render_hero_illustration(code),
        *glance_html,
        '      <section class="airport-section" aria-labelledby="official-heading">',
        '        <h2 id="official-heading">Official pages</h2>',
        *official_lines,
        "      </section>",
        *places_html,
        '      <section class="airport-section" aria-labelledby="stuck-heading">',
        '        <h2 id="stuck-heading">If you are stuck here</h2>',
        '        <div class="stuck-note">',
        (
            '          <p>If your flight is delayed or cancelled, walk through the step-by-step '
            '<a class="tap" href="../stuck.html">I\'m stuck at the airport guide</a> for airline commitments, '
            'refund rules under 14 CFR 260.6, counter scripts and an email draft, or '
            f'<a class="tap" href="{DOWNTIME_URL}" target="_blank" rel="noopener noreferrer">'
            "check what you may be owed</a>. This is plain-language help, not legal advice; your airline decides "
            "every claim, voucher or reimbursement.</p>"
        ),
        "        </div>",
        "      </section>",
        '      <section class="airport-section" aria-labelledby="sources-heading">',
        '        <h2 id="sources-heading">Where this page\'s data comes from</h2>',
        '        <ul class="airport-sources">',
        *[f"          <li>{line}</li>" for line in source_items],
        "        </ul>",
        "      </section>",
        '      <section class="airport-section airport-about-note" aria-labelledby="about-page-heading">',
        '        <h2 id="about-page-heading">About this page</h2>',
        '        <p class="small">This page is independent and not affiliated with the airport, the FAA or any airline. Data sources and dates are listed above. Read <a class="tap" href="../about.html">About Air Travel Desk</a> for how these pages are made.</p>',
        "      </section>",
        "    </main>",
        _render_footer(),
        _sun_now_script() if tz else "",
        _right_now_script(code, tz),
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
) -> str:
    """Render HTML for airports/index.html: all airports, grouped by state (the list is static HTML, no script)."""
    n = len(codes)
    title = f"US airport status: {n} busiest airports, live delays"
    description = (
        f"Directory of the {n} busiest US airports on Air Travel Desk with city, "
        "monthly BTS on-time arrival rate, live status links and traveler guides."
    )
    canonical = f"{SITE_URL}/airports/index.html"
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
                rate_line = f"Last month's on-time rate ({bts_month}): {b['ontime']}%"
            else:
                rate_line = ""      # no BTS number for this airport: show nothing instead of 'unavailable' on every card
            sections.append('          <li class="airport-index-card">')
            sections.append(
                f'            <a class="tap airport-index-link" href="{_esc(code)}.html">{_esc(name)} ({_esc(code)})</a>'
            )
            if city:
                sections.append(f'            <p class="airport-index-meta">{_esc(city)}</p>')
            if rate_line:
                sections.append(f'            <p class="airport-index-meta">{_esc(rate_line)}</p>')
            sections.append("          </li>")
        sections.append("        </ul>")

    source_items = [
        "FAA NAS status and aviationweather.gov — live delays and weather on each airport page.",
        f"BTS ({bts_month or 'monthly'}) — monthly on-time arrival rate where available.",
        f"OpenStreetMap (&copy; OpenStreetMap contributors) — nearby hotels and car rental where we have them, fetched {places_fetched_date or 'unknown date'}.",
        "Airport operators' own websites — official airport links. Some sites block automatic checks, so not every link is verified by script.",
        "OurAirports (public domain) — the website address for airports outside the first 30.",
    ]

    parts = [
        _render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        "<body>",
        _render_header(),
        '    <main id="main-content" class="airport-main">',
        '      <h1 class="airport-page-title">US Airports: delays, weather and traveler help</h1>',
        f'      <p class="airport-purpose">Purpose: directory of the {n} busiest US airports with city, last month\'s on-time arrival rate and a dedicated help page for each airport.</p>',
        '      <p class="small">The <a href="../index.html">live board</a> on the home page shows the first 30.</p>',
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
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def render_sitemap_block(codes: list[str], build_date: str) -> str:
    """Render the managed <!-- airports:begin --> ... <!-- airports:end --> sitemap block."""
    urls = [f"{SITE_URL}/airports/index.html"] + [f"{SITE_URL}/airports/{code}.html" for code in codes]
    lines = [f"  {SITEMAP_BEGIN}"]
    for url in urls:
        lines.append(f"  <url><loc>{_esc(url)}</loc><lastmod>{_esc(build_date)}</lastmod></url>")
    lines.append(f"  {SITEMAP_END}")
    return "\n".join(lines)


def update_sitemap(sitemap_path: Path, codes: list[str], build_date: str) -> None:
    """Insert or replace the airports sitemap block in sitemap.xml."""
    block = render_sitemap_block(codes, build_date)
    if sitemap_path.is_file():
        content = sitemap_path.read_text(encoding="utf-8")
    else:
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "</urlset>\n"
        )

    pattern = re.compile(
        r"[ \t]*" + re.escape(SITEMAP_BEGIN) + r".*?" + re.escape(SITEMAP_END),
        re.DOTALL,
    )
    if pattern.search(content):
        updated = pattern.sub(block, content, count=1)
    elif "</urlset>" in content:
        updated = content.replace("</urlset>", f"{block}\n</urlset>", 1)
    else:
        updated = content.rstrip() + "\n" + block + "\n"
    sitemap_path.write_text(updated, encoding="utf-8")


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
    places_fetched_date = str(places_data.get("fetched_utc") or "")[:10]

    # Pages for the 100 busiest airports, in rank order. An airport with no link entry still gets a page.
    codes = list(desk_airports.BUSIEST_100)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
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
