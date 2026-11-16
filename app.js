(function () {
  "use strict";

  var A = window.ATD;
  var REFRESH_MS = 60000;
  var TICK_MS = 30000;
  var SLOW_MS = 30 * 60000;
  var STALE_MIN = A.STALE_MIN;   // one limit for "live" wording; lib.js and the Python build use the same 30
  var TWITCH_SRC = "https://player.twitch.tv/?channel=airtraveldesklive&parent=www.airtraveldesklive.com&parent=airtraveldesklive.com&muted=true";
  var DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var LEVEL_WORD = { clear: "Clear", delay: "Delay", stop: "Ground stop" };
  var FALLBACK_LEVEL = { green: "clear", amber: "delay", red: "stop" };

  var D = { hist: null, history: null, state: null, cards: null, places: null, guide: null, security: null, commit: null, bts: null, tsa: null, radarMeta: null, radarImg: null, geo: null };
  var airports = [];       // [{code, name, short, city, level, ...}] the board airports (the first 30), in board order
  var allAirports = [];    // all 100 busiest airports, for the search box
  var byCode = {};
  var allByCode = {};
  var currentCode = "";
  var cardRefs = null;
  var slowLoaded = false;

  var $ = function (id) { return document.getElementById(id); };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) { n.className = cls; }
    if (text != null) { n.textContent = text; }
    return n;
  }

  function getJson(url, fresh) {
    var u = fresh ? url + "?ts=" + Date.now() : url;
    return fetch(u, fresh ? { cache: "no-store" } : undefined)
      .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
      .catch(function () { return null; });
  }

  function fmtTime(date, tz) {
    try {
      var o = { hour: "numeric", minute: "2-digit", timeZoneName: "short" };
      if (tz) { o.timeZone = tz; }
      return new Intl.DateTimeFormat(undefined, o).format(date);
    } catch (e) { return ""; }
  }

  function fmtDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? MONTHS[parseInt(m[2], 10) - 1] + " " + parseInt(m[3], 10) : "";
  }

  function fmtDayYear(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? MONTHS[parseInt(m[2], 10) - 1] + " " + parseInt(m[3], 10) + ", " + m[1] : "";
  }

  // AN34 r2: a timestamp's day in the visitor's own time zone ("updated Nov 15"), never the UTC date.
  function fmtLocalDay(iso) {
    var ms = Date.parse(iso || "");
    if (!isFinite(ms)) { return fmtDay(iso); }
    try { return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(ms)); } catch (e) { return fmtDay(iso); }
  }

  function million(n) { return (n / 1e6).toFixed(2) + " million"; }

  // AN35: the moment a scheduled closure is judged at: now, or the data's own time when the data is stale.
  function atMs() {
    var u = D.state && D.state.updated_utc, ms = Date.parse(u || "");
    return isFinite(ms) && A.isStale(ageMin(u)) ? ms : Date.now();
  }
  function ageMin(iso) {
    var ms = Date.parse(iso || "");
    return isFinite(ms) ? Math.max(0, Math.floor((Date.now() - ms) / 60000)) : null;
  }

  function ageText(iso) {
    var m = ageMin(iso);
    if (m == null) { return "time unknown"; }
    return A.agoText(m);
  }

  // True when the FAA data is older than STALE_MIN (or has no time). Live words are not used then.
  function isStaleIso(iso) { return A.isStale(ageMin(iso)); }
  function asOfText(iso, tz) {
    var ms = Date.parse(iso || "");
    var clock = isFinite(ms) ? fmtTime(new Date(ms), tz) : "";
    return "as of " + (clock || "an unknown time") + (isFinite(ms) ? " (" + ageText(iso) + ")" : "");
  }
  function staleChipText(word, iso, tz) {
    var ms = Date.parse(iso || "");
    var clock = isFinite(ms) ? fmtTime(new Date(ms), tz) : "";
    return "As of " + (clock || "an unknown time") + ": " + word.charAt(0).toLowerCase() + word.slice(1);
  }

  // ---------- data -> airport list ----------
  function buildAirports() {
    var list = [];
    if (D.cards && D.cards.airports) {
      Object.keys(D.cards.airports).forEach(function (c) { list.push(D.cards.airports[c]); });
    } else if (D.state && Array.isArray(D.state.board)) {
      D.state.board.forEach(function (b) {
        list.push({ code: b.code, name: b.name, short: b.name, city: "", level: FALLBACK_LEVEL[b.level] || "clear", events: [], alerts: [], aircraft_near: null, tz: b.tz || "" });
      });
    }
    // Levels and events always come from state.json when it is newer than airports.json.
    // The board, the map and the airport card cover the airports on the state.json board (30). The search covers all of them;
    // an airport outside the board opens its own page.
    // AN35: an airport inside a scheduled daily closure is calm: it counts as normal here, and the headline line and its program row say "closed overnight".
    list.forEach(function (a) { if (a.level === "stop" && A.isScheduledOnly(a, atMs())) { a.level = "clear"; } });
    allAirports = list;
    var boardCodes = {};
    var hasBoard = D.state && Array.isArray(D.state.board) && D.state.board.length;
    if (hasBoard) { D.state.board.forEach(function (b) { boardCodes[b.code] = true; }); }
    list = hasBoard ? list.filter(function (a) { return boardCodes[a.code]; }) : list.slice(0, 30);
    airports = list;
    byCode = {};
    allByCode = {};
    list.forEach(function (a) { byCode[a.code] = a; });
    allAirports.forEach(function (a) { allByCode[a.code] = a; });
  }

  function faaEvents() {
    var evs = (D.state && Array.isArray(D.state.events)) ? D.state.events : [];
    var rank = { ground_stop: 4, closure: 4, ground_delay: 3, delay: 2 };
    // AN35: a daily closure outside its hours is not an event.
    var sorted = evs.filter(function (e) { var sc = e.kind === "closure" && A.closureSchedule(e, e.tz, atMs()); return e.source === "FAA" && rank[e.kind] && !(sc && !sc.in_window); }).sort(function (a, b) {
      var d = rank[b.kind] - rank[a.kind];
      if (d) { return d; }
      return (A.minutesOf(b.fields && b.fields.avg) || 0) - (A.minutesOf(a.fields && a.fields.avg) || 0);
    });
    var seen = {}; // AN32: one row per airport, the worst program first
    return sorted.filter(function (e) { var c = String(e.airport || ""); if (seen[c]) { return false; } seen[c] = true; return true; });
  }

  // ---------- header: live video ----------
  function initLive() {
    var btn = $("load-live"), panel = $("live-panel"), frame = $("live-frame");
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      if (open) {
        frame.textContent = "";
        panel.hidden = true;
        btn.setAttribute("aria-expanded", "false");
        btn.textContent = "Load live video";
        return;
      }
      var f = document.createElement("iframe");
      f.src = TWITCH_SRC;
      f.title = "Air Travel Desk live video on Twitch";
      f.allowFullscreen = true;
      f.setAttribute("allow", "autoplay; fullscreen");
      f.className = "live-player";
      frame.textContent = "";
      frame.appendChild(f);
      panel.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      btn.textContent = "Hide live video";
    });
  }

  // ---------- 1: right now ----------
  function setStale(stale, text) {
    // AN34 r2: one line on a phone: "FAA's own page:" and the long link text hide below 700 px.
    var tail = / FAA's own page:$/.test(text);
    stale.textContent = (tail ? text.replace(/ FAA's own page:$/, "") : text) + " ";
    if (tail) { stale.appendChild(el("span", "sn-long", "FAA's own page: ")); }
    var a = document.createElement("a");
    a.className = "stale-link";
    a.href = "https://nasstatus.faa.gov";
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.appendChild(el("span", "sn-wide", "nasstatus.faa.gov"));
    a.appendChild(el("span", "sn-short", "FAA status"));
    stale.appendChild(a);
    stale.hidden = false;
  }

  function oldText(m) {
    if (m == null) { return "of unknown age"; }
    return A.oldText(m);
  }

  function renderFreshness() {
    var upd = D.state && D.state.updated_utc;
    var m = ageMin(upd);
    var line = $("updated-line"), stale = $("stale-notice");
    if (!D.state) {
      line.textContent = "Status not loaded";
      setStale(stale, "The latest status did not load. Try again in a minute, or see the FAA's own page:");
      return;
    }
    var clock = m == null ? "" : fmtTime(new Date(Date.parse(upd)));
    var stale0 = A.isStale(m);
    // AN34 round 4: a dateline (the visitor's day and clock of the FAA check) in place of a pulsing "Right now".
    var dl = "Latest FAA check";
    if (m != null) { var dd = new Date(Date.parse(upd)); try { dl = A.dateline({ weekday: dd.toLocaleDateString("en-US", { weekday: "long" }), hour: dd.getHours(), clock: fmtTime(dd) }); } catch (e) { /* keep the plain label */ } }
    ($("now-title") || $("now-heading")).textContent = stale0 ? "Last known status" : dl;
    // AN35: this line is the one place the FAA data age is stated (the stale banner states it when the data is old).
    line.textContent = m == null ? "Update time unavailable" : A.faaAgePlain(m, clock, stale0);
    var staleFeeds = (D.state.stale_feeds || []);
    if (staleFeeds.indexOf("FAA") >= 0) {
      // The job kept the last good FAA list because the FAA fetch failed; never present it as fresh.
      setStale(stale, "The FAA status list is " + oldText(m) + " and could not be refreshed. FAA's own page:");
    } else if (m == null || m > STALE_MIN) {
      setStale(stale, "This data is " + oldText(m) + ", not live. FAA's own page:");
    } else {
      stale.hidden = true;
    }
  }

  function nbspUnits(t) { return String(t || "").replace(/(\d) (h|min)\b/g, "$1\u00a0$2").replace(/\bh (\d)/g, "h\u00a0$1"); }

  // AN34: the verdict headline, with the count in the status colour, and one plain line on the exceptions.
  function renderSummary() {
    var s = $("summary"), tl = $("trouble-line");
    if (!D.state) { s.textContent = "Unable to load the latest FAA status."; return; }
    var upd = D.state.updated_utc, stale = isStaleIso(upd);
    var list = allAirports.length ? allAirports : airports;
    var have = {};
    list.forEach(function (a) { have[a.code] = 1; });
    var outside = faaEvents().filter(function (e) { return !have[String(e.airport || "")]; });
    var text = A.nationalSummary(list, stale ? asOfText(upd) : "", outside, atMs());
    var m = /^(\d+ of the \d+)(.*)$/.exec(text);
    s.textContent = "";
    if (m) { s.appendChild(el("em", "ok", m[1])); s.appendChild(document.createTextNode(m[2])); } else { s.textContent = text; }
    if (tl) { tl.textContent = nbspUnits(A.troubleLine(list, stale, atMs())); }
    renderChips();
  }

  // Quick picks under the search: this browser's airports first, then the airports with trouble, else the biggest hubs.
  function chipFor(a) {
    var lvl = A.LEVEL_RANK.hasOwnProperty(a.level) ? a.level : "clear";
    var c = el("a", "pick pick--" + lvl);
    c.href = "airports/" + a.code + ".html";
    c.appendChild(el("span", "dot dot--" + lvl));
    c.appendChild(el("span", "pick-code", a.code));
    var tail = "Normal";
    if (lvl !== "clear") {
      var closed = (a.events || []).some(function (e) { return e && e.kind === "closure"; });
      var mins = null;
      (a.events || []).forEach(function (e) { var x = A.minutesOf(e && e.avg); if (x != null && (mins == null || x > mins)) { mins = x; } });
      tail = closed ? "Closed" : lvl === "stop" ? "Ground stop" : mins != null ? nbspUnits(A.fmtMinutes(mins)) : "Delays";
    }
    c.appendChild(el("span", "pick-tail", tail));
    return c;
  }
  function renderChips() {
    var box = $("chips");
    if (!box) { return; }
    box.textContent = "";
    var mine = getMine(), last = getLast();
    if (last && mine.indexOf(last) < 0) { mine = [last].concat(mine); }
    mine = mine.slice(0, 4);
    var trouble = allAirports.filter(function (a) { return (a.level === "stop" || a.level === "delay") && mine.indexOf(a.code) < 0; });
    trouble.sort(function (x, y) { return (y.level === "stop" ? 1 : 0) - (x.level === "stop" ? 1 : 0); });
    trouble = trouble.slice(0, 4);
    if (mine.length) {
      box.appendChild(el("span", "picks-label", "Yours"));
      mine.forEach(function (c) { if (allByCode[c]) { box.appendChild(chipFor(allByCode[c])); } });
    }
    if (trouble.length) {
      box.appendChild(el("span", "picks-label", "Trouble now"));
      trouble.forEach(function (a) { box.appendChild(chipFor(a)); });
    }
    if (!mine.length && !trouble.length) {
      box.appendChild(el("span", "picks-label", "Busiest"));
      ["ATL", "DFW", "DEN", "ORD"].forEach(function (c) { if (allByCode[c]) { box.appendChild(chipFor(allByCode[c])); } });
    }
  }

  var REASON_PREFIX = { "WX": "weather", "VOLUME": "traffic volume", "RWY/TWY": "runway or taxiway", "EQUIPMENT": "equipment", "STAFFING": "staffing", "OTHER": "other" };
  function reasonText(r) {
    return String(r || "").split(";").map(function (part) {
      part = part.trim();
      var m = /^([A-Za-z/]+):\s*(.*)$/.exec(part);
      var p = m && REASON_PREFIX[m[1].toUpperCase()];
      if (!p) { return part; }
      var rest = m[2].toLowerCase();
      return !rest || rest === p || rest === "volume" ? p : p + ", " + rest;
    }).filter(Boolean).join("; ");
  }

  var MONTH_IX = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };
  function shortDur(min) { var h = Math.floor(min / 60), m = min % 60; return !h ? m + " min" : h + " h" + (m ? " " + m : ""); }
  // The big number on a program row and its small label. Same rule as prerender_home.event_figure.
  function eventFigure(ev, tz) {
    var f = ev.fields || {};
    var sc = ev.kind === "closure" && A.closureSchedule(ev, tz, atMs());
    if (sc) { return sc.in_window ? { big: "Closed overnight", small: "reopens about " + sc.reopen + " local time" } : { big: "Open now", small: "closes again about " + sc.close + " local time" }; }
    if (ev.kind === "closure") {
      var mt = /([A-Z][a-z]{2}) (\d{1,2}) at (\d{2}):(\d{2}) UTC/.exec(String(f.reopen || ""));
      if (mt && MONTH_IX.hasOwnProperty(mt[1])) {
        var now = new Date(), y = now.getUTCFullYear();
        if (MONTH_IX[mt[1]] < now.getUTCMonth() - 6) { y++; }
        var d = new Date(Date.UTC(y, MONTH_IX[mt[1]], +mt[2], +mt[3], +mt[4]));
        var day = "";
        try { day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(d); } catch (e) { day = mt[1] + " " + mt[2]; }
        // AN34 r2: the big word is the state; the date sits in the small line, in the visitor's zone like every clock here.
        if (d.getTime() <= Date.now()) { return { big: "Closed", small: "listed to reopen " + day + ", " + fmtTime(d) + "; that time has passed, so it may have reopened" }; }
        // AN34 round 4: a listing days out is often a run of nightly closures, not one long shutdown.
        if (d.getTime() - Date.now() > 24 * 3600 * 1000) { return { big: "Closed", small: "FAA listing runs to " + day + ". A listing this long is often nightly closures; check the airport for its hours" }; }
        return { big: "Closed", small: "listed to reopen " + day + ", " + fmtTime(d) };
      }
      return { big: "Closed", small: "no reopening time listed" };
    }
    if (ev.kind === "ground_stop") {
      var endMs = ev.end_utc ? Date.parse(ev.end_utc) : NaN;
      if (isFinite(endMs) && endMs <= Date.now()) { return { big: "Stop", small: "listed to end " + fmtTime(new Date(endMs)) + "; that time has passed, so it may have lifted" }; }
      if (isFinite(endMs)) { var cd = A.countdown(endMs, Date.now()); return { big: fmtTime(new Date(endMs)), small: "listed end" + (cd ? ", " + cd : "") }; }
      if (f.end_time) { return { big: String(f.end_time).replace(/\.$/, ""), small: "listed end" }; }
      return { big: "Stop", small: "no end time listed" };
    }
    var avg = A.minutesOf(f.avg || ev.avg), mx = A.minutesOf(f.max || ev.max);
    if (avg != null) { return { big: shortDur(avg), small: (ev.kind === "ground_delay" ? "average hold" : "average delay") + (mx != null ? " \u00B7 longest " + A.fmtMinutes(mx) : "") }; }
    return { big: "Delays", small: "no size listed" };
  }

  function eventCard(ev) {
    var code = String(ev.airport || "").toUpperCase();
    var a = allByCode[code] || byCode[code] || {};
    var place = a.short || ev.display || code;
    var night = ev.kind === "closure" && A.closureSchedule(ev, ev.tz || a.tz, atMs());
    var stop = (ev.kind === "ground_stop" || ev.kind === "closure") && !night;
    var card = el("article", "event-card" + (night ? " event-card--night" : stop ? " event-card--stop" : ""));
    var head = el("div", "event-header");
    var h3 = el("h3", "event-title");
    var lk = el("a", "ev-link");
    lk.href = /^[A-Z]{3}$/.test(code) ? "airports/" + code + ".html" : "airports/index.html";
    lk.appendChild(el("span", "ev-code", code));
    lk.appendChild(el("span", "ev-place", a.name || ev.display || place));
    h3.appendChild(lk);
    head.appendChild(h3);
    head.appendChild(el("span", "badge " + (night ? "badge--night" : stop ? "badge--stop" : "badge--delay"), A.kindLabel(ev.kind, ev, ev.tz || a.tz, atMs())));
    card.appendChild(head);
    card.appendChild(el("p", "event-impact", nbspUnits(A.impactText(ev, place, isStaleIso(D.state.updated_utc), ev.tz || a.tz, atMs()))));
    if (ev.reason && String(ev.reason).toLowerCase() !== "closed") { card.appendChild(el("p", "event-reason", "Reason: " + reasonText(ev.reason))); }
    var fig = eventFigure(ev, ev.tz || a.tz);
    var big = el("p", "event-big");
    big.appendChild(el("b", null, nbspUnits(fig.big)));
    big.appendChild(el("small", null, fig.small));
    card.appendChild(big);
    var meta = el("p", "event-meta");
    var parts = [];
    parts.push("Source: " + ((ev.sources && ev.sources.length) ? ev.sources.join(", ") : "FAA"));
    meta.textContent = parts.join(" · ");
    card.appendChild(meta);
    return card;
  }

  // Latest: the desk's actionable ticker items (newest first). A line shows its source and age.
  // AN17: illustrations. Files and alt text are copied from assets/illustrations/library.json (a test checks this).
  // Only 'meaning' images are used here. The "Illustration" tag is always shown with the picture.
  var ILLUSTRATIONS = {
    "ground-stop": { "file": "ground-stop-2.webp", "alt": "Illustration: A plain aircraft silhouette stopped before a striped barrier on a taxiway." },
    "closure": { "file": "closure-1.webp", "alt": "Illustration: A runway outline with a big X across its centre line." },
    "delay": { "file": "delay-2.webp", "alt": "Illustration: One big round clock face without numerals beside a row of plain luggage carts." },
    "storm-hub": { "file": "storm-hub-2.webp", "alt": "Illustration: A large cloud with rain lines over a runway seen from the side." },
    "fog": { "file": "fog-4.webp", "alt": "Illustration: A row of runway lights shrinking into mist." },
    "wind": { "file": "wind-4.webp", "alt": "Illustration: A windsock and an airport tower in strong wind." },
    "snow-ice": { "file": "snow-ice-1.webp", "alt": "Illustration: Large flat snowflakes falling over a runway." },
    "holding": { "file": "holding-5.webp", "alt": "Illustration: An aircraft silhouette and a big dotted ring above clouds." },
    "holiday": { "file": "holiday-1.webp", "alt": "Illustration: A long row of plain suitcases in a line." },
    "tsa-record": { "file": "tsa-record-1.webp", "alt": "Illustration: A long row of plain grey trays on a conveyor belt." }
  };

  // Illustration category for one Latest item, from its kind, its tag, then whole words in its text. "" = none.
  function illustrationCategory(it) {
    var kind = String(it.kind || "").toLowerCase().replace(/[\s-]+/g, "_");
    if (kind === "ground_stop") { return "ground-stop"; }
    if (kind === "closure") { return "closure"; }
    if (kind === "delay" || kind === "ground_delay") { return "delay"; }
    if (kind === "owed") { return ""; }
    var hay = (String(it.tag || "") + " " + String(it.text || "")).toLowerCase();
    if (/\b(thunderstorms?|storms?|tornado(es)?)\b/.test(hay)) { return "storm-hub"; }
    if (/\b(fog|ifr|lifr)\b/.test(hay)) { return "fog"; }
    if (/\b(wind|winds|gusts?|gusty)\b/.test(hay)) { return "wind"; }
    if (/\b(snow|ice|icing|freezing)\b/.test(hay)) { return "snow-ice"; }
    if (/\bholding\b/.test(hay)) { return "holding"; }
    if (/\bground stops?\b/.test(hay)) { return "ground-stop"; }
    return "";
  }

  // A figure with a lazy 16:9 image and a visible "Illustration" tag. w/h are the display size in pixels.
  function illustrationFigure(cat, extraClass, w, h) {
    return null; // AN32: generic drawings are gone from the pages; the map above is kept for the tests
    var info = ILLUSTRATIONS[cat];
    if (!info) { return null; }
    var fig = el("figure", "illus " + extraClass);
    var img = document.createElement("img");
    img.src = "assets/illustrations/" + info.file;
    img.alt = info.alt;
    img.width = w;
    img.height = h;
    img.loading = "lazy";
    img.decoding = "async";
    // Offline and never visited: drop the picture, keep the text.
    img.addEventListener("error", function () { if (fig.parentNode) { fig.parentNode.removeChild(fig); } });
    fig.appendChild(img);
    fig.appendChild(el("figcaption", "illus-tag", "Illustration"));
    return fig;
  }

  function renderLatest() {
    var box = document.getElementById("latest-box"), list = document.getElementById("latest-list");
    if (!box || !list) { return; } // AN32: the home page no longer shows the Latest feed
    list.textContent = "";
    var items = D.state ? A.latestItems(D.state.ticker, 6, Date.now()) : [];
    box.hidden = !items.length;
    items.forEach(function (it) {
      var thumb = illustrationFigure(illustrationCategory(it), "illus--thumb", 96, 54);
      var li = el("li", "latest-item" + (thumb ? " latest-item--thumb" : ""));
      if (thumb) { li.appendChild(thumb); }
      li.appendChild(el("span", "latest-tag", it.tag || ""));
      li.appendChild(el("span", "latest-text", it.text));
      var when = it.as_of_utc || it.t_utc;
      li.appendChild(el("span", "latest-src", (it.src ? it.src + ", " : "") + ageText(when)));
      list.appendChild(li);
    });
  }

  function renderEvents() {
    var box = $("events");
    box.textContent = "";
    if (!D.state) { return; }
    var list = faaEvents();
    if (!list.length) {
      var staleNow = isStaleIso(D.state.updated_utc);
      box.appendChild(el("p", "empty-state", staleNow ? "No FAA delays or ground stops were listed " + asOfText(D.state.updated_utc) + "." : "No FAA delays or ground stops are listed right now."));
      return;
    }
    list.forEach(function (ev) { box.appendChild(eventCard(ev)); });
  }

  // ---------- 2: search and board ----------
  // Three columns on wide screens, two below 1000 px (the CSS grid matches).
  var BOARD_MQ = window.matchMedia ? window.matchMedia("(min-width: 1000px)") : null;
  var boardOpen = false, BOARD_FOLD = 8, quietOpen = null;
  function boardCols() { return BOARD_MQ && BOARD_MQ.matches ? 3 : 2; }
  if (BOARD_MQ) { try { BOARD_MQ.addEventListener("change", function () { renderBoard(); }); } catch (e) { /* old browser: keep the first layout */ } }

  // AN34: the board is rows of links: code, city, the last 24 hours, FAA status now. Trouble first, then traffic order.
  function renderBoard() {
    var box = $("board");
    box.textContent = "";
    var tiles = {};
    ((D.state && D.state.board) || []).forEach(function (t) { tiles[t.code] = t; });
    var weight = { red: 3, orange: 2, yellow: 1 };
    var ordered = airports.map(function (a, i) { return { a: a, i: i, w: (tiles[a.code] && weight[tiles[a.code].status]) || (a.level === "stop" ? 3 : a.level === "delay" ? 1 : 0) }; });
    ordered.sort(function (x, y) { return (y.w - x.w) || (x.i - y.i); }); // worst first, then the usual order
    var head = el("div", "bh");
    head.setAttribute("aria-hidden", "true");
    ["Code", "City", "Past 24 h", "FAA now"].forEach(function (h) { head.appendChild(el("span", null, h)); });
    // AN34 round 3: full rows only for airports with an FAA program now or in the last 24 h. The rest,
    // normal now and all day, fold into one compact grid of codes, so a calm day is not 30 rows of "Normal".
    var busy = ordered.filter(function (o) { return o.w > 0 || o.a.level !== "clear" || histTrouble(o.a.code); });
    var quiet = ordered.filter(function (o) { return busy.indexOf(o) < 0; });
    var ncol = boardCols();
    if (busy.length) {
      var cols = el("div", "board-cols");
      // AN34: on a phone the board opens with the first 10 (trouble first); one tap shows all of them.
      var total = busy.length, folded = ncol === 2 && !boardOpen && total > BOARD_FOLD;
      var shown = folded ? busy.slice(0, BOARD_FOLD) : busy;
      var nc = Math.min(ncol === 3 && shown.length <= 8 ? 2 : ncol, shown.length);
      var per = Math.ceil(shown.length / nc) || 1;
      for (var c = 0; c < nc; c++) {
        var col = el("div", "board-col");
        col.appendChild(head.cloneNode(true));
        shown.slice(c * per, (c + 1) * per).forEach(function (o) { col.appendChild(makeTile(o.a, tiles)); });
        if (col.childNodes.length > 1) { cols.appendChild(col); }
      }
      cols.className = "board-cols board-cols--" + cols.childNodes.length;
      box.appendChild(cols);
      if (folded) {
        var more = el("button", "board-open", "Show all " + total + " airports with a delay today");
        more.type = "button";
        more.addEventListener("click", function () { boardOpen = true; renderBoard(); markSelected(); });
        box.appendChild(more);
      }
    }
    if (quiet.length) {
      // AN34 r2: on phones the calm airports fold behind one line; wide screens open it.
      var qw = el("details", "board-quiet" + (busy.length ? "" : " board-quiet--only"));
      qw.open = quietOpen != null ? quietOpen : !!(BOARD_MQ && BOARD_MQ.matches);
      qw.addEventListener("toggle", function () { quietOpen = qw.open; });
      var qs = el("summary", "quiet-head");
      qs.appendChild(el("span", "quiet-n", String(quiet.length)));
      qs.appendChild(document.createTextNode(busy.length ? " more airports normal all day" : " airports, all normal all day"));
      qs.appendChild(el("span", "quiet-codes", quiet.slice(0, 8).map(function (o) { return o.a.code; }).join(" ") + (quiet.length > 8 ? " \u2026" : "")));
      qw.appendChild(qs);
      var qg = el("div", "quiet-grid");
      quiet.forEach(function (o) {
        var q = el("a", "tile qt");
        q.href = "airports/" + o.a.code + ".html";
        q.setAttribute("data-code", o.a.code);
        q.setAttribute("aria-label", o.a.code + ", " + (o.a.short || o.a.name) + ": normal. Open airport page.");
        if (o.a.code === currentCode) { q.setAttribute("aria-current", "true"); }
        q.appendChild(el("span", "qt-code", o.a.code));
        q.appendChild(el("span", "qt-name", o.a.short || o.a.name || o.a.code));
        qg.appendChild(q);
      });
      qw.appendChild(qg);
      box.appendChild(qw);
    }
    renderMine(tiles);
    var note = $("board-note");
    if (note) {
      note.textContent = "";
      note.appendChild(el("span", "key-lead", "Each strip is the past 24 hours, one bar an hour, oldest on the left:"));
      [["clear", "no FAA program"], ["delay", "delay"], ["stop", "ground stop or closure"], ["none", "no reading"]].forEach(function (k) {
        var key = el("span", "key");
        key.appendChild(el("i", "hh hh--" + k[0]));
        key.appendChild(document.createTextNode(k[1]));
        note.appendChild(key);
      });
      note.appendChild(el("span", "key-src", "Status: FAA. Last 24 h: our hourly copy of the FAA feed" + (D.hist && D.hist.generated_utc ? ", " + ageText(D.hist.generated_utc) : "") + "."));
    }
  }

  // AN32: airports saved in this browser only (localStorage, no account).
  var MINE_KEY = "atd.mine";
  function getMine() {
    try { var v = JSON.parse(window.localStorage.getItem(MINE_KEY) || "[]"); return Array.isArray(v) ? v.filter(function (c) { return allByCode[c]; }).slice(0, 8) : []; } catch (e) { return []; }
  }
  // The airport the visitor opened last, so the top of the page can show it again (this browser only).
  function getLast() { try { var c = window.localStorage.getItem("atd.last"); return c && allByCode[c] ? c : ""; } catch (e) { return ""; } }
  function setLast(code) { try { window.localStorage.setItem("atd.last", code); } catch (e) { /* storage blocked */ } }
  function setMine(list) { try { window.localStorage.setItem(MINE_KEY, JSON.stringify(list.slice(0, 8))); } catch (e) { /* storage blocked: the list lasts until the page closes */ } }
  function toggleMine(code) {
    var l = getMine(), i = l.indexOf(code);
    if (i >= 0) { l.splice(i, 1); } else { l.push(code); }
    setMine(l);
    renderBoard();
    renderCardLive();
  }
  function renderMine(tiles) {
    var wrap = $("mine"), box = $("mine-list");
    if (!wrap || !box) { return; }
    var l = getMine(), last = getLast();
    if (last && l.indexOf(last) < 0) { l = [last].concat(l).slice(0, 8); }
    wrap.hidden = !l.length;
    box.textContent = "";
    l.forEach(function (c) { box.appendChild(makeTile(allByCode[c], tiles)); });
  }

  function histTrouble(code) {
    var row = D.hist && D.hist.airports && D.hist.airports[code];
    return typeof row === "string" && /[ds]/.test(row.slice(-24));
  }

  function histCells(code) {
    var row = D.hist && D.hist.airports && D.hist.airports[code];
    var strip = el("span", "hist24");
    if (typeof row !== "string" || !row.length) { strip.classList.add("hist24--empty"); return strip; }
    var word = { c: "clear", d: "delay", s: "stop", "-": "none" };
    row.slice(-24).split("").forEach(function (ch) { strip.appendChild(el("i", "hh hh--" + (word[ch] || "none"))); });
    return strip;
  }

  function makeTile(a, tiles) {
    var lvl = A.LEVEL_RANK.hasOwnProperty(a.level) ? a.level : "clear";
    var tv = tiles[a.code] ? A.tileView(tiles[a.code]) : null;
    var b = el("a", "tile br tile--" + lvl + (tv ? " tile--" + tv.status : ""));
    b.href = "airports/" + a.code + ".html";
    b.setAttribute("data-code", a.code);
    var word = tv ? tv.word : LEVEL_WORD[lvl];
    b.setAttribute("aria-label", a.code + ", " + (a.short || a.name) + ": " + (lvl === "clear" ? "normal" : word) + (tv && tv.detail ? ", " + tv.detail : "") + (tv && tv.trendWord ? ", " + tv.trendWord : "") + ". Open airport page.");
    if (a.code === currentCode) { b.setAttribute("aria-current", "true"); }
    b.appendChild(el("span", "tile-code", a.code));
    b.appendChild(el("span", "tile-name", a.short || a.name || a.code));
    var h = histCells(a.code);
    h.setAttribute("aria-hidden", "true");
    b.appendChild(h);
    var st = el("span", "tile-level");
    if (lvl === "clear") {
      st.appendChild(el("span", "dot dot--clear"));
      // AN34 round 4: amber or red in the 24 h strip beside a clear airport means trouble earlier, now over; say so.
      st.appendChild(el("span", "tile-ok", histTrouble(a.code) ? "Clear now" : "Normal"));
    } else {
      var mins = null;
      (a.events || []).forEach(function (e) { var x = A.minutesOf(e && e.avg); if (x != null && (mins == null || x > mins)) { mins = x; } });
      var closed = (a.events || []).some(function (e) { return e && e.kind === "closure"; });
      st.appendChild(el("span", "badge badge--" + lvl, closed ? "Closed" : mins != null ? nbspUnits(shortDur(mins)) : word));
    }
    if (tv && tv.trendMark && lvl !== "clear") { st.appendChild(el("span", "tile-trend", { "\u2191": "worse", "\u2193": "better", "\u2192": "steady" }[tv.trendMark] || "")); }
    b.appendChild(st);
    return b;
  }

  function initSearch() {
    var input = $("airport-search"), list = $("search-results"), empty = $("search-empty");
    var res = [], active = 0;
    function go(a) { if (a) { setLast(a.code); window.location.href = "airports/" + a.code + ".html"; } }
    function draw() {
      list.textContent = "";
      res.forEach(function (a, i) {
        var li = el("li");
        var b = el("a", "result lvl-" + a.level + (i === active ? " is-active" : ""));
        b.href = "airports/" + a.code + ".html";
        b.setAttribute("data-code", a.code);
        b.appendChild(el("span", "result-code", a.code));
        b.appendChild(el("span", "result-name", (a.short || a.name) + (a.city ? ", " + a.city.split(", ").pop() : "")));
        b.appendChild(el("span", "result-level", a.level === "clear" ? "Normal" : (LEVEL_WORD[a.level] || "Normal")));
        b.addEventListener("click", function () { setLast(a.code); });
        li.appendChild(b);
        list.appendChild(li);
      });
    }
    function run() {
      var q = input.value;
      empty.hidden = true;
      if (!A.norm(q)) { res = []; list.hidden = true; list.textContent = ""; return; }
      res = A.searchAirports(allAirports, q).slice(0, 6);
      active = 0;
      if (!res.length) { list.hidden = true; list.textContent = ""; empty.hidden = false; return; }
      draw();
      list.hidden = false;
    }
    input.addEventListener("input", run);
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!res.length) { return; }
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + res.length) % res.length;
        draw();
      } else if (e.key === "Enter") {
        var all = res.length ? res : A.searchAirports(allAirports, input.value);
        if (all.length) { e.preventDefault(); list.hidden = true; go(all[Math.min(active, all.length - 1)]); }
      } else if (e.key === "Escape") { input.value = ""; run(); }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== input && !/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || "")) { e.preventDefault(); input.focus(); }
    });
  }

  // ---------- airport card ----------
  function link(href, text, cls) {
    var a = el("a", cls || "tap", text);
    var safe = A.safeUrl(href);
    if (safe) {
      a.href = safe;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    return a;
  }

  function cardUpdated() { return (D.cards && D.cards.updated_utc) || (D.state && D.state.updated_utc); }

  function appendFaaStatus(box, a) {
    var lvl = A.LEVEL_RANK.hasOwnProperty(a.level) ? a.level : "clear";
    var stale = isStaleIso(cardUpdated());
    var row = el("p", "card-status");
    if (stale) {
      row.appendChild(el("span", "badge badge--stale", staleChipText(lvl === "clear" ? "No FAA delays reported" : LEVEL_WORD[lvl], cardUpdated(), a.tz)));
    } else {
      row.appendChild(el("span", "badge badge--" + lvl, LEVEL_WORD[lvl]));
    }
    box.appendChild(row);
    var evs = a.events || [];
    if (!evs.length) {
      box.appendChild(el("p", null, stale
        ? "No FAA delay or ground stop was listed for " + (a.short || a.code) + " " + asOfText(cardUpdated(), a.tz) + "."
        : "No FAA delay or ground stop is listed for " + (a.short || a.code) + " right now."));
    }
    evs.forEach(function (ev) {
      box.appendChild(el("p", "event-impact", A.impactText(ev, a.short || a.code, stale)));
      var endMs = ev.end_utc ? Date.parse(ev.end_utc) : null;
      if (ev.kind === "ground_stop" && endMs != null) {
        var cd = A.countdown(endMs, Date.now());
        box.appendChild(el("p", "event-end", "Listed end: " + fmtTime(new Date(endMs), a.tz) + (cd ? " (" + cd + ")" : "")));
      }
    });
    if (a.reason) { box.appendChild(el("p", "event-reason", "Reason: " + reasonText(a.reason))); }
  }

  function wxLines(a) {
    var w = a.wx;
    if (!w || !w.now_text || ageMin(w.obs_utc) == null || ageMin(w.obs_utc) > 90) { return null; }
    var now = "Weather at " + fmtTime(new Date(Date.parse(w.obs_utc)), a.tz) + ": " + w.now_text;
    if (w.wind_kt != null) { now += ", wind " + Math.round(w.wind_kt) + " kt" + (w.gust_kt ? " gusting " + Math.round(w.gust_kt) : ""); }
    now += " (aviationweather.gov, " + ageText(w.obs_utc) + ")";
    var next3h = "";
    if (w.next3h_text) {
      if (!isStaleIso(cardUpdated())) {
        next3h = "Forecast, next 3 hours: " + w.next3h_text + " (aviationweather.gov TAF" + (w.taf_issue_utc ? ", issued " + ageText(w.taf_issue_utc) : "") + ")";
      } else if (!A.forecastExpired(w.next3h_text, w.taf_issue_utc || cardUpdated(), a.tz, Date.now())) {
        next3h = "Forecast issued " + fmtTime(new Date(Date.parse(w.taf_issue_utc || cardUpdated())), a.tz) + ": " + w.next3h_text + " (aviationweather.gov TAF)";
      }
    }
    return { now: now, next3h: next3h };
  }

  function faaPlainStatus(a, stale) {
    var evs = a.events || [];
    if (evs.length) {
      return evs.map(function (ev) { return A.impactText(ev, a.short || a.code, stale, a.tz, atMs()); }).join(" ");
    }
    if (a.level === "stop") { return "FAA ground stop in effect"; }
    if (a.level === "delay") { return "FAA delay program in effect"; }
    return "No FAA delay or ground stop";
  }

  function renderGuideNow(box, a) {
    if (!box) { return; }
    box.textContent = "";
    var upd = (D.cards && D.cards.updated_utc) || (D.state && D.state.updated_utc);
    box.appendChild(el("p", "guide-now-line", isStaleIso(upd)
      ? "Last known status, " + asOfText(upd, a.tz) + ": " + faaPlainStatus(a, true)
      : "Right now: " + faaPlainStatus(a) + " \u00B7 updated " + ageText(upd)));
  }

  function renderCardLive() {
    var r = cardRefs;
    if (!r) { return; }
    var a = byCode[currentCode];
    if (!a) { return; }
    var box = r.live;
    box.textContent = "";
    appendFaaStatus(box, a);
    var facts = el("ul", "facts");
    var t = fmtTime(new Date(), a.tz);
    if (t) { facts.appendChild(el("li", null, "Local time: " + t)); }
    facts.appendChild(el("li", null, (a.alerts && a.alerts.length) ? "NWS alert: " + a.alerts.join(", ") : "NWS alert: none listed. Alerts are checked only when the FAA reason is weather."));
    facts.appendChild(el("li", null, a.aircraft_near == null ? "Aircraft nearby: counted only while the airport has an active delay (adsb.lol)." : "Aircraft within 20 nm: " + a.aircraft_near + " (adsb.lol, ODbL)"));
    wxFacts(facts, a);
    var b = D.bts && D.bts.airports && D.bts.airports[a.code];
    if (b && b.ontime != null) {
      facts.appendChild(el("li", null, "On-time arrivals, " + D.bts.month_label + ": " + A.pct(b.ontime) + (b.ly_ontime != null ? " (" + D.bts.ly_month_label + ": " + A.pct(b.ly_ontime) + ")" : "") + " (BTS)"));
    }
    var upd = D.cards && D.cards.updated_utc || (D.state && D.state.updated_utc);
    facts.appendChild(el("li", null, (isStaleIso(upd) ? "FAA status last checked " : "FAA data ") + (isStaleIso(upd) ? ageText(upd) : A.oldText(ageMin(upd)))));
    box.appendChild(facts);
    renderGuideNow(r.guideNow, a);
  }

  // Weather, storm area and holding notes: each line names its source and age. Old readings are left out, not shown as current.
  function wxFacts(facts, a) {
    var wx = wxLines(a);
    if (wx) {
      facts.appendChild(el("li", null, wx.now));
      if (wx.next3h) { facts.appendChild(el("li", null, wx.next3h)); }
    }
    var s = a.storm;
    if (s && s.text && ageMin(s.as_of_utc) != null && ageMin(s.as_of_utc) <= 90) {
      facts.appendChild(el("li", "fact-note", "Storm area: " + s.text + " (NOAA SPC and aviationweather.gov, " + ageText(s.as_of_utc) + ")"));
    }
    var hd = a.holding;
    if (hd && hd.count >= 3 && ageMin(hd.as_of_utc) != null && ageMin(hd.as_of_utc) <= 25) {
      facts.appendChild(el("li", "fact-note", hd.count + " aircraft look to be holding near " + a.code + " (adsb.lol sampled, " + ageText(hd.as_of_utc) + "). A pattern in positions, not a reason."));
    }
  }

  function placeList(items, emptyText) {
    var ul = el("ul", "places");
    if (!items.length) { ul.appendChild(el("li", "places-empty", emptyText)); return ul; }
    items.forEach(function (p) {
      var li = el("li", "place");
      li.appendChild(el("span", "place-name", p.name));
      li.appendChild(el("span", "place-dist", p.km + " km (" + A.kmToMi(p.km) + " mi) from the airport"));
      if (p.website && A.safeUrl(p.website)) { li.appendChild(link(p.website, "Website", "tap place-link")); }
      ul.appendChild(li);
    });
    return ul;
  }

  function placesBlock(code, kind, title, emptyText) {
    var det = el("details", "stuck-details");
    var data = D.places && D.places.airports && D.places.airports[code];
    var items = data ? (data[kind] || []) : [];
    var sum = el("summary", null, title + (data ? " (" + items.length + ")" : ""));
    det.appendChild(sum);
    if (!data) { det.appendChild(el("p", "places-empty", "Places are not available right now.")); return det; }
    det.appendChild(placeList(items, emptyText));
    var asOf = D.places && D.places.fetched_utc ? " Data from " + String(D.places.fetched_utc).slice(0, 10) + "." : "";
    det.appendChild(el("p", "credit", "© OpenStreetMap contributors." + asOf + " Distances are straight-line. We show no prices and do not know what is available."));
    return det;
  }

  function renderCommitments(out, airlineId) {
    out.textContent = "";
    if (!D.commit) {
      out.appendChild(el("p", null, "The airline commitments are not available right now."));
    } else if (!airlineId) {
      out.appendChild(el("p", "hint", "Choose your airline to see what it has committed to."));
    } else {
      var v = A.commitmentView(D.commit, airlineId);
      if (v) {
        out.appendChild(el("h6", "airline-name", v.name));
        if (!v.listed) {
          out.appendChild(el("p", null, v.notListed));
        } else {
          out.appendChild(el("p", null, v.intro));
          var table = el("table", "commit-table");
          table.appendChild(el("caption", "sr-only", "What " + v.name + " has committed to"));
          var tb = el("tbody");
          v.rows.forEach(function (r) {
            var tr = el("tr");
            tr.appendChild(el("th", null, r.label)).setAttribute("scope", "row");
            var td = el("td");
            td.appendChild(el("span", "badge " + (r.committed ? "badge--yes" : "badge--no"), r.text));
            tr.appendChild(td);
            tb.appendChild(tr);
          });
          table.appendChild(tb);
          out.appendChild(table);
          out.appendChild(el("p", "small", v.scope));
          out.appendChild(el("p", "small", v.noNote));
        }
        out.appendChild(el("p", "refund-line", v.refund));
        out.appendChild(el("p", "small", v.source));
      }
    }
    out.appendChild(link(A.DOT_URL, "Open the DOT dashboard", "tap"));
  }

  function guideBlock(a) {
    var wrap = el("div", "guide-wrap");
    var det = el("details", "stuck-details airport-guide");
    var airportName = a.name || a.short || a.code;
    det.appendChild(el("summary", null, "Airport guide: " + airportName + " (" + a.code + ") · official pages"));

    var body = el("div", "guide-body");
    body.appendChild(el(
      "p",
      "guide-lead",
      "Official pages for " + airportName + " (" + a.code + "). This guide is independent and not affiliated with the airport or the FAA."
    ));

    var primaryRow = el("p", "guide-primary-row");
    var fullLink = el("a", "btn btn-primary guide-full-btn", "Open the full " + a.code + " page");
    fullLink.href = "airports/" + a.code + ".html";
    primaryRow.appendChild(fullLink);
    body.appendChild(primaryRow);

    var entry = D.guide && D.guide.airports && D.guide.airports[a.code];
    var checked = (D.guide && D.guide.checked_utc) ? String(D.guide.checked_utc).slice(0, 10) : "";

    if (!entry) {
      body.appendChild(el("p", "places-empty", "Official airport guide links are not available right now."));
    } else {
      var ul = el("ul", "guide-pills");
      var anyBlocked = false;
      (entry.links || []).forEach(function (item) {
        if (!item || !A.safeUrl(item.url)) { return; }
        var baseLabel = item.label || "Airport website";
        if (item.verified === false) { anyBlocked = true; }
        var li = el("li", "guide-pill-item");
        li.appendChild(link(item.url, baseLabel, "tap guide-pill"));
        ul.appendChild(li);
      });
      body.appendChild(ul);
      if (anyBlocked) {
        body.appendChild(el("p", "small guide-note", "Some airport sites block automatic checks, so we could not verify every link by script."));
      }
    }

    var nowBox = el("div", "guide-now");
    body.appendChild(nowBox);

    var stuckRow = el("p", "guide-stuck-row");
    var stuckLink = el("a", "tap guide-stuck-link", "Missed a flight? Open the I'm stuck guide");
    stuckLink.href = "stuck.html";
    stuckRow.appendChild(stuckLink);
    body.appendChild(stuckRow);

    det.appendChild(body);
    wrap.appendChild(det);

    var srcText = "Sources: Links from each airport operator's own website, FAA, NWS, aviationweather.gov" + (checked && !anyBlocked ? ". Last checked " + checked : "") + ".";
    wrap.appendChild(el("p", "credit guide-source", srcText));
    return { wrap: wrap, nowBox: nowBox };
  }

  function buildCard(a) {
    var code = a.code;
    var lvl = A.LEVEL_RANK.hasOwnProperty(a.level) ? a.level : "clear";
    var card = el("article", "airport-card airport-card--" + lvl);
    card.id = "card-" + code;
    var head = el("div", "card-head");
    head.appendChild(el("span", "card-code", code));
    var titles = el("div", "card-titles");
    titles.appendChild(el("h3", "card-title", (a.name || a.short) + " (" + code + ")"));
    if (a.city) { titles.appendChild(el("p", "card-city", a.city)); }
    head.appendChild(titles);
    var close = el("button", "btn btn-secondary btn-close", "Close");
    close.type = "button";
    close.addEventListener("click", closeAirport);
    head.appendChild(close);
    card.appendChild(head);

    var actions = el("p", "card-actions");
    var full = el("a", "btn btn-primary", "Open the " + code + " page");
    full.href = "airports/" + code + ".html";
    actions.appendChild(full);
    var save = el("button", "btn btn-secondary btn-save", getMine().indexOf(code) >= 0 ? "Remove from my airports" : "Save to my airports");
    save.type = "button";
    save.addEventListener("click", function () { toggleMine(code); save.textContent = getMine().indexOf(code) >= 0 ? "Remove from my airports" : "Save to my airports"; });
    actions.appendChild(save);

    var live = el("div", "card-live");
    card.appendChild(live);
    card.appendChild(actions);

    var fold = el("details", "card-more");
    fold.appendChild(el("summary", null, "Stuck at " + code + "? Rebooking, hotels, security lines and airline commitments"));
    var stuck = el("section", "stuck");
    stuck.setAttribute("aria-labelledby", "stuck-" + code);
    stuck.appendChild(el("h4", "stuck-title", "Stuck at the airport")).id = "stuck-" + code;

    stuck.appendChild(el("h5", null, "Rebook fast"));
    var ol = el("ol", "tips");
    A.rebookTips().forEach(function (t) { ol.appendChild(el("li", null, t)); });
    stuck.appendChild(ol);

    var guide = guideBlock(a);
    stuck.appendChild(guide.wrap);

    stuck.appendChild(el("h5", null, "Where to stay and rent a car"));
    stuck.appendChild(placesBlock(code, "hotels", "Hotels within 5 km", "No hotels with a name are listed in OpenStreetMap within 5 km."));
    stuck.appendChild(placesBlock(code, "cars", "Car rental within 5 km", "No car rental places are listed in OpenStreetMap within 5 km."));
    var hs = el("div"); hs.setAttribute("data-slot", "hotel-deals"); hs.hidden = true; stuck.appendChild(hs);
    var cs = el("div"); cs.setAttribute("data-slot", "car-deals"); cs.hidden = true; stuck.appendChild(cs);

    stuck.appendChild(el("h5", null, "Security line"));
    var sec = D.security && D.security[code];
    if (sec && A.safeUrl(sec.url)) {
      if (sec.verified === false) {
        stuck.appendChild(link(sec.url, "Airport website", "tap"));
        stuck.appendChild(el("p", "small", "Opens the airport's own website; look for its security wait times there. This site shows no wait numbers."));
      } else {
        stuck.appendChild(link(sec.url, "Check the official wait time", "tap"));
        stuck.appendChild(el("p", "small", "Opens the airport's own page. This site shows no wait numbers."));
      }
    } else {
      stuck.appendChild(el("p", "small", "No official wait page is listed for this airport."));
    }

    stuck.appendChild(el("h5", null, "What your airline has committed to"));
    var sel = el("select", "airline-select");
    sel.id = "airline-" + code;
    var lab = el("label", null, "Your airline");
    lab.setAttribute("for", sel.id);
    var o0 = el("option", null, "Choose your airline"); o0.value = "";
    sel.appendChild(o0);
    ((D.commit && D.commit.airlines) || []).forEach(function (al) {
      var o = el("option", null, al.name); o.value = al.id; sel.appendChild(o);
    });
    var out = el("div", "commit-out");
    out.setAttribute("aria-live", "polite");
    sel.addEventListener("change", function () { renderCommitments(out, sel.value); });
    stuck.appendChild(lab);
    stuck.appendChild(sel);
    stuck.appendChild(out);
    renderCommitments(out, "");

    stuck.appendChild(el("h5", null, "Owed something?"));
    stuck.appendChild(link(DOWNTIME_URL, "Delayed or cancelled? Check what you may be owed", "btn btn-primary"));
    fold.appendChild(stuck);
    card.appendChild(fold);

    cardRefs = { card: card, live: live, guideNow: guide.nowBox };
    return card;
  }

  function setUrl(code) {
    try {
      var url = code ? "?airport=" + encodeURIComponent(code) : window.location.pathname;
      window.history.replaceState(null, "", url);
    } catch (e) { /* no history access: ignore */ }
  }

  function openAirport(code, scroll) {
    var a = byCode[code];
    if (allByCode[code]) { setLast(code); }
    if (!a) {
      // An airport after the first 30 has no card on this page: open its own page.
      if (/^[A-Z]{3}$/.test(code || "") && allByCode[code]) { window.location.href = "airports/" + code + ".html"; }
      return;
    }
    var slot = $("airport-card-slot");
    currentCode = code;
    slot.textContent = "";
    slot.appendChild(buildCard(a));
    renderCardLive();
    markSelected();
    renderMap();
    setUrl(code);
    if (scroll) {
      var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      slot.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      try { slot.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
    }
  }

  function closeAirport() {
    $("airport-card-slot").textContent = "";
    cardRefs = null;
    currentCode = "";
    markSelected();
    renderMap();
    setUrl("");
  }

  function markSelected() {
    var tiles = $("board").querySelectorAll(".tile");
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].getAttribute("data-code") === currentCode) { tiles[i].setAttribute("aria-current", "true"); }
      else { tiles[i].removeAttribute("aria-current"); }
    }
  }

  // ---------- 4: comparisons ----------
  function compareCard(title, big, lines, source, illusCat, extraCls) {
    var c = el("article", "compare-card" + (extraCls ? " " + extraCls : ""));
    c.appendChild(el("h3", "compare-title", title));
    var fig = illusCat ? illustrationFigure(illusCat, "illus--card", 1280, 720) : null;
    if (fig) { c.appendChild(fig); }
    c.appendChild(el("p", "compare-big", big));
    lines.forEach(function (l) { c.appendChild(el("p", "compare-line", l)); });
    c.appendChild(el("p", "compare-source", source));
    return c;
  }

  function holidayCard(hv) {
    var c = el("article", "compare-card compare-card--wide holiday");
    c.appendChild(el("h3", "compare-title", "Thanksgiving week, this year and last"));
    var holFig = illustrationFigure("holiday", "illus--card", 1280, 720);
    if (holFig) { c.appendChild(holFig); }
    var dl = hv.daysTo > 0 ? hv.daysTo + (hv.daysTo === 1 ? " day" : " days") + " left" : hv.daysTo === 0 ? "Thanksgiving is today" : "Thanksgiving was " + (-hv.daysTo) + " days ago";
    c.appendChild(el("p", "compare-big", dl));
    c.appendChild(el("p", "compare-line", "Thanksgiving is " + fmtDay(hv.thanksgiving) + "." + (hv.rows.some(function (r) { return r.count != null; }) ? " Bars show people screened by TSA, in millions." : " TSA has not posted this year's counts for that week yet.")));
    var done = hv.rows.filter(function (r) { return r.count != null; }).length;
    // AN35: with no counted day this year the chart has nothing to show; leave the whole block out (the countdown and last year's busiest day stay).
    if (!done) {
      if (hv.busiest && hv.busiestCount) {
        var rec0 = hv.record && hv.record.date === hv.busiest;
        c.appendChild(el("p", "compare-line", "Last year's busiest day that week: " + fmtDayYear(hv.busiest) + ", " + million(hv.busiestCount) + (rec0 ? ", the TSA record." : ".")));
      }
      c.appendChild(el("p", "compare-source", "Source: TSA checkpoint numbers, updated " + fmtLocalDay(hv.fetched) + ". Last year lined up by days to Thanksgiving."));
      return c;
    }
    var grid = el("div", "hol-grid");
    grid.setAttribute("role", "img");
    grid.setAttribute("aria-label", "Bar chart of TSA people screened, " + fmtDay(hv.rows[0].date) + " to " + fmtDay(hv.rows[hv.rows.length - 1].date) + ", this year against last year. This year has " + done + " days counted so far. The table below has the numbers.");
    hv.rows.forEach(function (r) {
      var col = el("div", "hol-col" + (r.isThanksgiving ? " hol-col--day" : ""));
      var bars = el("div", "hol-bars");
      var ly = el("span", "hol-bar hol-bar--ly" + (r.isBusiest ? " hol-bar--busiest" : ""));
      ly.style.height = r.lyPct + "%";
      var now = el("span", "hol-bar hol-bar--now" + (r.nowPct == null ? " hol-bar--none" : ""));
      now.style.height = (r.nowPct == null ? 100 : r.nowPct) + "%";
      bars.appendChild(ly); bars.appendChild(now);
      col.appendChild(el("span", "hol-mark", r.isBusiest ? "\u25B2" : "\u00A0"));
      col.appendChild(bars);
      col.appendChild(el("span", "hol-dow", r.dow.slice(0, 2)));
      col.appendChild(el("span", "hol-num", String(r.day)));
      grid.appendChild(col);
    });
    c.appendChild(grid);
    // AN34 round 3: a 2-item key; days not counted yet have no bar; one takeaway line.
    var key = el("p", "hol-key");
    var k1 = el("span", "hol-k"); k1.appendChild(el("span", "hol-sw hol-sw--now")); k1.appendChild(document.createTextNode(" This year")); key.appendChild(k1);
    var k2 = el("span", "hol-k"); k2.appendChild(el("span", "hol-sw hol-sw--ly")); k2.appendChild(document.createTextNode(" Last year")); key.appendChild(k2);
    c.appendChild(key);
    if (hv.busiest && hv.busiestCount) {
      var rec = hv.record && hv.record.date === hv.busiest;
      c.appendChild(el("p", "compare-line", "\u25B2 Last year's busiest day: " + fmtDayYear(hv.busiest) + ", " + million(hv.busiestCount) + (rec ? ", the TSA record." : ".")));
    }
    var table = el("table", "sr-only");
    table.appendChild(el("caption", null, "TSA people screened, Thanksgiving week"));
    var hr = el("tr");
    ["Day", "This year", "Last year"].forEach(function (h) { var th2 = el("th", null, h); th2.setAttribute("scope", "col"); hr.appendChild(th2); });
    var thead = el("thead"); thead.appendChild(hr); table.appendChild(thead);
    var tb = el("tbody");
    hv.rows.forEach(function (r) {
      var tr = el("tr");
      tr.appendChild(el("th", null, r.dow + " " + fmtDay(r.date))).setAttribute("scope", "row");
      tr.appendChild(el("td", null, r.count == null ? "not counted yet" : million(r.count)));
      tr.appendChild(el("td", null, r.lyCount == null ? "n/a" : million(r.lyCount)));
      tb.appendChild(tr);
    });
    table.appendChild(tb);
    c.appendChild(table);
    c.appendChild(el("p", "compare-source", "Source: TSA checkpoint numbers, updated " + fmtLocalDay(hv.fetched) + ". Last year lined up by days to Thanksgiving."));
    return c;
  }

  function signed(p) { return (p > 0 ? "+" : "") + p.toFixed(1) + "%"; }

  function renderCompare() {
    var box = $("compare-cards");
    box.textContent = "";
    var t = D.tsa;
    if (t && t.latest_count) {
      var src = "Source: TSA checkpoint numbers, updated " + fmtLocalDay(t.fetched_utc);
      var pctDay = t.ly_count ? (t.latest_count / t.ly_count - 1) * 100 : null;
      // AN34: one big number, the same day last year, then the last 7 days as bars with last year's marks.
      var c = el("article", "compare-card tsa-card");
      c.appendChild(el("h3", "compare-title", "People screened, " + fmtDay(t.latest_date)));
      var big = el("p", "compare-big tsa-num", (t.latest_count / 1e6).toFixed(2));
      big.appendChild(el("span", null, " million"));
      c.appendChild(big);
      if (t.ly_count) {
        var ln = el("p", "compare-line", "Same weekday last year (" + fmtDay(t.ly_date) + "): " + million(t.ly_count) + " ");
        if (pctDay != null) { ln.appendChild(el("span", pctDay >= 0 ? "delta delta--up" : "delta delta--down", "(" + signed(pctDay) + ")")); }
        c.appendChild(ln);
      }
      var days = Array.isArray(t.last7) ? t.last7.filter(function (d) { return d && d.count; }) : [];
      if (days.length >= 3) {
        var max = 0;
        days.forEach(function (d) { max = Math.max(max, d.count, d.ly_count || 0); });
        var bars = el("div", "bars");
        bars.setAttribute("role", "img");
        bars.setAttribute("aria-label", "TSA checkpoint counts for the last " + days.length + " days, with the same days last year");
        days.forEach(function (d, i) {
          var b = el("div", "bar7" + (i === days.length - 1 ? " bar7--latest" : ""));
          var fill = el("i");
          fill.style.height = (d.count / max * 100).toFixed(1) + "%";
          if (d.ly_count) { var ly = el("span", "ly"); ly.style.bottom = Math.min(100, d.ly_count / d.count * 100).toFixed(1) + "%"; fill.appendChild(ly); }
          b.appendChild(fill);
          var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d.date || "");
          var dow = "";
          if (m) { try { dow = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" }).format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], 12))); } catch (e) { dow = ""; } }
          b.appendChild(el("small", null, dow));
          bars.appendChild(b);
        });
        c.appendChild(bars);
      }
      var extra = [];
      if (t.total7 && t.ly_total7) { extra.push("Last 7 days: " + million(t.total7) + (t.pct7 != null ? " (" + signed(t.pct7) + " on last year)" : "") + "."); }
      extra.push("Dashed line: the same day last year.");
      c.appendChild(el("p", "compare-line small", extra.join(" ")));
      c.appendChild(el("p", "compare-source", src));
      box.appendChild(c);
      var th = t.thanksgiving;
      var hv = A.holidayView(D.state && D.state.holiday, Date.now());
      if (hv) {
        box.appendChild(holidayCard(hv));
      } else if (th && th.days_to != null) {
        var l1 = th.days_to > 0 ? "Thanksgiving is " + fmtDay(th.date_this_year) + "." : "Thanksgiving was " + fmtDay(th.date_this_year) + ".";
        var l2 = th.busiest_date ? "Last year the busiest day of that week was " + fmtDay(th.busiest_date) + "." : "";
        box.appendChild(compareCard("Thanksgiving countdown", th.days_to > 0 ? th.days_to + (th.days_to === 1 ? " day" : " days") : "Now",
          [l1, l2].filter(Boolean), src));
      }
    }
    var b = D.bts;
    if (b && b.nation && b.nation.ontime != null) {
      // AN34 round 3: one card for the BTS month, with the month on the big numbers.
      var bc = el("article", "compare-card compare-card--bts");
      bc.appendChild(el("h3", "compare-title", "All US flights, " + b.month_label));
      var stat = function (big, label, ly) {
        var d = el("div", "bts-stat");
        var n = el("p", "compare-big", big);
        d.appendChild(n);
        d.appendChild(el("p", "bts-label", label));
        if (ly != null) { d.appendChild(el("p", "compare-line", b.ly_month_label + ": " + A.pct(ly))); }
        return d;
      };
      bc.appendChild(stat(A.pct(b.nation.ontime), "arrived on time", b.nation.ly_ontime));
      if (b.nation.cancel != null) { bc.appendChild(stat(A.pct(b.nation.cancel), "were cancelled", b.nation.ly_cancel)); }
      bc.appendChild(el("p", "compare-source", "Source: BTS On-Time Performance, " + b.month_label + ". On time: less than 15 minutes late."));
      box.appendChild(bc);
    }
    if (!box.childNodes.length) { box.appendChild(el("p", "empty-state", "Comparison numbers are not available right now.")); }
  }

  // ---------- 3: map (Albers projection, radar reprojection) ----------
  var DEG = Math.PI / 180;
  var PHI1 = 29.5 * DEG, PHI2 = 45.5 * DEG, PHI0 = 37.5 * DEG, LAMBDA0 = -96.0 * DEG;
  var AN = 0.5 * (Math.sin(PHI1) + Math.sin(PHI2));
  var AC = Math.cos(PHI1) * Math.cos(PHI1) + 2 * AN * Math.sin(PHI1);
  var ARHO0 = Math.sqrt(AC - 2 * AN * Math.sin(PHI0)) / AN;
  var bounds = null, mapMarkers = [], radarCache = null;

  function albers(lon, lat) {
    var phi = lat * DEG, lam = lon * DEG, theta = AN * (lam - LAMBDA0);
    var rho = Math.sqrt(Math.max(0, AC - 2 * AN * Math.sin(phi))) / AN;
    return [rho * Math.sin(theta), ARHO0 - rho * Math.cos(theta)];
  }
  function albersInv(x, y) {
    var dy = ARHO0 - y, rho = Math.sqrt(x * x + dy * dy), theta = Math.atan2(x, dy);
    var s = (AC - (rho * AN) * (rho * AN)) / (2 * AN);
    if (s < -1 || s > 1) { return null; }
    return [(LAMBDA0 + theta / AN) / DEG, Math.asin(s) / DEG];
  }
  function mainland(f) { var n = (f.properties && f.properties.name) || ""; return !(n === "Alaska" || n === "Hawaii" || n === "Puerto Rico"); }
  function polysOf(f) { var g = f.geometry || {}; return g.type === "Polygon" ? [g.coordinates] : (g.type === "MultiPolygon" ? g.coordinates : []); }
  function computeBounds(features) {
    var b = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
    features.forEach(function (f) {
      if (!mainland(f)) { return; }
      polysOf(f).forEach(function (poly) { poly.forEach(function (ring) { ring.forEach(function (pt) {
        var p = albers(pt[0], pt[1]);
        if (p[0] < b.minX) { b.minX = p[0]; } if (p[0] > b.maxX) { b.maxX = p[0]; }
        if (p[1] < b.minY) { b.minY = p[1]; } if (p[1] > b.maxY) { b.maxY = p[1]; }
      }); }); });
    });
    return b;
  }
  function fitFor(w, h) {
    var pad = 6, sx = bounds.maxX - bounds.minX || 1, sy = bounds.maxY - bounds.minY || 1;
    var scale = Math.min((w - pad * 2) / sx, (h - pad * 2) / sy);
    return { scale: scale, ox: (w - sx * scale) / 2, oy: (h - sy * scale) / 2 };
  }
  function project(fit, lon, lat) { var p = albers(lon, lat); return [fit.ox + (p[0] - bounds.minX) * fit.scale, fit.oy + (bounds.maxY - p[1]) * fit.scale]; }
  function unproject(fit, px, py) { return albersInv(bounds.minX + (px - fit.ox) / fit.scale, bounds.maxY - (py - fit.oy) / fit.scale); }

  function pathStates(ctx, fit) {
    D.geo.features.forEach(function (f) {
      if (!mainland(f)) { return; }
      polysOf(f).forEach(function (poly) {
        poly.forEach(function (ring) {
          for (var i = 0; i < ring.length; i++) {
            var p = project(fit, ring[i][0], ring[i][1]);
            if (i === 0) { ctx.moveTo(p[0], p[1]); } else { ctx.lineTo(p[0], p[1]); }
          }
          ctx.closePath();
        });
      });
    });
  }

  function buildRadar(w, h, fit) {
    var bbox = (D.radarMeta && D.radarMeta.bbox) || [-125, 24, -66, 50];
    var west = bbox[0], south = bbox[1], east = bbox[2], north = bbox[3];
    var img = D.radarImg, iw = img.naturalWidth, ih = img.naturalHeight;
    var src = document.createElement("canvas"); src.width = iw; src.height = ih;
    var sctx = src.getContext("2d"); sctx.drawImage(img, 0, 0);
    var sd = sctx.getImageData(0, 0, iw, ih).data;
    var out = document.createElement("canvas"); out.width = w; out.height = h;
    var octx = out.getContext("2d"), od = octx.createImageData(w, h), o = od.data;
    for (var py = 0; py < h; py++) {
      for (var px = 0; px < w; px++) {
        var ll = unproject(fit, px + 0.5, py + 0.5);
        if (!ll) { continue; }
        var lon = ll[0], lat = ll[1];
        if (lon < west || lon >= east || lat <= south || lat > north) { continue; }
        var sx = Math.floor((lon - west) / (east - west) * iw), sy = Math.floor((north - lat) / (north - south) * ih);
        var si = -1, best = -1;
        for (var dy = -1; dy <= 1; dy++) {
          var yy = sy + dy; if (yy < 0 || yy >= ih) { continue; }
          for (var dx = -1; dx <= 1; dx++) {
            var xx = sx + dx; if (xx < 0 || xx >= iw) { continue; }
            var k = (yy * iw + xx) * 4;
            if (sd[k + 3] === 0) { continue; }
            var score = sd[k] + sd[k + 1] * 0.6 - sd[k + 2] * 0.5;
            if (score > best) { best = score; si = k; }
          }
        }
        if (si < 0) { continue; }
        var r = sd[si], g = sd[si + 1], b = sd[si + 2], oi = (py * w + px) * 4;
        o[oi] = r; o[oi + 1] = g; o[oi + 2] = b; o[oi + 3] = (b > r && b > g) ? 150 : 255;
      }
    }
    octx.putImageData(od, 0, 0);
    var clipped = document.createElement("canvas"); clipped.width = w; clipped.height = h;
    var cctx = clipped.getContext("2d");
    cctx.beginPath(); pathStates(cctx, fit); cctx.clip();
    cctx.drawImage(out, 0, 0);
    return clipped;
  }

  // AN34: colours come from the theme tokens, so the map matches dark and light.
  function cssVar(name, fallback) {
    try { var v = window.getComputedStyle($("map") || document.documentElement).getPropertyValue(name).trim(); return v || fallback; } catch (e) { return fallback; }
  }
  var MARK_R = { clear: 4.5, delay: 8, stop: 8.5 };

  function markerLabel(a) {
    var closed = (a.events || []).some(function (e) { return e && e.kind === "closure"; });
    if (closed) { return "Closed"; }
    if (a.level === "stop") { return "Ground stop"; }
    var mins = null;
    (a.events || []).forEach(function (e) { var x = A.minutesOf(e && e.avg); if (x != null && (mins == null || x > mins)) { mins = x; } });
    return mins != null ? shortDur(mins) : "Delays";
  }

  function renderMap() {
    var canvas = $("map");
    if (!canvas || !D.geo || !bounds) { return; }
    var rect = canvas.getBoundingClientRect();
    var w = Math.round(rect.width), h = Math.round(rect.height);
    if (w < 40 || h < 40) { return; }
    var dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    }
    var col = {
      land: cssVar("--map-land", "#131b25"), edge: cssVar("--map-edge", "#2a3644"), ground: cssVar("--navy", "#080b0f"),
      text: cssVar("--board-text", "#f6f1e3"), muted: cssVar("--text-muted", "#a3afbd"),
      clear: cssVar("--green", "#3ccf91"), delay: cssVar("--amber", "#f5b301"), stop: cssVar("--red", "#ff5a47")
    };
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    var fit = fitFor(w, h);
    ctx.lineJoin = "round";
    ctx.fillStyle = col.land; ctx.strokeStyle = col.edge; ctx.lineWidth = 1;
    ctx.beginPath(); pathStates(ctx, fit); ctx.fill(); ctx.stroke();
    if (D.radarImg && D.radarImg.naturalWidth) {
      var key = [w, h, D.radarMeta && D.radarMeta.fetched_utc].join("|");
      if (!radarCache || radarCache.key !== key) { radarCache = { key: key, canvas: buildRadar(w, h, fit) }; }
      ctx.globalAlpha = 0.55; ctx.drawImage(radarCache.canvas, 0, 0, w, h); ctx.globalAlpha = 1;
      ctx.strokeStyle = col.edge; ctx.lineWidth = 0.8;
      ctx.beginPath(); pathStates(ctx, fit); ctx.stroke();
    }
    mapMarkers = [];
    var seen = {};
    function add(a) {
      if (seen[a.code] || typeof a.lat !== "number" || typeof a.lon !== "number") { return; }
      if (a.lat < 24 || a.lat > 50 || a.lon < -125.5 || a.lon > -66) { return; } // lower 48 only
      seen[a.code] = true;
      var p = project(fit, a.lon, a.lat);
      mapMarkers.push({ code: a.code, x: p[0], y: p[1], level: a.level, a: a });
    }
    airports.forEach(add);
    allAirports.forEach(function (a) { if (a.level === "stop" || a.level === "delay") { add(a); } });
    // AN34 r2: an FAA program at an airport with no card (the headline may lead with it) still gets a ringed, labelled dot.
    faaEvents().forEach(function (e) {
      var c = String(e.airport || "");
      if (!/^[A-Z]{3}$/.test(c) || seen[c] || A.closureSchedule(e, e.tz, atMs()) || typeof e.lat !== "number" || typeof e.lon !== "number") { return; }
      add({ code: c, lat: e.lat, lon: e.lon, level: e.kind === "closure" || e.kind === "ground_stop" ? "stop" : "delay", events: [{ kind: e.kind, avg: (e.fields || {}).avg }] });
    });
    canvas.setAttribute("data-markers", mapMarkers.map(function (m) { return m.code + ":" + Math.round(m.x) + ":" + Math.round(m.y); }).join(","));
    var order = { clear: 0, delay: 1, stop: 2 };
    mapMarkers.sort(function (x, y) { return (order[x.level] || 0) - (order[y.level] || 0); });
    var scale = Math.max(0.8, Math.min(1.3, w / 520));
    mapMarkers.forEach(function (m) {
      var r = (MARK_R[m.level] || MARK_R.clear) * scale;
      var c = col[m.level] || col.clear;
      if (m.level !== "clear") {
        ctx.beginPath(); ctx.arc(m.x, m.y, r * 2.4, 0, Math.PI * 2); ctx.globalAlpha = 0.18; ctx.fillStyle = c; ctx.fill(); ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(m.x, m.y, r * 1.6, 0, Math.PI * 2); ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.stroke();
      }
      if (m.code === currentCode) {
        ctx.beginPath(); ctx.arc(m.x, m.y, r + 6, 0, Math.PI * 2); ctx.strokeStyle = col.text; ctx.lineWidth = 2; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(m.x, m.y, r, 0, Math.PI * 2); ctx.fillStyle = c; ctx.fill();
    });
    // labels for airports with a program (and the open one): code in display type, status after it; they avoid each other
    var fs = Math.round(22 * scale), fs2 = Math.round(15 * scale);
    var placed = [];
    mapMarkers.filter(function (m) { return m.level !== "clear" || m.code === currentCode; }).reverse().forEach(function (m) {
      var sub = m.level === "clear" ? "" : markerLabel(m.a);
      ctx.font = "700 " + fs + "px 'Barlow Condensed', 'Arial Narrow', sans-serif";
      var w1 = ctx.measureText(m.code).width;
      ctx.font = "600 " + fs2 + "px 'Public Sans', Arial, sans-serif";
      var w2 = sub ? ctx.measureText(sub).width + 6 : 0;
      var bw = Math.ceil(w1 + w2) + 4, bh = fs + 4, off = 16 * scale;
      var cands = [[off, -bh / 2], [-off - bw, -bh / 2], [-bw / 2, -off - bh], [-bw / 2, off], [off, 6], [-off - bw, 6], [off, -bh - 8], [-off - bw, -bh - 8], [off, bh + 2], [-off - bw, bh + 2]];
      for (var i = 0; i < cands.length; i++) {
        var bx = Math.max(2, Math.min(w - bw - 2, m.x + cands[i][0])), by = Math.max(2, Math.min(h - bh - 2, m.y + cands[i][1]));
        var clash = placed.some(function (o) { return !(bx + bw + 3 <= o.x || o.x + o.w + 3 <= bx || by + bh + 3 <= o.y || o.y + o.h + 3 <= by); });
        if (clash) { continue; }
        placed.push({ x: bx, y: by, w: bw, h: bh });
        ctx.lineWidth = 4; ctx.strokeStyle = col.ground; ctx.textBaseline = "middle";
        ctx.font = "700 " + fs + "px 'Barlow Condensed', 'Arial Narrow', sans-serif";
        ctx.strokeText(m.code, bx + 2, by + bh / 2); ctx.fillStyle = col.text; ctx.fillText(m.code, bx + 2, by + bh / 2);
        if (sub) {
          ctx.font = "600 " + fs2 + "px 'Public Sans', Arial, sans-serif";
          ctx.strokeText(sub, bx + 2 + w1 + 6, by + bh / 2 + 1); ctx.fillStyle = col.muted; ctx.fillText(sub, bx + 2 + w1 + 6, by + bh / 2 + 1);
        }
        break;
      }
    });
    ctx.textBaseline = "alphabetic";
  }

  function initMap() {
    var canvas = $("map");
    canvas.addEventListener("click", function (e) {
      var rect = canvas.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top;
      var best = null, bd = 24;
      mapMarkers.forEach(function (m) { var d = Math.hypot(m.x - x, m.y - y); if (d <= bd) { bd = d; best = m; } });
      if (best && !byCode[best.code] && !allByCode[best.code]) { window.location.href = "airports/" + best.code + ".html"; return; }
      if (best) { openAirport(best.code, true); }
    });
    canvas.addEventListener("pointermove", function (e) {
      var rect = canvas.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top;
      canvas.style.cursor = mapMarkers.some(function (m) { return Math.hypot(m.x - x, m.y - y) <= 24; }) ? "pointer" : "default";
    });
    if (window.ResizeObserver) { new ResizeObserver(function () { renderMap(); }).observe(canvas); }
    else { window.addEventListener("resize", renderMap); }
    try { window.addEventListener("atd-theme", function () { renderMap(); }); } catch (e) { /* old browser */ }
    try { window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", function () { renderMap(); }); } catch (e) { /* old browser: keep the first colours */ }
    getJson("us-states.geojson").then(function (g) {
      if (g && g.features) { D.geo = g; bounds = computeBounds(g.features); renderMap(); }
    });
  }

  function loadRadar() {
    getJson("data/radar.json", true).then(function (meta) {
      if (!meta || (D.radarMeta && meta.fetched_utc === D.radarMeta.fetched_utc)) { return; }
      var img = new Image();
      img.onload = function () { D.radarImg = img; D.radarMeta = meta; renderMap(); };
      img.src = "data/radar.png?v=" + encodeURIComponent(meta.fetched_utc);
    });
  }

  // ---------- FA20: changed in the last hour ----------
  function levelName(l) { return l === "red" ? "ground stop" : A.STATUS_WORD.hasOwnProperty(l) ? A.STATUS_WORD[l].toLowerCase() : "clear"; }

  function renderChanged() {
    var sum = $("changed-summary"), list = $("changed-list"), note = $("changed-note");
    if (!sum) { return; }
    list.textContent = "";
    if (!D.state || !Array.isArray(D.state.board)) { return; }
    var r = A.changedLastHour(D.history, D.state.board, D.state.updated_utc);
    // AN34: on a quiet hour the block shrinks to one line and the 24 h chart takes the full width.
    var split = sum.closest ? sum.closest(".split") : null;
    if (split) { split.classList.toggle("split--quiet", !r.ok || !r.changes.length); }
    // AN34 r2: an empty "changed" block is noise; it shows only when an airport changed level.
    var csec = $("changed");
    if (csec) { csec.hidden = !r.ok || !r.changes.length; }
    if (!r.ok) {
      sum.textContent = "Not enough readings yet to compare with an hour ago.";
      note.textContent = "The site keeps one FAA reading per hour. This fills in after the next hourly reading. Source: FAA NAS status, " + ageText(D.state.updated_utc) + ".";
      return;
    }
    if (!r.changes.length) {
      sum.textContent = "No change. All " + r.compared + " airports are at the same level as an hour ago.";
    } else {
      sum.textContent = r.changes.length + (r.changes.length === 1 ? " airport has" : " airports have") + " changed level since the earlier reading.";
      r.changes.slice(0, 12).forEach(function (c) {
        var li = el("li", "change-item change-item--" + c.dir + (c.to === "red" ? " change-item--stop" : ""));
        li.appendChild(el("span", "change-code", c.code));
        li.appendChild(el("span", "change-text", levelName(c.from) + " to " + levelName(c.to) + " (" + c.dir + ")"));
        list.appendChild(li);
      });
      if (r.changes.length > 12) { list.appendChild(el("li", "change-item", "and " + (r.changes.length - 12) + " more")); }
    }
    note.textContent = "Compared with the FAA reading from " + fmtTime(new Date(Date.parse(r.baseT))) + " (" + A.durText(r.baseAgeMin) + " before the latest check). Source: FAA NAS status, " + ageText(D.state.updated_utc) + ".";
  }

  // ---------- FA20: 24 hour history chart ----------
  var SVGNS = (function () { var d = document.createElement("div"); d.innerHTML = "<svg></svg>"; return d.firstChild.namespaceURI; })();
  function svgEl(name, attrs, text) {
    var n = document.createElementNS(SVGNS, name);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) { n.textContent = text; }
    return n;
  }
  function hourLabel(ms) {
    try { return new Intl.DateTimeFormat(undefined, { hour: "numeric" }).format(new Date(ms)); } catch (e) { return ""; }
  }

  function renderHistory() {
    var box = $("hist-box");
    if (!box) { return; }
    var rows = A.historySeries(D.history);
    box.textContent = "";
    if (!rows.length) {
      box.appendChild(el("p", "empty-state", D.history ? "No hourly readings yet. The chart fills in as the hours pass." : "The hourly readings could not be loaded."));
      return;
    }
    var HOUR = 3600000, SLOTS = 24, W = 360, H = 190, L = 28, R = 352, T = 12, B = 152;
    var lastSlot = Math.floor(rows[rows.length - 1].ms / HOUR);
    var max = 0, peak = rows[0];
    rows.forEach(function (r) { if (r.notGreen > max) { max = r.notGreen; } if (r.notGreen > peak.notGreen) { peak = r; } });
    var ymax = Math.max(4, max), slotW = (R - L) / SLOTS, bw = Math.max(4, slotW - 4);
    function y(v) { return B - (B - T) * v / ymax; }
    var newest = rows[rows.length - 1];
    var summary = (A.isStale(ageMin(newest.t)) ? "At the latest hourly reading, " : "At the last hourly reading, ") + newest.notGreen + " of " + newest.total + " airports " + (newest.notGreen === 1 ? "was" : "were") + " not clear. The most in the last 24 hours was " + peak.notGreen + ", around " + hourLabel(peak.ms) + ". Source: FAA NAS status, hourly readings, latest " + ageText(newest.t) + ".";

    var svg = svgEl("svg", { "class": "hist-svg", viewBox: "0 0 " + W + " " + H, role: "img", "aria-labelledby": "hist-title hist-desc", focusable: "false" });
    svg.appendChild(svgEl("title", { id: "hist-title" }, "Airports not clear, by hour, last 24 hours"));
    svg.appendChild(svgEl("desc", { id: "hist-desc" }, summary + " The table below the chart lists every reading."));
    var ticks = [0, Math.round(ymax / 2), ymax].filter(function (v, i, a) { return a.indexOf(v) === i; });
    ticks.forEach(function (v) {
      svg.appendChild(svgEl("line", { "class": "hist-grid", x1: L, x2: R, y1: y(v), y2: y(v) }));
      svg.appendChild(svgEl("text", { x: L - 4, y: y(v) + 4, "text-anchor": "end" }, String(v)));
    });
    rows.forEach(function (r) {
      var k = SLOTS - 1 - (lastSlot - Math.floor(r.ms / HOUR));
      if (k < 0 || k >= SLOTS) { return; }
      var x = L + k * slotW + (slotW - bw) / 2;
      if (r.notGreen === 0) {
        svg.appendChild(svgEl("line", { "class": "hist-zero", x1: x, x2: x + bw, y1: B - 1, y2: B - 1 }));
        return;
      }
      var hAll = B - y(r.notGreen), hStop = B - y(r.stops);
      svg.appendChild(svgEl("rect", { "class": "hist-bar--delay", x: x, y: B - hAll, width: bw, height: hAll, rx: 1 }));
      if (r.stops) { svg.appendChild(svgEl("rect", { "class": "hist-bar--stop", x: x, y: B - hStop, width: bw, height: hStop, rx: 1 })); }
    });
    [0, 6, 12, 18, 23].forEach(function (k) {
      var ms = (lastSlot - (SLOTS - 1 - k)) * HOUR;
      svg.appendChild(svgEl("text", { x: L + k * slotW + slotW / 2, y: B + 16, "text-anchor": k === 0 ? "start" : k === 23 ? "end" : "middle" }, hourLabel(ms)));
    });
    svg.appendChild(svgEl("text", { x: R, y: H - 6, "text-anchor": "end" }, "Hours in your local time"));
    box.appendChild(svg);
    box.appendChild(el("p", "hist-note", summary));
    box.appendChild(el("p", "hist-note", "Red part of a bar: ground stops and closures. Amber part: delays. A green line: all clear. A missing bar: no reading for that hour."));

    var det = el("details", "hist-details");
    det.appendChild(el("summary", null, "Show the numbers as a table"));
    var wrap = el("div", "hist-table-wrap");
    var tb = el("table", "hist-table");
    tb.appendChild(el("caption", "sr-only", "Airports not clear, by hourly reading"));
    var th = el("thead"), hr = el("tr");
    ["Reading time", "Not clear", "Ground stops or closures", "Airports counted"].forEach(function (h) { var c = el("th", null, h); c.scope = "col"; hr.appendChild(c); });
    th.appendChild(hr); tb.appendChild(th);
    var body = el("tbody");
    rows.slice().reverse().forEach(function (r) {
      var tr = el("tr");
      var c0 = el("th", null, fmtTime(new Date(r.ms))); c0.scope = "row"; tr.appendChild(c0);
      tr.appendChild(el("td", null, String(r.notGreen)));
      tr.appendChild(el("td", null, String(r.stops)));
      tr.appendChild(el("td", null, String(r.total)));
      body.appendChild(tr);
    });
    tb.appendChild(body); wrap.appendChild(tb); det.appendChild(wrap);
    box.appendChild(det);
  }

  // ---------- loading ----------
  function renderLive() {
    buildAirports();
    renderFreshness();
    renderSummary();
    renderEvents();
    renderLatest();
    renderChanged();
    renderBoard();
    renderCardLive();
    renderMap();
    if (D.tsa || D.bts) { renderCompare(); }
  }

  function loadLive() {
    return Promise.all([getJson("data/state.json", true), getJson("data/airports.json", true), getJson("data/board-history.json", true)]).then(function (r) {
      if (r[0]) { D.state = r[0]; }
      D.history = r[2] || D.history;
      if (r[1]) { D.cards = r[1]; }
      // Merge: state.json is the truth for levels and events when airports.json lags behind it.
      if (D.state && D.cards && D.cards.updated_utc && D.state.updated_utc && D.cards.updated_utc < D.state.updated_utc && Array.isArray(D.state.board)) {
        D.state.board.forEach(function (b) {
          var c = D.cards.airports && D.cards.airports[b.code];
          if (c) { c.level = FALLBACK_LEVEL[b.level] || c.level; }
        });
      }
      renderLive();
      renderHistory();
      return null;
    });
  }

  function loadSlow() {
    return Promise.all([
      getJson("data/places.json"), getJson("data/security-waits.json"), getJson("data/dot-commitments.json"),
      getJson("data/bts.json", true), getJson("data/tsa.json", true), getJson("data/airport-guide.json"),
      getJson("data/history-summary.json", true)
    ]).then(function (r) {
      if (r[6] && r[6].airports) { D.hist = r[6]; renderBoard(); }
      D.places = r[0]; D.security = r[1]; D.commit = r[2];
      D.bts = (r[3] && r[3].nation) ? r[3] : null;
      D.tsa = r[4];
      D.guide = r[5];
      renderCompare();
      if (!slowLoaded && currentCode) { slowLoaded = true; openAirport(currentCode, false); }
      slowLoaded = true;
      renderCardLive();
      loadRadar();
      return null;
    });
  }

  function tick() {
    renderFreshness();
    renderEvents();
    renderLatest();
    renderChanged();
    renderCardLive();
  }

  function init() {
    initLive();
    initSearch();
    initMap();
    loadLive().then(function () {
      var code = A.airportFromSearch(window.location.search, Object.keys(allByCode));
      return loadSlow().then(function () { if (code) { openAirport(code, true); } });
    });
    // Poll only while the tab is visible; refresh at once when the viewer comes back.
    window.setInterval(function () { if (!document.hidden) loadLive(); }, REFRESH_MS);
    window.setInterval(tick, TICK_MS);
    window.setInterval(function () { if (!document.hidden) loadSlow(); }, SLOW_MS);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) loadLive(); });
  }

  init();
})();
