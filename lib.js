/* Air Travel Desk: pure helpers (no DOM). Loaded by index.html before app.js and tested with node. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) { module.exports = api; }
  else { root.ATD = api; }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Extra words people type for an airport. A search aid only.
  var ALIASES = {
    ORD: "ohare o hare", LGA: "la guardia laguardia", DCA: "reagan national washington",
    IAD: "dulles washington", MDW: "midway", IAH: "bush intercontinental houston",
    JFK: "kennedy new york", EWR: "newark liberty new york", DFW: "dallas fort worth",
    ATL: "hartsfield jackson", SEA: "sea tac seatac", MSP: "saint paul st paul",
    BWI: "baltimore washington", LAS: "harry reid vegas", PHX: "sky harbor", FLL: "ft lauderdale hollywood"
  };

  function norm(s) {
    return String(s == null ? "" : s).toLowerCase().replace(/['’]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
  }

  // Search airports by code, city or name. Every typed word must start a word of the airport's text.
  // list items: {code, name, short, city}. Returns airports, best match first.
  function searchAirports(list, query) {
    var q = norm(query);
    if (!q) { return []; }
    var words = q.split(" ");
    var out = [];
    for (var i = 0; i < list.length; i++) {
      var a = list[i];
      var code = norm(a.code);
      var text = norm([a.short, a.city, a.name, ALIASES[String(a.code).toUpperCase()] || ""].join(" "));
      var tw = text.split(" ");
      var score = 0;
      if (q === code) { score = 100; }
      else if (code.indexOf(q) === 0 && q.length >= 2) { score = 80; }
      else {
        var all = true;
        for (var w = 0; w < words.length; w++) {
          var hit = false;
          for (var k = 0; k < tw.length; k++) { if (tw[k].indexOf(words[w]) === 0) { hit = true; break; } }
          if (!hit && words[w].length >= 3 && text.replace(/ /g, "").indexOf(words[w]) === 0) { hit = true; }
          if (!hit) { all = false; break; }
        }
        if (all) {
          score = 50;
          if (norm(a.short).indexOf(q) === 0 || norm(a.city).indexOf(q) === 0) { score = 60; }
        }
      }
      if (score) { out.push({ a: a, score: score, i: i }); }
    }
    out.sort(function (x, y) { return y.score - x.score || x.i - y.i; });
    return out.map(function (r) { return r.a; });
  }

  function minutesOf(text) {
    var h = /(\d+)\s*hours?/i.exec(text || ""), m = /(\d+)\s*minutes?/i.exec(text || "");
    if (!h && !m) { return null; }
    return (h ? parseInt(h[1], 10) * 60 : 0) + (m ? parseInt(m[1], 10) : 0);
  }

  function fmtMinutes(min) {
    if (min == null || !isFinite(min)) { return ""; }
    min = Math.round(min);
    var h = Math.floor(min / 60), m = min % 60;
    if (h && m) { return h + " h " + m + " min"; }
    if (h) { return h + " h"; }
    return m + " min";
  }

  // "2 hours and 18 minutes" -> "2 h 18 min"
  function fmtFaaDuration(text) {
    var m = minutesOf(text);
    return m == null ? String(text || "") : fmtMinutes(m);
  }

  // Ends-at countdown. endMs is null when the FAA gave no parsable end time.
  function countdown(endMs, nowMs) {
    if (endMs == null || !isFinite(endMs)) { return ""; }
    var diff = Math.round((endMs - nowMs) / 60000);
    if (diff <= 0) { return "past listed end time"; }
    return "ends in " + fmtMinutes(diff);
  }

  var LEVEL_RANK = { clear: 0, delay: 1, stop: 2 };

  // One line for the top of the page. airports: [{short, level, events:[{avg}]}]
  // ---------- age words (one rule everywhere; tools/prerender_text.py has the same) ----------
  var STALE_MIN = 30;
  function isStale(m) { return m == null || m > STALE_MIN; }
  function durText(m) {
    if (m == null) { return "age unknown"; }
    if (m < 60) { return m + " min"; }
    if (m < 1440) { var h = Math.floor(m / 60); return h === 1 ? "1 hour" : h + " hours"; }
    var d = Math.floor(m / 1440);
    return d === 1 ? "1 day" : d + " days";
  }
  function agoText(m) {
    if (m == null) { return "age unknown"; }
    return m < 1 ? "less than 1 min ago" : durText(m) + " ago";
  }
  function oldText(m) {
    if (m == null) { return "of unknown age"; }
    if (m < 60) { return m === 1 ? "1 minute old" : m + " minutes old"; }
    return durText(m) + " old";
  }

  // End time named in a forecast window ("clear through 2 am Pacific"), in ms. The first such clock time
  // after the issue time. null when the text has no clock time. Same rule as forecast_end in prerender_text.py.
  var ZONES = { eastern: "America/New_York", central: "America/Chicago", mountain: "America/Denver", pacific: "America/Los_Angeles", alaska: "America/Anchorage", hawaii: "Pacific/Honolulu" };
  function zoneParts(ms, zone) {
    var f = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" });
    var o = {};
    f.formatToParts(new Date(ms)).forEach(function (p) { o[p.type] = parseInt(p.value, 10); });
    return o;
  }
  function localToMs(y, mo, d, h, mi, zone) {
    var guess = Date.UTC(y, mo - 1, d, h, mi);
    for (var i = 0; i < 2; i++) {
      var p = zoneParts(guess, zone);
      guess += Date.UTC(y, mo - 1, d, h, mi) - Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute);
    }
    return guess;
  }
  function forecastEnd(text, issuedIso, tz) {
    var m = /\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b(?:\s+(eastern|central|mountain|pacific|alaska|hawaii))?/i.exec(String(text || ""));
    var issued = Date.parse(issuedIso || "");
    if (!m || !isFinite(issued)) { return null; }
    var zone = (m[4] && ZONES[m[4].toLowerCase()]) || tz;
    if (!zone) { return null; }
    try {
      var h = parseInt(m[1], 10) % 12 + (m[3].toLowerCase() === "pm" ? 12 : 0), mi = m[2] ? parseInt(m[2], 10) : 0;
      var base = zoneParts(issued, zone);
      for (var add = 0; add < 3; add++) {
        var day = new Date(Date.UTC(base.year, base.month - 1, base.day + add));
        var c = localToMs(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), h, mi, zone);
        if (c > issued) { return c; }
      }
    } catch (e) { return null; }
    return null;
  }
  // True when the forecast window has ended, or its end cannot be read.
  function forecastExpired(text, issuedIso, tz, nowMs) {
    var end = forecastEnd(text, issuedIso, tz);
    return end == null || end <= (nowMs == null ? Date.now() : nowMs);
  }

  // AN34: the home headline is a verdict over all the airports we cover, not a list of counts.
  // "98 of the 100 busiest US airports have no FAA delays right now". troubleLine names the exceptions.
  function isClosedAirport(a) { return a.level === "stop" && (a.events || []).some(function (e) { return e && e.kind === "closure"; }); }
  function nationalSummary(airports, asOf) {
    var bad = 0;
    for (var i = 0; i < airports.length; i++) { if (airports[i].level === "stop" || airports[i].level === "delay") { bad++; } }
    // AN34: when the data is old (asOf set) the headline is past tense and carries no time; the banner and the checked line date it.
    if (!bad) { return asOf ? "No delays or ground stops were listed at the " + (airports.length > 30 ? airports.length : 30) + " busiest airports" : "No delays or ground stops at the " + (airports.length > 30 ? airports.length : 30) + " busiest airports right now"; }
    var ok = airports.length - bad;
    return ok + " of the " + airports.length + " busiest US airports " + (asOf ? "had no FAA delays at the last check" : (ok === 1 ? "has" : "have") + " no FAA delays right now");
  }

  // One plain sentence per airport with an FAA program, worst first (closed, stop, then the longest delay). Max 3.
  function troubleRank(a) {
    var avg = 0;
    (a.events || []).forEach(function (e) { var m = minutesOf(e && e.avg); if (m != null && m > avg) { avg = m; } });
    return (isClosedAirport(a) ? 30000 : a.level === "stop" ? 20000 : 10000) + avg;
  }
  function troubleLine(airports, stale) {
    var list = airports.filter(function (a) { return a.level === "stop" || a.level === "delay"; });
    list.sort(function (x, y) { return troubleRank(y) - troubleRank(x); });
    var out = list.slice(0, 3).map(function (a) {
      var name = (a.short || a.name || a.code) + " (" + a.code + ")";
      if (isClosedAirport(a)) { return stale ? name + " was listed as closed." : name + " is closed."; }
      if (a.level === "stop") { return stale ? name + " had a ground stop." : name + " has a ground stop."; }
      var gd = null, avg = null;
      (a.events || []).forEach(function (e) {
        if (!e) { return; }
        if (e.kind === "ground_delay") { gd = e; }
        var m = minutesOf(e.avg); if (m != null && (avg == null || m > avg)) { avg = m; }
      });
      if (gd) { return "Flights to " + name + (stale ? " were" : " are") + " held" + (avg != null ? " about " + fmtMinutes(avg) : "") + "."; }
      return name + (stale ? " had" : " has") + " delays" + (avg != null ? " of about " + fmtMinutes(avg) : "") + ".";
    });
    if (list.length > 3) { out.push((list.length - 3) + (list.length - 3 === 1 ? " more airport has" : " more airports have") + " an FAA program."); }
    return out.join(" ");
  }

  function kindLabel(kind) {
    return ({ ground_stop: "Ground stop", ground_delay: "Ground delay", closure: "Airport closed", delay: "Delays" })[kind] || "Disruption";
  }

  // Plain-language impact for one FAA event. place: short airport name.
  function impactText(ev, place, stale) {
    var avg = fmtFaaDuration(ev.avg || (ev.fields && ev.fields.avg) || "");
    var max = fmtFaaDuration(ev.max || (ev.fields && ev.fields.max) || "");
    var dir = ev.direction || (ev.fields && ev.fields.direction) || "";
    if (ev.kind === "ground_stop") { return "Flights bound for " + place + " are held at their departure airports until the stop ends."; }
    if (ev.kind === "closure") { return stale ? place + " was listed as closed to flights." : place + " is closed to flights right now."; }
    if (ev.kind === "ground_delay") {
      var s = "Flights bound for " + place + " are held at their departure airports";
      if (avg) { s += ", about " + avg + " on average"; }
      if (max) { s += " and up to " + max; }
      return s + ".";
    }
    var d = dir ? dir.toLowerCase() + " " : "";
    var t = "Expect " + d + "delays at " + place;
    if (avg) { t += " of about " + avg; }
    return t + ".";
  }

  function safeUrl(u) {
    try {
      var p = new URL(String(u || ""));
      return (p.protocol === "https:" || p.protocol === "http:") ? p.href : "";
    } catch (e) { return ""; }
  }

  function airportFromSearch(search, validCodes) {
    var m = /[?&]airport=([A-Za-z]{3})(?:&|$)/.exec(search || "");
    if (!m) { return ""; }
    var code = m[1].toUpperCase();
    return !validCodes || validCodes.indexOf(code) >= 0 ? code : "";
  }

  var DOT_URL = "https://www.transportation.gov/airconsumer/airline-cancellation-delay-dashboard";
  var REFUND_LINE = "Refunds are a separate rule, 14 CFR 260.6, and it applies whatever the cause of the delay or cancellation.";
  var LABEL_ORDER = ["rebook_same", "rebook_other", "meal", "hotel", "transport", "cash", "voucher", "miles"];

  // Commitments for one airline from data/dot-commitments.json.
  // Returns {listed, name, rows:[{label, committed, text}], intro, notListed, refund, source, dotUrl}.
  function commitmentView(data, airlineId) {
    var airline = null, list = (data && data.airlines) || [];
    for (var i = 0; i < list.length; i++) { if (list[i].id === airlineId) { airline = list[i]; } }
    if (!airline) { return null; }
    var view = {
      name: airline.name, listed: !!airline.commitments, rows: [], intro: "", notListed: "",
      scope: "The dashboard covers delays and cancellations the airline causes, such as maintenance or crew problems. It does not say what an airline gives for weather or air traffic control.",
      noNote: "No commitment means the airline has not committed to it on the dashboard. It may still help at its own discretion.",
      refund: REFUND_LINE,
      source: "Source: U.S. Department of Transportation, Airline Cancellation and Delay Dashboard, last updated " + ((data && data.source_last_updated) || "unknown") + ".",
      dotUrl: DOT_URL
    };
    if (!airline.commitments) {
      view.notListed = airline.name + " is not listed on the DOT dashboard.";
      return view;
    }
    view.intro = "Your airline has committed to the items marked Committed, when it causes the delay or cancellation.";
    var labels = (data && data.commitment_labels) || {};
    for (var k = 0; k < LABEL_ORDER.length; k++) {
      var key = LABEL_ORDER[k];
      if (!(key in airline.commitments)) { continue; }
      var yes = airline.commitments[key] === true;
      view.rows.push({ key: key, label: labels[key] || key, committed: yes, text: yes ? "Committed" : "No commitment" });
    }
    return view;
  }

  function rebookTips() {
    return [
      "Ask the agent to rebook you on the next flight. You can also call the airline while you wait in line.",
      "Ask whether the airline has an earlier seat on a partner airline or from a nearby airport.",
      "Keep your boarding pass, receipts and a screenshot of the delay or cancellation notice for any refund or compensation request later."
    ];
  }

  function kmToMi(km) { return Math.round(km * 0.621371 * 10) / 10; }

  // ---------- AN12: board bars, trend, Thanksgiving card ----------
  var STATUS_WORD = { green: "Clear", yellow: "Delay", orange: "Ground delay", red: "Stop" };
  var TREND = {
    up: { mark: "\u2191", word: "worse than an hour ago" },
    down: { mark: "\u2193", word: "better than an hour ago" },
    flat: { mark: "\u2192", word: "about the same as an hour ago" }
  };

  // One board tile from state.json board[]: bar fill is the FAA average delay over 120 min (capped); clear is an empty bar.
  function tileView(t) {
    var status = STATUS_WORD.hasOwnProperty(t && t.status) ? t.status : "green";
    var fill = status === "green" ? 0 : Math.max(0, Math.min(1, Number(t && t.fill) || 0));
    var tr = (t && TREND[t.trend]) || null;
    if (tr && status === "green" && t.trend === "flat") { tr = null; }       // a flat clear airport needs no arrow
    var word = STATUS_WORD[status];
    if (status === "red" && t && t.text) { word = String(t.text).charAt(0).toUpperCase() + String(t.text).slice(1); }
    return {
      status: status, word: word, fillPct: Math.round(fill * 1000) / 10,
      detail: (status === "green" || status === "red") ? "" : String((t && t.text) || ""),
      trendMark: tr ? tr.mark : "", trendWord: tr ? tr.word : ""
    };
  }

  function millions(n) { return n == null || !isFinite(n) ? "" : (n / 1e6).toFixed(2); }

  // Thanksgiving card rows from state.holiday. A day with no count yet keeps count null (drawn as an empty outline, never zero).
  function holidayView(h) {
    if (!h || !h.days || !h.days.length) { return null; }
    var max = 0, rows = h.days.map(function (d) {
      if (d.count != null && d.count > max) { max = d.count; }
      if (d.ly_count != null && d.ly_count > max) { max = d.ly_count; }
      return d;
    }).map(function (d) {
      return {
        date: d.date, dow: d.dow, day: d.day, count: d.count, lyCount: d.ly_count, lyDate: d.ly_date,
        nowPct: d.count == null || !max ? null : Math.round(d.count / max * 1000) / 10,
        lyPct: d.ly_count == null || !max ? 0 : Math.round(d.ly_count / max * 1000) / 10,
        isBusiest: !!d.is_busiest, isRecord: !!d.is_record, isThanksgiving: !!d.is_thanksgiving
      };
    });
    return { rows: rows, max: max, daysTo: h.days_to, thanksgiving: h.thanksgiving, busiest: h.busiest_date, busiestCount: h.busiest_count,
             record: h.record || null, latest: h.latest || null, counted: h.counted_days || 0, fetched: h.fetched_utc };
  }

  // Latest list: newest first, the owed reminder left out (it has its own panel), the same words once.
  // nowMs (optional): weather lines whose forecast window has ended ("through 2 am Pacific (next 3 h)") are dropped.
  function latestItems(items, limit, nowMs) {
    var seen = {}, out = [];
    (items || []).slice().sort(function (a, b) { return String(b.t_utc || "").localeCompare(String(a.t_utc || "")); }).forEach(function (it) {
      if (!it || !it.text || it.kind === "owed" || seen[it.text]) { return; }
      if (nowMs != null && it.kind === "wx" && forecastExpired(it.text, it.as_of_utc || it.t_utc, "", nowMs)) { return; }
      seen[it.text] = true;
      out.push(it);
    });
    return out.slice(0, limit || 6);
  }

  // ---------- FA20: changed in the last hour, and the 24 h history chart ----------
  var RANK = { green: 0, yellow: 1, orange: 2, red: 3 };
  function rankOf(level) { return RANK.hasOwnProperty(level) ? RANK[level] : 0; }
  function levelOf(v) { return v && (v.status || v.level) || "green"; } // state.board has both: level is amber, status is orange; history readings have level only

  // Airports whose level differs from the history reading nearest to 60 minutes before the board time.
  // History readings are hourly, so a usable reading is 20 to 120 minutes old. board: state.board[] ({code, status}).
  function changedLastHour(history, board, nowIso) {
    var now = Date.parse(nowIso || "");
    var points = (history && Array.isArray(history.points)) ? history.points : [];
    if (!isFinite(now) || !Array.isArray(board) || !board.length) { return { ok: false, reason: "no board" }; }
    var best = null, bestGap = Infinity;
    points.forEach(function (p) {
      var t = Date.parse(p && p.t_utc || "");
      if (!isFinite(t) || !p.board) { return; }
      var age = (now - t) / 60000;
      if (age < 20 || age > 120) { return; }
      var gap = Math.abs(age - 60);
      if (gap < bestGap) { best = p; bestGap = gap; }
    });
    if (!best) { return { ok: false, reason: "no reading about an hour old" }; }
    var changes = [];
    board.forEach(function (b) {
      var before = best.board[b.code];
      if (!before) { return; }
      var from = levelOf(before), to = levelOf(b);
      if (rankOf(from) === rankOf(to)) { return; }
      changes.push({ code: b.code, name: b.name || b.code, from: from, to: to, dir: rankOf(to) > rankOf(from) ? "worse" : "better" });
    });
    changes.sort(function (a, b) {
      if (a.dir !== b.dir) { return a.dir === "worse" ? -1 : 1; }
      return rankOf(b.to) - rankOf(a.to) || (a.code < b.code ? -1 : 1);
    });
    return { ok: true, changes: changes, baseT: best.t_utc, baseAgeMin: Math.round((now - Date.parse(best.t_utc)) / 60000), compared: board.length };
  }

  // One entry per hourly reading in the last 24 h before the newest reading: how many airports are not green.
  function historySeries(history) {
    var points = (history && Array.isArray(history.points)) ? history.points : [];
    var rows = [];
    points.forEach(function (p) {
      var t = Date.parse(p && p.t_utc || "");
      if (!isFinite(t) || !p.board) { return; }
      var codes = Object.keys(p.board), bad = 0, stops = 0;
      codes.forEach(function (c) {
        var r = rankOf(levelOf(p.board[c]));
        if (r > 0) { bad++; }
        if (r === 3) { stops++; }
      });
      rows.push({ t: p.t_utc, ms: t, hour: p.hour_utc || "", total: codes.length, notGreen: bad, stops: stops });
    });
    rows.sort(function (a, b) { return a.ms - b.ms; });
    if (!rows.length) { return []; }
    var last = rows[rows.length - 1].ms;
    return rows.filter(function (r) { return last - r.ms < 24 * 3600 * 1000; });
  }

  // Source line for any "checked" time in sources.json: a UTC time, a day, or nothing.
  function checkedView(kind, checked, nowMs) {
    if (kind === "stream") { return { text: "Not read by the website", age: null }; }
    if (kind === "static") { return { text: "Static file", age: null }; }
    if (!checked) { return { text: "No time on file", age: null }; }
    if (/^\d{4}-\d{2}-\d{2}$/.test(checked)) { return { text: checked + " (checked on this date)", age: null }; }
    var ms = Date.parse(checked);
    if (!isFinite(ms)) { return { text: "No time on file", age: null }; }
    var m = Math.max(0, Math.floor(((nowMs == null ? Date.now() : nowMs) - ms) / 60000));
    var age = agoText(m);
    return { text: checked.replace("T", " ").replace("Z", " UTC"), age: age, minutes: m };
  }

  function pct(n, digits) { return (n == null || !isFinite(n)) ? "" : Number(n).toFixed(digits == null ? 1 : digits) + "%"; }

  return {
    norm: norm, searchAirports: searchAirports, minutesOf: minutesOf, fmtMinutes: fmtMinutes,
    fmtFaaDuration: fmtFaaDuration, countdown: countdown, nationalSummary: nationalSummary, troubleLine: troubleLine,
    kindLabel: kindLabel, impactText: impactText, safeUrl: safeUrl, airportFromSearch: airportFromSearch,
    commitmentView: commitmentView, rebookTips: rebookTips, kmToMi: kmToMi, pct: pct,
    tileView: tileView, holidayView: holidayView, latestItems: latestItems, millions: millions,
    changedLastHour: changedLastHour, historySeries: historySeries, checkedView: checkedView,
    STALE_MIN: STALE_MIN, isStale: isStale, durText: durText, agoText: agoText, oldText: oldText,
    forecastEnd: forecastEnd, forecastExpired: forecastExpired,
    STATUS_WORD: STATUS_WORD, LEVEL_RANK: LEVEL_RANK, DOT_URL: DOT_URL, REFUND_LINE: REFUND_LINE
  };
});
