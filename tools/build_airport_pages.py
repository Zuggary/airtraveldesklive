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

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = "https://www.airtraveldesklive.com"
DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive"
CONTACT_EMAIL = "hello@airtraveldesklive.com"
BTS_DEFINITION_SHORT = "BTS counts a flight on time if it arrives less than 15 minutes late"

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


def _render_header() -> str:
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
        '        <a class="chip" href="../index.html">Live board</a>',
        '        <a class="chip" href="index.html">Airports</a>',
        '        <a class="chip" href="../about.html">About</a>',
        '        <a class="chip" href="../privacy.html">Privacy</a>',
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
        '    var BADGE_LABEL = { clear: "Clear", delay: "Delays", stop: "Ground stop", closed: "Closed" };',
        "    function el(tag, cls, text) {",
        "      var n = document.createElement(tag);",
        "      if (cls) { n.className = cls; }",
        "      if (text != null) { n.textContent = text; }",
        "      return n;",
        "    }",
        "    function ageLabel(iso) {",
        '      var ms = Date.parse(iso || "");',
        '      if (!isFinite(ms)) { return "update time unknown"; }',
        "      var m = Math.max(0, Math.floor((Date.now() - ms) / 60000));",
        '      return "updated " + (m < 1 ? "less than 1 min ago" : m + " min ago");',
        "    }",
        "    function clockLabel(iso) {",
        '      var ms = Date.parse(iso || "");',
        '      if (!isFinite(ms)) { return ""; }',
        "      try {",
        '        var opts = { hour: "numeric", minute: "2-digit", timeZoneName: "short" };',
        "        if (TZ) { opts.timeZone = TZ; }",
        '        return new Intl.DateTimeFormat("en-US", opts).format(new Date(ms));',
        "      } catch (e) { return \"\"; }",
        "    }",
        "    function checkedText(iso) {",
        "      var c = clockLabel(iso);",
        '      var m = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60000));',
        '      var age = m < 1 ? "less than 1 min ago" : (m >= 120 ? Math.floor(m / 60) + " hours ago" : m + " min ago");',
        '      return c ? "Checked " + c + " (" + age + ")" : "Check time unknown";',
        "    }",
        '    var checkedLine = document.getElementById("checked-line");',
        "    function setUnavailable() {",
        '      if (checkedLine) { checkedLine.textContent = "FAA NAS status: not available right now."; }',
        "      if (statusChip) {",
        '        statusChip.className = "badge status-chip";',
        '        statusChip.textContent = "Status unavailable";',
        "      }",
        "      if (wxChip) { wxChip.hidden = true; }",
        "    }",
        "    function render(data) {",
        "      var a = data && data.airports && data.airports[CODE];",
        '      if (checkedLine && a) { checkedLine.textContent = "FAA NAS status. " + checkedText(data.updated_utc) + "."; }',
        "      if (!a) {",
        "        setUnavailable();",
        "        box.textContent = \"\";",
        '        box.appendChild(el("p", null, "Airport status is not available right now. See nasstatus.faa.gov."));',
        "        return;",
        "      }",
        "      var hasClosure = Array.isArray(a.events) && a.events.some(function (ev) { return ev && ev.kind === \"closure\"; });",
        '      var lvl = (a.level === "closed" || hasClosure) ? "closed" : (LEVEL_TEXT[a.level] ? a.level : "clear");',
        "      if (statusChip) {",
        '        statusChip.className = BADGE_CLASS[lvl] + " status-chip";',
        "        statusChip.textContent = BADGE_LABEL[lvl];",
        "      }",
        "      var w = a.wx;",
        "      if (wxChip) {",
        "        if (w && w.now_text) {",
        '          var chipWx = "Weather: " + w.now_text;',
        "          if (w.wind_kt != null) {",
        '            chipWx += ", " + Math.round(w.wind_kt) + " kt";',
        "          }",
        "          wxChip.textContent = chipWx;",
        "          wxChip.hidden = false;",
        "        } else {",
        "          wxChip.hidden = true;",
        "        }",
        "      }",
        "      box.textContent = \"\";",
        '      var statusRow = el("p", "card-status");',
        '      statusRow.appendChild(el("span", BADGE_CLASS[lvl], BADGE_LABEL[lvl]));',
        "      box.appendChild(statusRow);",
        '      box.appendChild(el("p", null, LEVEL_TEXT[lvl] + " (FAA NAS status)"));',
        "      if (a.reason) {",
        '        box.appendChild(el("p", "event-reason", "Reason: " + a.reason));',
        "      }",
        "      if (w && w.now_text) {",
        '        var wxText = "Weather now: " + w.now_text;',
        "        if (w.wind_kt != null) {",
        '          wxText += ", wind " + Math.round(w.wind_kt) + " kt" + (w.gust_kt ? " gusting " + Math.round(w.gust_kt) + " kt" : "");',
        "        }",
        '        wxText += " (aviationweather.gov METAR, observed " + clockLabel(w.obs_utc) + ", " + ageLabel(w.obs_utc || data.updated_utc) + ")";',
        '        box.appendChild(el("p", null, wxText));',
        "      }",
        "      if (w && w.next3h_text) {",
        '        box.appendChild(el("p", null, "Next 3 hours: " + w.next3h_text + " (aviationweather.gov TAF)"));',
        "      }",
        "      var alerts = Array.isArray(a.alerts) ? a.alerts : [];",
        '      box.appendChild(el("p", null, alerts.length ? "Alerts: " + alerts.join(", ") : "Alerts: none listed."));',
        '      box.appendChild(el("p", "credit", "Sources: FAA NAS status, aviationweather.gov METAR and TAF. Data " + ageLabel(data.updated_utc) + "."));',
        "    }",
        '    fetch("../data/airports.json?ts=" + Date.now(), { cache: "no-store" })',
        '      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })',
        "      .then(render)",
        "      .catch(function () {",
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
) -> str:
    """Render HTML for a single airport page."""
    name = str(airport_info.get("name") or code)
    city = str(airport_info.get("city") or "")
    tz = str(airport_info.get("tz") or "")
    operator = str(guide_entry.get("operator") or "")

    title = f"{name} ({code}): delays, weather and traveller help — Air Travel Desk"
    description = (
        f"Live FAA delay status, airport weather, official {code} operator links, "
        f"nearby hotels and car rental, and delay help for {name} ({code})."
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

    glance_rows: list[tuple[str, str]] = [("Airport code", code)]
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
        glance_html = [
            '        <div class="glance-grid">',
            *glance_facts,
            *ontime_lines,
            "        </div>",
        ]
    else:
        glance_html = ['        <div class="glance-grid glance-grid--single">', *glance_facts, "        </div>"]

    # Official pages from airport-guide.json
    guide_links = [
        item for item in (guide_entry.get("links") or [])
        if isinstance(item, dict) and _safe_http_url(item.get("url"))
    ]
    official_lines = ['        <ul class="guide-pills">']
    for item in guide_links:
        url = _safe_http_url(item.get("url"))
        base_label = str(item.get("label") or "Airport website").strip()
        unchecked = item.get("verified") is False
        pill_text = f"{base_label} (unchecked)" if unchecked else base_label
        extra_attrs = ""
        if unchecked:
            note = f"{base_label} — we could not check this link by script"
            extra_attrs = f' title="{_esc(note)}" aria-label="{_esc(note)}"'
        official_lines.append('          <li class="guide-pill-item">')
        official_lines.append(
            f'            <a class="tap guide-pill" href="{_esc(url)}" target="_blank" rel="noopener noreferrer"{extra_attrs}>{_esc(pill_text)}</a>'
        )
        official_lines.append("          </li>")
    official_lines.append("        </ul>")
    if len(guide_links) < 4:
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
        "FAA NAS status — live airport delays, ground delays, ground stops and closures.",
        "aviationweather.gov — live airport weather observations (METAR) and 3-hour forecasts (TAF).",
    ]
    if has_bts:
        source_items.append(f"BTS ({bts_month}) — monthly on-time arrival rate and flight count.")
    elif bts_month:
        source_items.append(f"BTS ({bts_month}) — monthly on-time arrival data (no entry for {code}).")
    source_items.append(
        f"OpenStreetMap (&copy; OpenStreetMap contributors) — hotels and car rental within 5 km, fetched {places_credit_date}."
    )
    source_items.append(
        f"{_esc(op_label)} — official airport pages, links checked {guide_checked_date or build_date}."
    )

    parts = [
        _render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        "<body>",
        _render_header(),
        '    <main id="main-content" class="airport-main">',
        f'      <h1 class="airport-page-title">{_esc(name)} ({_esc(code)}): delays, weather and traveller help</h1>',
        '      <div class="airport-summary-band">',
        '        <div class="airport-summary-chips">',
        '          <span id="status-chip" class="badge status-chip" aria-live="polite">Checking live status…</span>',
        '          <span id="weather-chip" class="badge weather-chip" hidden></span>',
        "        </div>",
        '        <p id="checked-line" class="last-checked">Checking FAA NAS status\u2026</p>',
        '        <div class="airport-summary-actions">',
        '          <a class="btn btn-secondary" href="../stuck.html">I\'m stuck guide</a>',
        "        </div>",
        "      </div>",
        '      <section class="airport-section" aria-labelledby="glance-heading">',
        '        <h2 id="glance-heading">At a glance</h2>',
        *glance_html,
        "      </section>",
        '      <section class="airport-section" aria-labelledby="right-now-heading">',
        '        <h2 id="right-now-heading">Right now</h2>',
        f'        <div id="right-now" class="right-now-box" data-code="{_esc(code)}">',
        '          <p class="updated-text">Loading current FAA status and weather…</p>',
        "        </div>",
        "        <noscript>",
        '          <p class="noscript-note">Live status needs JavaScript; see nasstatus.faa.gov.</p>',
        "        </noscript>",
        "      </section>",
        '      <section class="airport-section" aria-labelledby="official-heading">',
        '        <h2 id="official-heading">Official pages</h2>',
        *official_lines,
        "      </section>",
        '      <section class="airport-section" aria-labelledby="places-heading">',
        '        <h2 id="places-heading">Hotels and car rental within 5 km</h2>',
        '        <div class="places-columns">',
        '          <div class="places-col">',
        "            <h3>Hotels within 5 km</h3>",
        _render_place_list(hotels, "No hotels with a name are listed in OpenStreetMap within 5 km.", "hotels"),
        "          </div>",
        '          <div class="places-col">',
        "            <h3>Car rental within 5 km</h3>",
        _render_place_list(cars, "No car rental places are listed in OpenStreetMap within 5 km.", "car rental places"),
        "          </div>",
        "        </div>",
        (
            f'        <p class="credit">&copy; OpenStreetMap contributors. Data from {_esc(places_credit_date)}. '
            "Distances are straight-line. We show no prices and do not know what is available.</p>"
        ),
        "      </section>",
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
        _right_now_script(code, tz),
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def render_index_page(
    codes: list[str],
    *,
    guide_checked_date: str,
    airports_map: dict[str, Any],
    places_fetched_date: str,
    bts_data: dict[str, Any],
    build_date: str,
) -> str:
    """Render HTML for airports/index.html listing all 30 airports."""
    title = "US Airports: delays, weather and traveller help — Air Travel Desk"
    description = (
        "Directory of the 30 busiest US airports on Air Travel Desk with city, "
        "monthly BTS on-time arrival rate, live status links and traveller guides."
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

    cards: list[str] = ['        <ul class="airport-index-list">']
    for code in codes:
        info = airports_map.get(code) or {}
        name = str(info.get("name") or code)
        city = str(info.get("city") or "")
        b = bts_airports.get(code)
        if isinstance(b, dict) and b.get("ontime") is not None and bts_month:
            rate_line = f"Last month's on-time rate ({bts_month}): {b['ontime']}%"
        else:
            rate_line = "Last month's on-time rate: unavailable"
        cards.append('          <li class="airport-index-card">')
        cards.append(
            f'            <a class="tap airport-index-link" href="{_esc(code)}.html">{_esc(name)} ({_esc(code)})</a>'
        )
        if city:
            cards.append(f'            <p class="airport-index-meta">{_esc(city)}</p>')
        cards.append(f'            <p class="airport-index-meta">{_esc(rate_line)}</p>')
        cards.append("          </li>")
    cards.append("        </ul>")

    source_items = [
        "FAA NAS status and aviationweather.gov — live delays and weather on each airport page.",
        f"BTS ({bts_month or 'monthly'}) — monthly on-time arrival rate where available.",
        f"OpenStreetMap (&copy; OpenStreetMap contributors) — nearby hotels and car rental, fetched {places_fetched_date or 'unknown date'}.",
        f"Airport operators' own websites — official airport links, checked {guide_checked_date or build_date}.",
    ]

    parts = [
        _render_head(title=title, description=description, canonical=canonical, breadcrumb=breadcrumb),
        "<body>",
        _render_header(),
        '    <main id="main-content" class="airport-main">',
        '      <h1 class="airport-page-title">US Airports: delays, weather and traveller help</h1>',
        '      <p class="airport-purpose">Purpose: directory of the 30 busiest US airports with city, last month\'s on-time arrival rate and a dedicated help page for each airport.</p>',
        '      <section class="airport-section" aria-labelledby="directory-heading">',
        '        <h2 id="directory-heading">30 busiest US airports</h2>',
        *cards,
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
) -> list[Path]:
    """Generate all 30 airport pages and airports/index.html, and optionally update sitemap.xml."""
    date_str = build_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    guide_data = _load_json(data_dir / "airport-guide.json")
    airports_data = _load_json(data_dir / "airports.json")
    places_data = _load_json(data_dir / "places.json")
    bts_data = _load_json(data_dir / "bts.json")

    guide_airports = guide_data.get("airports") or {}
    if not guide_airports:
        raise ValueError(f"No airports found in {data_dir / 'airport-guide.json'}")

    airports_map = airports_data.get("airports") or {}
    places_airports = places_data.get("airports") or {}
    guide_checked_date = str(guide_data.get("checked_utc") or "")[:10]
    places_fetched_date = str(places_data.get("fetched_utc") or "")[:10]

    codes = list(guide_airports.keys())
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for code in codes:
        page_html = render_airport_page(
            code,
            guide_entry=guide_airports[code],
            guide_checked_date=guide_checked_date,
            airport_info=airports_map.get(code) or {},
            places_entry=places_airports.get(code),
            places_fetched_date=places_fetched_date,
            bts_data=bts_data,
            build_date=date_str,
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
    )
    print(f"build_airport_pages: wrote {len(written)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
