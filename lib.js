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
  function nationalSummary(airports) {
    var stops = 0, delays = 0, best = null;
    for (var i = 0; i < airports.length; i++) {
      var a = airports[i];
      if (a.level === "stop") { stops++; }
      else if (a.level === "delay") { delays++; }
      var evs = a.events || [];
      for (var j = 0; j < evs.length; j++) {
        var mins = minutesOf(evs[j].avg);
        if (mins != null && (!best || mins > best.mins)) { best = { mins: mins, name: a.short || a.code }; }
      }
    }
    if (!stops && !delays) { return "No delays or ground stops at the 30 busiest airports right now"; }
    var parts = [];
    if (stops) { parts.push(stops + (stops === 1 ? " airport with a ground stop" : " airports with ground stops")); }
    if (delays) { parts.push(delays + (delays === 1 ? " airport with delays" : " airports with delays")); }
    var line = parts.join(" · ");
    if (best) { line += " · longest: " + best.name + ", avg " + fmtMinutes(best.mins); }
    return line;
  }

  function kindLabel(kind) {
    return ({ ground_stop: "Ground stop", ground_delay: "Ground delay", closure: "Airport closed", delay: "Delays" })[kind] || "Disruption";
  }

  // Plain-language impact for one FAA event. place: short airport name.
  function impactText(ev, place) {
    var avg = fmtFaaDuration(ev.avg || (ev.fields && ev.fields.avg) || "");
    var max = fmtFaaDuration(ev.max || (ev.fields && ev.fields.max) || "");
    var dir = ev.direction || (ev.fields && ev.fields.direction) || "";
    if (ev.kind === "ground_stop") { return "Flights bound for " + place + " are held at their departure airports until the stop ends."; }
    if (ev.kind === "closure") { return place + " is closed to flights right now."; }
    if (ev.kind === "ground_delay") {
      var s = "Flights bound for " + place + " are leaving late";
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
  function latestItems(items, limit) {
    var seen = {}, out = [];
    (items || []).slice().sort(function (a, b) { return String(b.t_utc || "").localeCompare(String(a.t_utc || "")); }).forEach(function (it) {
      if (!it || !it.text || it.kind === "owed" || seen[it.text]) { return; }
      seen[it.text] = true;
      out.push(it);
    });
    return out.slice(0, limit || 6);
  }

  function pct(n, digits) { return (n == null || !isFinite(n)) ? "" : Number(n).toFixed(digits == null ? 1 : digits) + "%"; }

  return {
    norm: norm, searchAirports: searchAirports, minutesOf: minutesOf, fmtMinutes: fmtMinutes,
    fmtFaaDuration: fmtFaaDuration, countdown: countdown, nationalSummary: nationalSummary,
    kindLabel: kindLabel, impactText: impactText, safeUrl: safeUrl, airportFromSearch: airportFromSearch,
    commitmentView: commitmentView, rebookTips: rebookTips, kmToMi: kmToMi, pct: pct,
    tileView: tileView, holidayView: holidayView, latestItems: latestItems, millions: millions,
    STATUS_WORD: STATUS_WORD, LEVEL_RANK: LEVEL_RANK, DOT_URL: DOT_URL, REFUND_LINE: REFUND_LINE
  };
});
