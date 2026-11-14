(function () {
  "use strict";

  var REFRESH_INTERVAL_MS = 60000;
  var TICK_INTERVAL_MS = 30000;
  var STALE_MINUTES = 20;

  var SHORT_NAMES = {
    ATL: "Atlanta",
    DFW: "Dallas/Fort Worth",
    DEN: "Denver",
    ORD: "Chicago O'Hare",
    LAX: "Los Angeles",
    JFK: "New York JFK",
    LAS: "Las Vegas",
    MCO: "Orlando",
    MIA: "Miami",
    CLT: "Charlotte",
    SEA: "Seattle-Tacoma",
    PHX: "Phoenix",
    EWR: "Newark",
    SFO: "San Francisco",
    IAH: "Houston Bush",
    BOS: "Boston Logan",
    FLL: "Fort Lauderdale",
    MSP: "Minneapolis",
    LGA: "LaGuardia",
    DTW: "Detroit",
    PHL: "Philadelphia",
    SLC: "Salt Lake City",
    BWI: "Baltimore",
    IAD: "Dulles",
    SAN: "San Diego",
    DCA: "Reagan National",
    TPA: "Tampa",
    BNA: "Nashville",
    AUS: "Austin",
    MDW: "Chicago Midway"
  };

  var LEVEL_LABELS = {
    clear: "Clear",
    delay: "Delay",
    stop: "Stop"
  };

  var latestData = null;

  var updatedEl = document.getElementById("updated-line");
  var staleEl = document.getElementById("stale-notice");
  var boardEl = document.getElementById("board");
  var eventsEl = document.getElementById("events");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  function formatKind(ev) {
    if (ev.kind === "ground_stop") {
      return "Ground Stop";
    }
    if (ev.kind === "ground_delay") {
      return "Ground Delay";
    }
    if (ev.kind === "closure") {
      return "Airport Closure";
    }
    if (ev.kind === "delay") {
      if (ev.direction) {
        return ev.direction + " Delay";
      }
      return "Flight Delay";
    }
    return "Flight Disruption";
  }

  function formatLocalTime(tz) {
    if (!tz) {
      return "";
    }
    try {
      return new Intl.DateTimeFormat(undefined, {
        timeZone: tz,
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short"
      }).format(new Date());
    } catch (_err) {
      return "";
    }
  }

  function updateFreshness() {
    if (!latestData) {
      return;
    }
    var parsedMs = Date.parse(latestData.updated_utc || "");
    var isStale = Boolean(latestData.stale);

    if (Number.isFinite(parsedMs)) {
      var diffMin = Math.max(0, Math.floor((Date.now() - parsedMs) / 60000));
      updatedEl.textContent = "Updated " + diffMin + " min ago";
      if (diffMin > STALE_MINUTES) {
        isStale = true;
      }
    } else {
      updatedEl.textContent = "Update time unavailable";
      isStale = true;
    }

    staleEl.hidden = !isStale;
  }

  function renderBoard(board) {
    boardEl.textContent = "";
    var list = Array.isArray(board) ? board : [];
    for (var i = 0; i < list.length; i++) {
      var item = list[i];
      var level = LEVEL_LABELS[item.level] ? item.level : "clear";
      var tile = el("article", "tile tile--" + level);
      tile.setAttribute("aria-label", item.code + " " + item.name + ": " + LEVEL_LABELS[level]);

      var top = el("div", "tile-top");
      top.appendChild(el("span", "tile-code", item.code));
      top.appendChild(el("span", "tile-level", LEVEL_LABELS[level]));

      var shortName = SHORT_NAMES[item.code] || item.name || item.code;
      var nameEl = el("span", "tile-name", shortName);
      if (item.name) {
        nameEl.title = item.name;
      }

      tile.appendChild(top);
      tile.appendChild(nameEl);
      boardEl.appendChild(tile);
    }
  }

  function addMetric(container, label, value) {
    if (!value) {
      return;
    }
    var item = el("span");
    item.appendChild(el("span", "event-metric-label", label + ": "));
    item.appendChild(document.createTextNode(value));
    container.appendChild(item);
  }

  function renderEvents(events, board) {
    eventsEl.textContent = "";
    var list = Array.isArray(events) ? events : [];
    if (list.length === 0) {
      eventsEl.appendChild(el("p", "empty-state", "No FAA delays right now"));
      return;
    }

    var tzByCode = {};
    if (Array.isArray(board)) {
      for (var b = 0; b < board.length; b++) {
        tzByCode[board[b].code] = board[b].tz;
      }
    }

    for (var i = 0; i < list.length; i++) {
      var ev = list[i];
      var isStop = ev.kind === "ground_stop" || ev.kind === "closure";
      var card = el("article", "event-card" + (isStop ? " event-card--stop" : ""));

      var header = el("div", "event-header");
      var titleWrap = el("div");
      var headingText = ev.name && ev.name !== ev.code ? ev.name + " (" + ev.code + ")" : ev.code;
      titleWrap.appendChild(el("h3", "event-title", headingText));
      titleWrap.appendChild(el("p", "event-kind", formatKind(ev)));

      var statusText = ev.status === "CONFIRMED" ? "CONFIRMED" : "OFFICIAL";
      var chipClass = "status-chip" + (statusText === "CONFIRMED" ? " status-chip--confirmed" : "");
      var chip = el("span", chipClass, statusText);

      header.appendChild(titleWrap);
      header.appendChild(chip);
      card.appendChild(header);

      var metrics = el("p", "event-metrics");
      addMetric(metrics, "Direction", ev.direction);
      addMetric(metrics, "Avg", ev.avg);
      addMetric(metrics, "Min", ev.min);
      addMetric(metrics, "Max", ev.max);
      addMetric(metrics, "Trend", ev.trend);
      addMetric(metrics, ev.kind === "closure" ? "Reopens" : "Ends", ev.end_time);
      if (metrics.childNodes.length > 0) {
        card.appendChild(metrics);
      }

      if (ev.reason) {
        card.appendChild(el("p", "event-reason", "Reason: " + ev.reason));
      }

      if (ev.alert) {
        card.appendChild(el("p", "event-alert", "NWS Alert: " + ev.alert));
      }

      var meta = el("div", "event-meta");
      var sourcesList = Array.isArray(ev.sources) && ev.sources.length > 0 ? ev.sources.join(", ") : "FAA";
      meta.appendChild(el("span", null, "Sources: " + sourcesList));

      var tz = ev.tz || tzByCode[ev.code] || "";
      var localTime = formatLocalTime(tz);
      if (localTime) {
        meta.appendChild(el("span", null, "Local time: " + localTime));
      }
      card.appendChild(meta);

      eventsEl.appendChild(card);
    }
  }

  function loadStatus() {
    var url = "data/status.json?ts=" + Date.now();
    fetch(url, { cache: "no-store" })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("HTTP " + resp.status);
        }
        return resp.json();
      })
      .then(function (data) {
        latestData = data;
        updateFreshness();
        renderBoard(data.board);
        renderEvents(data.events, data.board);
      })
      .catch(function () {
        if (!latestData) {
          updatedEl.textContent = "Unable to load status";
          staleEl.hidden = false;
        } else {
          updateFreshness();
        }
      });
  }

  loadStatus();
  window.setInterval(loadStatus, REFRESH_INTERVAL_MS);
  window.setInterval(updateFreshness, TICK_INTERVAL_MS);
})();
