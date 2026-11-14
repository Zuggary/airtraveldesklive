(function () {
  "use strict";

  var A = window.ATD;
  var REFRESH_MS = 60000;
  var TICK_MS = 30000;
  var SLOW_MS = 30 * 60000;
  var STALE_MIN = 20;
  var TWITCH_SRC = "https://player.twitch.tv/?channel=airtraveldesklive&parent=www.airtraveldesklive.com&parent=airtraveldesklive.com&muted=true";
  var DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var LEVEL_WORD = { clear: "Clear", delay: "Delay", stop: "Ground stop" };
  var FALLBACK_LEVEL = { green: "clear", amber: "delay", red: "stop" };

  var D = { history: null, state: null, cards: null, places: null, guide: null, security: null, commit: null, bts: null, tsa: null, radarMeta: null, radarImg: null, geo: null };
  var airports = [];       // [{code, name, short, city, level, ...}] in board order
  var byCode = {};
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

  function million(n) { return (n / 1e6).toFixed(2) + " million"; }

  function ageMin(iso) {
    var ms = Date.parse(iso || "");
    return isFinite(ms) ? Math.max(0, Math.floor((Date.now() - ms) / 60000)) : null;
  }

  function ageText(iso) {
    var m = ageMin(iso);
    if (m == null) { return "time unknown"; }
    return m < 1 ? "less than 1 min ago" : m + " min ago";
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
    airports = list;
    byCode = {};
    list.forEach(function (a) { byCode[a.code] = a; });
  }

  function faaEvents() {
    var evs = (D.state && Array.isArray(D.state.events)) ? D.state.events : [];
    var rank = { ground_stop: 4, closure: 4, ground_delay: 3, delay: 2 };
    return evs.filter(function (e) { return e.source === "FAA" && rank[e.kind]; }).sort(function (a, b) {
      var d = rank[b.kind] - rank[a.kind];
      if (d) { return d; }
      return (A.minutesOf(b.fields && b.fields.avg) || 0) - (A.minutesOf(a.fields && a.fields.avg) || 0);
    });
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
    stale.textContent = text + " ";
    var a = document.createElement("a");
    a.className = "stale-link";
    a.href = "https://nasstatus.faa.gov";
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = "nasstatus.faa.gov";
    stale.appendChild(a);
    stale.hidden = false;
  }

  function oldText(m) {
    if (m == null) { return "of unknown age"; }
    return m >= 120 ? Math.floor(m / 60) + " hours old" : m + " minutes old";
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
    line.textContent = (m == null ? "Update time unavailable" : "Updated " + (m < 1 ? "less than 1 min" : m + " min") + " ago") + " · updates about every 5 minutes";
    var staleFeeds = (D.state.stale_feeds || []);
    if (staleFeeds.indexOf("FAA") >= 0) {
      // The job kept the last good FAA list because the FAA fetch failed; never present it as fresh.
      setStale(stale, "The FAA status list is " + oldText(m) + " and could not be refreshed, so it may be out of date. For the FAA's own page, go to");
    } else if (m == null || m > STALE_MIN) {
      setStale(stale, "This data is " + oldText(m) + ". It normally updates about every 5 minutes. For the FAA's own page, go to");
    } else {
      stale.hidden = true;
    }
  }

  function renderSummary() {
    var s = $("summary");
    if (!D.state) { s.textContent = "Unable to load the latest FAA status."; return; }
    s.textContent = A.nationalSummary(airports);
  }

  function eventCard(ev) {
    var code = String(ev.airport || "").toUpperCase();
    var a = byCode[code] || {};
    var place = a.short || ev.display || code;
    var stop = ev.kind === "ground_stop" || ev.kind === "closure";
    var card = el("article", "event-card" + (stop ? " event-card--stop" : ""));
    var head = el("div", "event-header");
    head.appendChild(el("h3", "event-title", place + " (" + code + ")"));
    head.appendChild(el("span", "badge " + (stop ? "badge--stop" : "badge--delay"), A.kindLabel(ev.kind)));
    card.appendChild(head);
    card.appendChild(el("p", "event-impact", A.impactText(ev, place)));
    if (ev.reason) { card.appendChild(el("p", "event-reason", "Reason: " + ev.reason)); }
    var f = ev.fields || {};
    var endMs = ev.end_utc ? Date.parse(ev.end_utc) : null;
    if (ev.kind === "ground_stop" && (endMs != null || f.end_time)) {
      var cd = endMs != null ? A.countdown(endMs, Date.now()) : "";
      var when = endMs != null ? "Listed end: " + fmtTime(new Date(endMs), ev.tz) : "Listed end: " + String(f.end_time).replace(/\.$/, "");
      card.appendChild(el("p", "event-end", when + (cd ? " (" + cd + ")" : "")));
    }
    var meta = el("p", "event-meta");
    var parts = [];
    var t = fmtTime(new Date(), ev.tz || a.tz);
    if (t) { parts.push("Local time " + t); }
    parts.push("Sources: " + ((ev.sources && ev.sources.length) ? ev.sources.join(", ") : "FAA"));
    parts.push("Checked " + ageText(D.state.updated_utc));
    meta.textContent = parts.join(" · ");
    card.appendChild(meta);
    var b = el("button", "btn btn-secondary", "Open " + code + " card: stuck at the airport?");
    b.type = "button";
    b.addEventListener("click", function () { openAirport(code, true); });
    card.appendChild(b);
    return card;
  }

  // Latest: the desk's actionable ticker items (newest first). A line shows its source and age.
  function renderLatest() {
    var box = $("latest-box"), list = $("latest-list");
    list.textContent = "";
    var items = D.state ? A.latestItems(D.state.ticker, 6) : [];
    box.hidden = !items.length;
    items.forEach(function (it) {
      var li = el("li", "latest-item");
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
      box.appendChild(el("p", "empty-state", "No FAA delays or ground stops are listed right now."));
      return;
    }
    list.forEach(function (ev) { box.appendChild(eventCard(ev)); });
  }

  // ---------- 2: search and board ----------
  function renderBoard() {
    var box = $("board");
    box.textContent = "";
    var tiles = {};
    ((D.state && D.state.board) || []).forEach(function (t) { tiles[t.code] = t; });
    airports.forEach(function (a) {
      var lvl = A.LEVEL_RANK.hasOwnProperty(a.level) ? a.level : "clear";
      var tv = tiles[a.code] ? A.tileView(tiles[a.code]) : null;
      var b = el("button", "tile tile--" + lvl + (tv ? " tile--" + tv.status : ""));
      b.type = "button";
      b.setAttribute("data-code", a.code);
      var word = tv ? tv.word : LEVEL_WORD[lvl];
      b.setAttribute("aria-label", a.code + ", " + (a.short || a.name) + ": " + word + (tv && tv.detail ? ", " + tv.detail : "") + (tv && tv.trendWord ? ", " + tv.trendWord : "") + ". Open airport card.");
      if (a.code === currentCode) { b.setAttribute("aria-current", "true"); }
      var top = el("span", "tile-top");
      top.appendChild(el("span", "tile-code", a.code));
      var right = el("span", "tile-level", word);
      if (tv && tv.trendMark) { right.appendChild(el("span", "tile-trend", " " + tv.trendMark)); }
      top.appendChild(right);
      b.appendChild(top);
      b.appendChild(el("span", "tile-name", a.short || a.name || a.code));
      if (tv) {
        // Delay bar: full width = 2 h of FAA average delay. Clear is an empty green outline.
        var bar = el("span", "bar bar--" + tv.status);
        bar.setAttribute("aria-hidden", "true");
        var fillEl = el("span", "bar-fill");
        fillEl.style.width = tv.fillPct + "%";
        bar.appendChild(fillEl);
        b.appendChild(bar);
        if (tv.detail) { b.appendChild(el("span", "tile-detail", tv.detail)); }
      }
      b.addEventListener("click", function () { openAirport(a.code, true); });
      box.appendChild(b);
    });
    var note = $("board-note");
    if (note) { note.textContent = "Bar = FAA average delay; a full bar is 2 hours. Arrow compares with an hour ago. Source: FAA, " + (D.state ? ageText(D.state.updated_utc) : "time unknown") + "."; }
  }

  function initSearch() {
    var input = $("airport-search"), list = $("search-results"), empty = $("search-empty");
    function run() {
      var q = input.value;
      list.textContent = "";
      empty.hidden = true;
      if (!A.norm(q)) { list.hidden = true; return; }
      var res = A.searchAirports(airports, q).slice(0, 6);
      if (!res.length) { list.hidden = true; empty.hidden = false; return; }
      res.forEach(function (a) {
        var li = el("li");
        var b = el("button", "result lvl-" + a.level);
        b.type = "button";
        b.setAttribute("data-code", a.code);
        b.appendChild(el("span", "result-code", a.code));
        b.appendChild(el("span", "result-name", (a.short || a.name) + (a.city ? ", " + a.city.split(", ").pop() : "")));
        b.appendChild(el("span", "result-level", LEVEL_WORD[a.level] || "Clear"));
        b.addEventListener("click", function () { list.hidden = true; openAirport(a.code, true); });
        li.appendChild(b);
        list.appendChild(li);
      });
      list.hidden = false;
    }
    input.addEventListener("input", run);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var res = A.searchAirports(airports, input.value);
        if (res.length) { e.preventDefault(); list.hidden = true; openAirport(res[0].code, true); }
      }
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

  function appendFaaStatus(box, a) {
    var lvl = A.LEVEL_RANK.hasOwnProperty(a.level) ? a.level : "clear";
    var row = el("p", "card-status");
    row.appendChild(el("span", "badge badge--" + lvl, LEVEL_WORD[lvl]));
    box.appendChild(row);
    var evs = a.events || [];
    if (!evs.length) {
      box.appendChild(el("p", null, "No FAA delay or ground stop is listed for " + (a.short || a.code) + " right now."));
    }
    evs.forEach(function (ev) {
      box.appendChild(el("p", "event-impact", A.impactText(ev, a.short || a.code)));
      var endMs = ev.end_utc ? Date.parse(ev.end_utc) : null;
      if (ev.kind === "ground_stop" && endMs != null) {
        var cd = A.countdown(endMs, Date.now());
        box.appendChild(el("p", "event-end", "Listed end: " + fmtTime(new Date(endMs), a.tz) + (cd ? " (" + cd + ")" : "")));
      }
    });
    if (a.reason) { box.appendChild(el("p", "event-reason", "Reason: " + a.reason)); }
  }

  function wxLines(a) {
    var w = a.wx;
    if (!w || !w.now_text || ageMin(w.obs_utc) == null || ageMin(w.obs_utc) > 90) { return null; }
    var now = "Weather at " + fmtTime(new Date(Date.parse(w.obs_utc)), a.tz) + ": " + w.now_text;
    if (w.wind_kt != null) { now += ", wind " + Math.round(w.wind_kt) + " kt" + (w.gust_kt ? " gusting " + Math.round(w.gust_kt) : ""); }
    now += " (aviationweather.gov, " + ageText(w.obs_utc) + ")";
    var next3h = w.next3h_text
      ? "Forecast, next 3 hours: " + w.next3h_text + " (aviationweather.gov TAF" + (w.taf_issue_utc ? ", issued " + ageText(w.taf_issue_utc) : "") + ")"
      : "";
    return { now: now, next3h: next3h };
  }

  function faaPlainStatus(a) {
    var evs = a.events || [];
    if (evs.length) {
      return evs.map(function (ev) { return A.impactText(ev, a.short || a.code); }).join(" ");
    }
    if (a.level === "stop") { return "FAA ground stop in effect"; }
    if (a.level === "delay") { return "FAA delay program in effect"; }
    return "No FAA delay or ground stop";
  }

  function renderGuideNow(box, a) {
    if (!box) { return; }
    box.textContent = "";
    var upd = (D.cards && D.cards.updated_utc) || (D.state && D.state.updated_utc);
    box.appendChild(el("p", "guide-now-line", "Right now: " + faaPlainStatus(a) + " \u00B7 updated " + ageText(upd)));
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
    facts.appendChild(el("li", null, "Status checked " + ageText(upd)));
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
      (entry.links || []).forEach(function (item) {
        if (!item || !A.safeUrl(item.url)) { return; }
        var baseLabel = item.label || "Airport website";
        var unchecked = item.verified === false;
        var text = unchecked ? baseLabel + " (unchecked)" : baseLabel;
        var li = el("li", "guide-pill-item");
        var aLink = link(item.url, text, "tap guide-pill");
        if (unchecked) {
          var note = baseLabel + " — we could not check this link by script";
          aLink.title = note;
          aLink.setAttribute("aria-label", note);
        }
        li.appendChild(aLink);
        ul.appendChild(li);
      });
      body.appendChild(ul);
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

    var srcText = "Sources: Links from each airport operator's own website, FAA, NWS, aviationweather.gov" + (checked ? ". Last checked " + checked : "") + ".";
    wrap.appendChild(el("p", "credit guide-source", srcText));
    return { wrap: wrap, nowBox: nowBox };
  }

  function buildCard(a) {
    var code = a.code;
    var card = el("article", "airport-card");
    card.id = "card-" + code;
    var head = el("div", "card-head");
    var titles = el("div");
    titles.appendChild(el("h3", "card-title", (a.name || a.short) + " (" + code + ")"));
    if (a.city) { titles.appendChild(el("p", "card-city", a.city)); }
    head.appendChild(titles);
    var close = el("button", "btn btn-secondary btn-close", "Close");
    close.type = "button";
    close.addEventListener("click", closeAirport);
    head.appendChild(close);
    card.appendChild(head);

    var live = el("div", "card-live");
    card.appendChild(live);

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
    card.appendChild(stuck);

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
    if (!a) { return; }
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
  function compareCard(title, big, lines, source) {
    var c = el("article", "compare-card");
    c.appendChild(el("h3", "compare-title", title));
    c.appendChild(el("p", "compare-big", big));
    lines.forEach(function (l) { c.appendChild(el("p", "compare-line", l)); });
    c.appendChild(el("p", "compare-source", source));
    return c;
  }

  function holidayCard(hv) {
    var c = el("article", "compare-card compare-card--wide holiday");
    c.appendChild(el("h3", "compare-title", "Thanksgiving week, this year and last"));
    var dl = hv.daysTo > 0 ? hv.daysTo + (hv.daysTo === 1 ? " day" : " days") + " left" : hv.daysTo === 0 ? "Thanksgiving is today" : "Thanksgiving was " + (-hv.daysTo) + " days ago";
    c.appendChild(el("p", "compare-big", dl));
    c.appendChild(el("p", "compare-line", "Thanksgiving is " + fmtDay(hv.thanksgiving) + ". Bars show people screened by TSA, in millions."));
    var grid = el("div", "hol-grid");
    grid.setAttribute("role", "img");
    var done = hv.rows.filter(function (r) { return r.count != null; }).length;
    grid.setAttribute("aria-label", "Bar chart of TSA people screened, " + fmtDay(hv.rows[0].date) + " to " + fmtDay(hv.rows[hv.rows.length - 1].date) + ", this year against last year. This year has " + done + " days counted so far. The table below has the numbers.");
    hv.rows.forEach(function (r) {
      var col = el("div", "hol-col" + (r.isThanksgiving ? " hol-col--day" : ""));
      var bars = el("div", "hol-bars");
      var ly = el("span", "hol-bar hol-bar--ly" + (r.isBusiest ? " hol-bar--busiest" : ""));
      ly.style.height = r.lyPct + "%";
      var now = el("span", "hol-bar hol-bar--now" + (r.nowPct == null ? " hol-bar--none" : ""));
      now.style.height = (r.nowPct == null ? 100 : r.nowPct) + "%";
      bars.appendChild(ly); bars.appendChild(now);
      col.appendChild(el("span", "hol-mark", r.isRecord ? "\u2605" : r.isBusiest ? "\u25B2" : "\u00A0"));
      col.appendChild(bars);
      col.appendChild(el("span", "hol-dow", r.dow.slice(0, 2)));
      col.appendChild(el("span", "hol-num", String(r.day)));
      grid.appendChild(col);
    });
    c.appendChild(grid);
    var key = el("p", "hol-key");
    key.appendChild(el("span", "hol-sw hol-sw--now"));
    key.appendChild(document.createTextNode(" This year  "));
    key.appendChild(el("span", "hol-sw hol-sw--ly"));
    key.appendChild(document.createTextNode(" Last year  "));
    key.appendChild(el("span", "hol-sw hol-sw--none"));
    key.appendChild(document.createTextNode(" Not counted yet  \u2605 TSA record day  \u25B2 Last year's busiest day"));
    c.appendChild(key);
    if (hv.busiest && hv.busiestCount) {
      var rec = hv.record && hv.record.date === hv.busiest;
      c.appendChild(el("p", "compare-line", "Last year's busiest day that week: " + fmtDayYear(hv.busiest) + ", " + million(hv.busiestCount) + (rec ? ". It is also the TSA record day." : ".")));
    }
    if (hv.record && !(hv.busiest && hv.record.date === hv.busiest)) {
      c.appendChild(el("p", "compare-line", "TSA record day: " + fmtDayYear(hv.record.date) + ", " + million(hv.record.count) + "."));
    }
    var l = hv.latest;
    if (l && l.count) {
      c.appendChild(el("p", "compare-line", "Latest count: " + fmtDay(l.date) + ", " + million(l.count) + (l.pct != null ? " (" + signed(l.pct) + " against " + fmtDay(l.ly_date) + " last year)" : "") + "."));
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
    c.appendChild(el("p", "compare-source", "Source: TSA checkpoint numbers, updated " + fmtDay((hv.fetched || "").slice(0, 10)) + ". Last year's days are lined up by distance from Thanksgiving."));
    return c;
  }

  function signed(p) { return (p > 0 ? "+" : "") + p.toFixed(1) + "%"; }

  function renderCompare() {
    var box = $("compare-cards");
    box.textContent = "";
    var t = D.tsa;
    if (t && t.latest_count) {
      var src = "Source: TSA checkpoint numbers, updated " + fmtDay((t.fetched_utc || "").slice(0, 10));
      var pctDay = t.ly_count ? (t.latest_count / t.ly_count - 1) * 100 : null;
      box.appendChild(compareCard("People screened, " + fmtDay(t.latest_date), million(t.latest_count),
        [t.ly_count ? "Same weekday last year (" + fmtDay(t.ly_date) + "): " + million(t.ly_count) + (pctDay != null ? " (" + signed(pctDay) + ")" : "") : ""].filter(Boolean), src));
      if (t.total7 && t.ly_total7) {
        box.appendChild(compareCard("Last 7 days", million(t.total7),
          ["Same 7 days last year: " + million(t.ly_total7) + (t.pct7 != null ? " (" + signed(t.pct7) + ")" : "")], src));
      }
      if (t.record && t.record.count) {
        box.appendChild(compareCard("Record day", million(t.record.count),
          [fmtDayYear(t.record.date) + (t.latest_pct_of_record != null ? ". " + fmtDay(t.latest_date) + " was " + t.latest_pct_of_record.toFixed(0) + "% of the record." : "")],
          "Source: TSA checkpoint numbers since 2019, updated " + fmtDay((t.fetched_utc || "").slice(0, 10))));
      }
      var th = t.thanksgiving;
      var hv = A.holidayView(D.state && D.state.holiday);
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
      var bsrc = "Source: BTS On-Time Performance, " + b.month_label + ". On time means arriving less than 15 minutes late.";
      box.appendChild(compareCard("On-time arrivals, all US flights", A.pct(b.nation.ontime),
        [b.nation.ly_ontime != null ? b.ly_month_label + ": " + A.pct(b.nation.ly_ontime) : ""].filter(Boolean), bsrc));
      if (b.nation.cancel != null) {
        box.appendChild(compareCard("Cancelled flights", A.pct(b.nation.cancel),
          [b.nation.ly_cancel != null ? b.ly_month_label + ": " + A.pct(b.nation.ly_cancel) : ""].filter(Boolean), bsrc));
      }
      var cs = (b.carriers || []).filter(function (c) { return c.ontime != null; }).slice(0, 6);
      if (cs.length) {
        var c = el("article", "compare-card compare-card--wide");
        c.appendChild(el("h3", "compare-title", "On-time arrivals by airline"));
        var table = el("table", "mini-table");
        table.appendChild(el("caption", "sr-only", "On-time arrivals by airline, " + b.month_label));
        var thead = el("thead"), hr = el("tr");
        ["Airline", b.month_label, b.ly_month_label].forEach(function (h) { var th2 = el("th", null, h); th2.setAttribute("scope", "col"); hr.appendChild(th2); });
        thead.appendChild(hr); table.appendChild(thead);
        var tb = el("tbody");
        cs.forEach(function (x) {
          var tr = el("tr");
          tr.appendChild(el("th", null, x.name)).setAttribute("scope", "row");
          tr.appendChild(el("td", null, A.pct(x.ontime)));
          tr.appendChild(el("td", null, x.ly_ontime != null ? A.pct(x.ly_ontime) : "n/a"));
          tb.appendChild(tr);
        });
        table.appendChild(tb);
        c.appendChild(table);
        c.appendChild(el("p", "compare-source", "Source: BTS On-Time Performance, " + b.month_label + ". The six airlines with the most flights."));
        box.appendChild(c);
      }
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

  var MARK = { clear: { fill: "#34d399", r: 5 }, delay: { fill: "#f2b33d", r: 8 }, stop: { fill: "#ef4444", r: 9 } };

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
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    var fit = fitFor(w, h);
    ctx.fillStyle = "#112240"; ctx.strokeStyle = "#3a5a92"; ctx.lineWidth = 1;
    ctx.beginPath(); pathStates(ctx, fit); ctx.fill(); ctx.stroke();
    if (D.radarImg && D.radarImg.naturalWidth) {
      var key = [w, h, D.radarMeta && D.radarMeta.fetched_utc].join("|");
      if (!radarCache || radarCache.key !== key) { radarCache = { key: key, canvas: buildRadar(w, h, fit) }; }
      ctx.globalAlpha = 0.85; ctx.drawImage(radarCache.canvas, 0, 0, w, h); ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(90, 120, 170, 0.9)"; ctx.lineWidth = 0.8;
      ctx.beginPath(); pathStates(ctx, fit); ctx.stroke();
    }
    mapMarkers = [];
    airports.forEach(function (a) {
      if (typeof a.lat !== "number" || typeof a.lon !== "number") { return; }
      var p = project(fit, a.lon, a.lat);
      mapMarkers.push({ code: a.code, x: p[0], y: p[1], level: a.level, a: a });
    });
    canvas.setAttribute("data-markers", mapMarkers.map(function (m) { return m.code + ":" + Math.round(m.x) + ":" + Math.round(m.y); }).join(","));
    var order = { clear: 0, delay: 1, stop: 2 };
    mapMarkers.sort(function (x, y) { return (order[x.level] || 0) - (order[y.level] || 0); });
    mapMarkers.forEach(function (m) {
      var st = MARK[m.level] || MARK.clear;
      if (m.code === currentCode) {
        ctx.beginPath(); ctx.arc(m.x, m.y, st.r + 6, 0, Math.PI * 2); ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(m.x, m.y, st.r + 2, 0, Math.PI * 2); ctx.fillStyle = "rgba(7, 14, 28, 0.9)"; ctx.fill();
      ctx.beginPath(); ctx.arc(m.x, m.y, st.r, 0, Math.PI * 2); ctx.fillStyle = st.fill; ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = "#ffffff"; ctx.stroke();
    });
    // labels for airports with an event, placed so they avoid each other
    ctx.font = "700 14px system-ui, sans-serif";
    var placed = [];
    mapMarkers.filter(function (m) { return m.level !== "clear" || m.code === currentCode; }).reverse().forEach(function (m) {
      var bw = Math.ceil(ctx.measureText(m.code).width) + 8, bh = 20;
      var cands = [[14, -10], [-14 - bw, -10], [-bw / 2, -34], [-bw / 2, 16], [14, 8], [-14 - bw, 8], [14, -30], [-14 - bw, -30]];
      for (var i = 0; i < cands.length; i++) {
        var bx = Math.max(2, Math.min(w - bw - 2, m.x + cands[i][0])), by = Math.max(2, Math.min(h - bh - 2, m.y + cands[i][1]));
        var clash = placed.some(function (o) { return !(bx + bw + 3 <= o.x || o.x + o.w + 3 <= bx || by + bh + 3 <= o.y || o.y + o.h + 3 <= by); });
        if (!clash) { placed.push({ x: bx, y: by, w: bw, h: bh }); ctx.fillStyle = "rgba(7, 14, 28, 0.92)"; ctx.fillRect(bx, by, bw, bh); ctx.fillStyle = "#f8fafc"; ctx.fillText(m.code, bx + 4, by + 15); break; }
      }
    });
  }

  function initMap() {
    var canvas = $("map");
    canvas.addEventListener("click", function (e) {
      var rect = canvas.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top;
      var best = null, bd = 24;
      mapMarkers.forEach(function (m) { var d = Math.hypot(m.x - x, m.y - y); if (d <= bd) { bd = d; best = m; } });
      if (best) { openAirport(best.code, true); }
    });
    canvas.addEventListener("pointermove", function (e) {
      var rect = canvas.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top;
      canvas.style.cursor = mapMarkers.some(function (m) { return Math.hypot(m.x - x, m.y - y) <= 24; }) ? "pointer" : "default";
    });
    if (window.ResizeObserver) { new ResizeObserver(function () { renderMap(); }).observe(canvas); }
    else { window.addEventListener("resize", renderMap); }
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
    note.textContent = "Compared with the FAA reading from " + fmtTime(new Date(Date.parse(r.baseT))) + " (" + r.baseAgeMin + " min before the latest check). Source: FAA NAS status, " + ageText(D.state.updated_utc) + ".";
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
    var summary = "Now " + newest.notGreen + " of " + newest.total + " airports are not clear. The most in the last 24 hours was " + peak.notGreen + ", around " + hourLabel(peak.ms) + ". Source: FAA NAS status, hourly readings, latest " + ageText(newest.t) + ".";

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
      getJson("data/bts.json", true), getJson("data/tsa.json", true), getJson("data/airport-guide.json")
    ]).then(function (r) {
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
      var code = A.airportFromSearch(window.location.search, Object.keys(byCode));
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
