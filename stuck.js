/* Air Travel Desk: I'm stuck at the airport wizard (offline-capable, no storage, no network sends). */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.ATDStuck = api;
    if (typeof document !== "undefined") {
      api.init();
    }
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive";
  var REFUND_QUOTE = "Refunds are a separate rule, 14 CFR 260.6, and it applies whatever the cause of the delay or cancellation.";
  var PLAIN_READING = "This is our plain reading, not legal advice.";
  var ASK_FIRST_PAGE = "/stuck#ask-first";
  var ASK_FIRST_READ = "2026-11-14";
  var ASK_FIRST_DASHBOARD_URL = "https://www.transportation.gov/airconsumer/airline-cancellation-delay-dashboard";
  // Situations that get the short "Ask before you pay" card in the result.
  var ASK_FIRST_SITUATIONS = ["delayed", "cancelled", "missed_connection", "overnight"];
  var LABEL_ORDER = ["rebook_same", "rebook_other", "meal", "hotel", "transport", "cash", "voucher", "miles"];

  var SITUATIONS = [
    { id: "delayed", label: "Delayed" },
    { id: "cancelled", label: "Cancelled" },
    { id: "diverted", label: "Diverted" },
    { id: "missed_connection", label: "Missed my connection" },
    { id: "overnight", label: "Overnight (stuck until tomorrow)" }
  ];

  var CAUSES = [
    { id: "airline", label: "Airline's own issue (maintenance, crew)" },
    { id: "weather", label: "Weather or air traffic control" },
    { id: "unsure", label: "Not sure" }
  ];

  var CHECKLIST_ITEMS = [
    "Phone charger and power bank",
    "Medicines for tonight and tomorrow",
    "Kids' food and comfort items",
    "ID and boarding pass",
    "Receipts for meals, hotel and transport (photo them)",
    "Screenshot of the delay or cancellation notice",
    "Travel insurance and credit-card benefit numbers"
  ];

  var STEPS_BY_SITUATION = {
    delayed: [
      "Check the airline app and gate board for the updated departure time and listed reason.",
      "If the delay threatens a connection or reaches 3 hours, get in the gate or customer service line AND call the airline at the same time.",
      "Ask the agent about an earlier flight, or a seat on a partner airline if your airline has committed to that.",
      "If the airline caused the delay and your wait is 3 hours or more, ask for a meal or meal voucher if the airline has committed to it (see below).",
      "Screenshot the delay notice and keep your boarding pass and receipts in case you are eligible for reimbursement."
    ],
    cancelled: [
      "Get in the rebooking line AND call the airline at the same time so whichever reaches an agent first can help.",
      "Check the airline app right away for free self-service rebooking onto the next flight.",
      "Ask about other flights, including partner airlines or nearby airports, if your airline has committed to it.",
      "Ask for meal or hotel vouchers if the wait is 3 hours or more or overnight and the airline has committed to them (see below).",
      "If you choose not to travel, tell the agent you want a refund of the unused ticket rather than a travel credit.",
      "Screenshot the cancellation notice and keep your boarding pass and receipts in case you are eligible for a refund or reimbursement."
    ],
    diverted: [
      "Listen for crew and gate updates to find out whether the aircraft will refuel and continue or offload passengers.",
      "If the flight will not continue today, open the airline app and call customer service right away while heading to a desk.",
      "Ask the agent about rebooking on the next flight to your destination, or ground transport if your destination airport is nearby.",
      "Ask for meal or hotel vouchers if you face a 3+ hour wait or an overnight stay and the airline has committed to them (see below).",
      "Keep your boarding pass, screenshot the diversion notice, and save meal, hotel, and transport receipts in case you can claim reimbursement."
    ],
    missed_connection: [
      "Go to the nearest airline customer service desk AND call the airline at the same time.",
      "Check the airline app — airlines often auto-rebook missed connections, and you can review or change that seat.",
      "Ask the agent about standby on an earlier flight, partner airline options, or nearby airports if your airline has committed to them.",
      "Ask for meal or hotel vouchers if the missed connection leaves you waiting 3+ hours or overnight and the airline has committed to them (see below).",
      "Keep both your original and new boarding passes, screenshots of both flights, and all receipts in case you can claim reimbursement."
    ],
    overnight: [
      "Get in the customer service line AND call the airline at the same time to lock in tomorrow's earliest seat before flights fill up.",
      "Check the airline app for rebooking options first while you wait for an agent.",
      "Ask the agent for a hotel voucher, ground transport to and from the hotel, and meal vouchers if the airline caused the disruption and has committed to them (see below).",
      "If no voucher is offered or the airline has no hotel commitment, check your travel insurance or credit-card trip delay benefits before paying out of pocket.",
      "Keep your boarding pass, screenshot the delay or cancellation notice, and photo every meal, hotel, and transport receipt in case you can claim reimbursement."
    ]
  };

  // AN38: art for the result. Each step that is about a meal, a hotel, rebooking or a refund gets its own picture,
  // and the card head shows the situation (delayed or cancelled). Files are in assets/art/. All are decoration (empty alt).
  var STEP_ART = {
    "meal": "step-meal",
    "hotel": "step-hotel",
    "rebook": "step-rebook",
    "refund": "step-refund"
  };
  var STATE_ART = { delayed: "state-delayed", cancelled: "state-cancelled" };

  // Which art a step gets, from what the step is about. Hotel, then meal, then refund, then rebooking. "" = none.
  function stepArtKey(stepText) {
    if (/\bask\b/i.test(stepText)) {
      if (/\bhotel\b/i.test(stepText)) { return "hotel"; }
      if (/\bmeal\b/i.test(stepText)) { return "meal"; }
    }
    if (/\brefund\b/i.test(stepText)) { return "refund"; }
    if (/\b(rebook\w*|earlier flight|next flight|other flights|standby)\b/i.test(stepText)) { return "rebook"; }
    return "";
  }

  function safeUrl(u) {
    try {
      var p = new URL(String(u || ""));
      return (p.protocol === "https:" || p.protocol === "http:") ? p.href : "";
    } catch (e) {
      return "";
    }
  }

  function findById(list, id) {
    for (var i = 0; i < (list || []).length; i++) {
      if (list[i].id === id) { return list[i]; }
    }
    return null;
  }

  function situationLabel(id) {
    var s = findById(SITUATIONS, id);
    return s ? s.label : "Delayed";
  }

  function causeLabel(id) {
    var c = findById(CAUSES, id);
    return c ? c.label : "Not sure";
  }

  function buildScripts(airlineName, isOther, situationId, causeId) {
    var flightRef = isOther ? "flight [FLIGHT]" : airlineName + " flight [FLIGHT]";
    var causeLineCounter;
    if (causeId === "airline") {
      causeLineCounter = situationId === "overnight"
        ? "Since this is an airline-caused issue, could you also let me know how to get those vouchers under your customer service commitments?"
        : "Since this appears to be an airline-caused issue, could you check whether meal or hotel vouchers apply under your customer service commitments?";
    } else if (causeId === "weather") {
      causeLineCounter = "I understand weather or air traffic control is involved, so I am focused on finding the quickest way to get to my destination.";
    } else {
      causeLineCounter = situationId === "overnight"
        ? "Could you also confirm the listed cause and whether meal or hotel vouchers are available?"
        : "Could you also confirm the listed cause and whether any meal or hotel vouchers are available?";
    }

    var counterBySituation = {
      delayed: "Hello, I am booked on " + flightRef + " today, and it is currently delayed. Could you tell me the latest estimated departure time and whether there is an earlier flight or partner option I can move to? " + causeLineCounter + " Thank you for your help.",
      cancelled: "Hello, my " + flightRef + " was cancelled. Could you please rebook me on the next available flight, including a partner airline if possible, or help me cancel for a refund if I decide not to travel? " + causeLineCounter + " Thank you for your help.",
      diverted: "Hello, my " + flightRef + " was diverted here. Could you let me know whether this flight is expected to continue today, or rebook me on the next available flight to my destination? " + causeLineCounter + " Thank you for your help.",
      missed_connection: "Hello, I missed my connection on " + flightRef + " because my earlier flight arrived late. Could you check if I have been rebooked on the next flight, or put me on the earliest available option including standby? " + causeLineCounter + " Thank you for your help.",
      overnight: "Hello, my " + flightRef + " disruption leaves me stuck overnight until tomorrow. Could you please confirm the earliest seat tomorrow morning and let me know about meal, hotel, and ground transport vouchers? " + causeLineCounter + " Thank you for your help."
    };

    var phoneSituation = {
      delayed: "is significantly delayed",
      cancelled: "was cancelled",
      diverted: "was diverted",
      missed_connection: "had a missed connection",
      overnight: "left me stuck overnight until tomorrow"
    }[situationId] || "was disrupted";

    var phoneCause = causeId === "airline"
      ? "Could you also note the airline-caused reason on my record and check what meal or hotel vouchers apply?"
      : "Could you also confirm the official reason in the system and whether any vouchers or refund options apply?";

    var phone = "Hi, I am at the airport right now because my " + flightRef + " " + phoneSituation + ". " +
      "I have the app open and would like to check the earliest confirmed seat you can put me on, including partner flights if available. " +
      phoneCause + " Thank you for checking.";

    return {
      counter: counterBySituation[situationId] || counterBySituation.delayed,
      phone: phone
    };
  }

  function buildCommitmentsModel(data, airlineId, causeId) {
    var airline = airlineId === "other" ? null : findById(data && data.airlines, airlineId);
    var name = airline ? airline.name : "your airline";
    var heading = airline ? ("What " + airline.name + " has committed to") : "What your airline has committed to";
    var updated = (data && data.source_last_updated) || "unknown";
    var dotUrl = safeUrl(data && data.source_url);

    var causeNote;
    if (causeId === "weather") {
      causeNote = "These commitments cover only delays and cancellations the airline causes. They do not apply when the cause is weather or air traffic control.";
    } else if (causeId === "unsure") {
      causeNote = "These commitments cover only delays and cancellations the airline causes (such as maintenance, crew problems, cabin cleaning, baggage loading, or fueling). Check with the airline or FAA status to see the listed cause.";
    } else {
      causeNote = "These commitments apply when the airline causes the delay or cancellation (such as maintenance, crew problems, cabin cleaning, baggage loading, or fueling).";
    }

    if (airlineId === "other" || !airline) {
      return {
        heading: heading,
        kind: "other",
        causeNote: causeNote,
        message: "Other airlines are not listed in this quick table. Check the U.S. DOT airline dashboard or your airline's customer service plan to see what it has committed to when it causes a delay or cancellation.",
        rows: [],
        moneyNote: "If you pay out of pocket, any reimbursement is money you may be able to claim back under your airline's own commitments or customer service plan.",
        sourceText: "Source: U.S. Department of Transportation, Airline Cancellation and Delay Dashboard (last updated " + updated + ").",
        dotUrl: dotUrl,
        updated: updated
      };
    }

    if (!airline.commitments) {
      return {
        heading: heading,
        kind: "unlisted",
        causeNote: causeNote,
        message: airline.name + " is not listed on the DOT dashboard.",
        note: airline.note || "",
        pageUrl: "/airlines/" + airline.id,
        pageLabel: "See what " + airline.name + " has committed to",
        rows: [],
        moneyNote: "If you pay out of pocket, any reimbursement is money you may be able to claim back only under the airline's contract of carriage or at its discretion.",
        sourceText: "Source: U.S. Department of Transportation, Airline Cancellation and Delay Dashboard (last updated " + updated + ").",
        dotUrl: dotUrl,
        updated: updated
      };
    }

    var labels = (data && data.commitment_labels) || {};
    var rows = [];
    for (var i = 0; i < LABEL_ORDER.length; i++) {
      var key = LABEL_ORDER[i];
      if (!(key in airline.commitments)) { continue; }
      var yes = airline.commitments[key] === true;
      rows.push({
        key: key,
        label: labels[key] || key,
        committed: yes,
        text: yes ? "Committed" : "No commitment"
      });
    }

    return {
      heading: heading,
      kind: "listed",
      causeNote: causeNote,
      intro: airline.name + " has committed to the items marked Committed when it causes the delay or cancellation.",
      pageUrl: "/airlines/" + airline.id,
      pageLabel: "See what " + airline.name + " has committed to",
      rows: rows,
      noNote: "No commitment means the airline has not committed to it on the dashboard. It may still help at its own discretion.",
      moneyNote: "If you pay out of pocket, any reimbursement is money you may be able to claim back under the airline's own commitments or policy.",
      sourceText: "Source: U.S. Department of Transportation, Airline Cancellation and Delay Dashboard (last updated " + updated + ").",
      dotUrl: dotUrl,
      updated: updated
    };
  }

  // AN25: the short "Ask before you pay" card for the result. Static text, no network.
  // Returns null for a situation that does not get the card (for example "diverted").
  function buildAskFirstModel(situationId, causeId) {
    if (ASK_FIRST_SITUATIONS.indexOf(situationId) === -1) { return null; }
    var causeLine;
    if (causeId === "weather") {
      causeLine = "The dashboard commitments are for airline-caused problems, not weather or air traffic control. Help for those causes is usually up to the airline, so ask anyway.";
    } else if (causeId === "airline") {
      causeLine = "You said the airline caused it. Ask the agent to put that reason in writing.";
    } else {
      causeLine = "Ask for the cause in writing. It usually matters, and the airline's own plan decides.";
    }
    return {
      heading: "Ask before you pay",
      intro: "Before you buy a meal or a hotel, ask the airline if it will help. Whether it does depends on the cause and on the airline's own plan.",
      items: [
        "Ask: \"Does the airline offer a meal or a hotel for this?\"",
        "Ask for the reason, any voucher, the agent's name or ID, and the time, in writing.",
        causeLine,
        "Keep every receipt. If the answer is no, ask for the reason in writing. You can file a DOT complaint later."
      ],
      pageUrl: ASK_FIRST_PAGE,
      pageLabel: "Read the full Ask before you pay section",
      sourceLabel: "U.S. DOT: Airline Cancellation and Delay Dashboard",
      sourceUrl: ASK_FIRST_DASHBOARD_URL,
      read: ASK_FIRST_READ
    };
  }

  function buildEmailDraft(airlineName, isOther, situationId, causeId) {
    var sitText = situationLabel(situationId);
    var greetingName = isOther ? "Customer Relations" : (airlineName + " Customer Relations");
    var flightDesc = isOther ? "my flight [FLIGHT]" : (airlineName + " flight [FLIGHT]");
    var causeText = causeId === "airline"
      ? "The stated cause was an airline-controlled issue (such as maintenance or crew)."
      : causeId === "weather"
        ? "The stated cause involved weather or air traffic control."
        : "I am also asking for confirmation of the official cause of the disruption.";

    var askLine;
    if (situationId === "cancelled") {
      askLine = "If I chose not to travel after the cancellation, I am requesting a refund of my unused ticket. If I continued my trip and paid out of pocket for meals, hotel, or ground transport, I am requesting reimbursement of the attached receipts for any expenses possibly owed under your customer service commitments.";
    } else {
      askLine = "If I chose not to travel after a significant schedule change or cancellation, I am requesting a refund of my unused ticket. If I continued my trip and incurred meal, hotel, or ground transport costs, I am requesting reimbursement of the attached receipts for any expenses possibly owed under your customer service commitments.";
    }

    return [
      "Subject: Flight [FLIGHT] on [DATE] - " + sitText + " request",
      "",
      "Hello " + greetingName + ",",
      "",
      "I am writing about " + flightDesc + " scheduled for [DATE].",
      "What happened: My trip was affected by the following situation: " + sitText + ". " + causeText,
      "",
      "What I am asking for:",
      askLine,
      "",
      "Flight number: [FLIGHT]",
      "Travel date: [DATE]",
      "Confirmation code: [CONFIRMATION]",
      "",
      "I have kept my boarding pass, screenshots of the disruption notice, and receipts.",
      "",
      "Thank you,",
      "[YOUR NAME]"
    ].join("\n");
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text != null) { node.textContent = text; }
    return node;
  }

  // Art that sits in the layout: a masked strip under a step, or the head of the card. Decoration, so alt is empty
  // and it is hidden from screen readers. Offline and never visited: the picture is dropped and the text stays.
  // Two paintings of each scene: a night one for the dark page and a pale one for the light page. The theme switch
  // (html[data-theme]) or the system setting picks; syncArt re-picks when either changes.
  function lightPage() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t === "light") { return true; }
    if (t === "dark") { return false; }
    try { return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches); } catch (e) { return false; }
  }

  function artPath(base, ext) {
    return "assets/art/" + base + (lightPage() ? "-light" : "") + "-960." + ext;
  }

  function artFigure(base, cls) {
    var fig = el("div", cls);
    fig.setAttribute("aria-hidden", "true");
    fig.setAttribute("data-art", base);
    var pic = document.createElement("picture");
    var src = document.createElement("source");
    src.type = "image/avif";
    src.srcset = artPath(base, "avif");
    pic.appendChild(src);
    var img = document.createElement("img");
    img.src = artPath(base, "jpg");
    img.alt = "";
    img.width = 960;
    img.height = 540;
    img.loading = "lazy";
    img.decoding = "async";
    img.addEventListener("error", function () { if (fig.parentNode) { fig.parentNode.removeChild(fig); } });
    pic.appendChild(img);
    fig.appendChild(pic);
    return fig;
  }

  function syncArt() {
    var figs = document.querySelectorAll("[data-art]");
    for (var i = 0; i < figs.length; i++) {
      var base = figs[i].getAttribute("data-art"), s = figs[i].querySelector("source"), m = figs[i].querySelector("img");
      if (s && m && figs[i].className.indexOf("art-") === 0) { s.srcset = artPath(base, "avif"); m.src = artPath(base, "jpg"); }
    }
  }

  function watchArtTheme() {
    window.addEventListener("atd-theme", syncArt);
    try {
      var mq = window.matchMedia("(prefers-color-scheme: light)");
      if (mq.addEventListener) { mq.addEventListener("change", syncArt); }
    } catch (e) { /* old browser: the picture stays as first chosen */ }
  }

  function renderRadioGroup(container, name, options, selectedValue, onChange) {
    container.textContent = "";
    options.forEach(function (opt) {
      var id = name + "-" + opt.id;
      var label = el("label", "radio-card");
      label.setAttribute("for", id);

      var input = document.createElement("input");
      input.type = "radio";
      input.name = name;
      input.id = id;
      input.value = opt.id;
      input.className = "radio-input";
      if (opt.id === selectedValue) { input.checked = true; }
      input.addEventListener("change", function () {
        if (input.checked) { onChange(opt.id); }
      });

      label.appendChild(input);
      label.appendChild(el("span", "radio-text", opt.label));
      container.appendChild(label);
    });
  }

  // AN25: the Copy button of the static "Ask before you pay" section.
  // The page works without this script: the button is hidden until it runs, and the text can be selected by hand.
  // No library. navigator.clipboard first, then a textarea select + execCommand, then a visible "select the text" note.
  function initAskFirst() {
    var btn = document.getElementById("ask-copy-btn");
    var box = document.getElementById("ask-message");
    var status = document.getElementById("ask-copy-status");
    if (!btn || !box || !status) { return; }
    btn.hidden = false;
    function manual() {
      box.focus();
      box.select();
      var copied = false;
      try { copied = document.execCommand("copy"); } catch (e) { copied = false; }
      status.textContent = copied ? "Copied." : "Text selected. Copy it with your device menu.";
    }
    btn.addEventListener("click", function () {
      var text = box.value;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          status.textContent = "Copied.";
        }, manual);
      } else {
        manual();
      }
    });
  }

  function init() {
    watchArtTheme();
    initAskFirst();
    // Anchor help stays available before the wizard, including on cached visits.
    function openReceiptHelp() {
      var receipts = document.getElementById("keep-receipts");
      if (receipts && window.location.hash === "#keep-receipts") { receipts.open = true; }
    }
    window.addEventListener("hashchange", openReceiptHelp);
    openReceiptHelp();
    var state = {
      step: 1,
      airlineId: "",
      situationId: "",
      causeId: "",
      data: null
    };

    var progressEl = document.getElementById("wizard-progress");
    var dataNotice = document.getElementById("data-notice");
    var stepEls = {
      1: document.getElementById("step-1"),
      2: document.getElementById("step-2"),
      3: document.getElementById("step-3"),
      4: document.getElementById("step-4")
    };
    var airlineBox = document.getElementById("airline-options");
    var situationBox = document.getElementById("situation-options");
    var causeBox = document.getElementById("cause-options");
    var err1 = document.getElementById("step-1-error");
    var err2 = document.getElementById("step-2-error");
    var resultSummary = document.getElementById("result-summary");
    var resultBody = document.getElementById("result-body");

    if (!progressEl || !airlineBox || !situationBox || !causeBox || !resultBody) { return; }

    function showStep(n, moveFocus) {
      state.step = n;
      for (var k = 1; k <= 4; k++) {
        stepEls[k].hidden = (k !== n);
      }
      progressEl.textContent = n === 4 ? "Step 4 of 4 · Your plan" : ("Step " + n + " of 4");
      var barFill = document.getElementById("wizard-bar-fill");
      if (barFill) { barFill.style.width = (n * 25) + "%"; }
      if (n === 4) { renderResult(); }
      if (moveFocus) {
        var focusTarget = n === 4 ? resultSummary : document.getElementById("step-" + n + "-heading");
        if (focusTarget) {
          try { focusTarget.focus({ preventScroll: false }); } catch (e) { focusTarget.focus(); }
        }
        window.scrollTo(0, 0);
      }
    }

    function renderAirlines() {
      var list = ((state.data && state.data.airlines) || []).map(function (a) {
        return { id: a.id, label: a.name };
      });
      list.push({ id: "other", label: "Other airline" });
      renderRadioGroup(airlineBox, "airline", list, state.airlineId, function (val) {
        state.airlineId = val;
        err1.hidden = true;
      });
    }

    function renderSituations() {
      renderRadioGroup(situationBox, "situation", SITUATIONS, state.situationId, function (val) {
        state.situationId = val;
        err2.hidden = true;
      });
    }

    function renderCauses() {
      renderRadioGroup(causeBox, "cause", CAUSES, state.causeId, function (val) {
        state.causeId = val;
      });
    }

    function renderResult() {
      var airlineObj = state.airlineId === "other" ? null : findById(state.data && state.data.airlines, state.airlineId);
      var airlineName = airlineObj ? airlineObj.name : "Other airline";
      var isOther = !airlineObj;
      var effectiveCause = state.causeId || "unsure";

      resultSummary.textContent = airlineName + " · " + situationLabel(state.situationId) + " · " + causeLabel(effectiveCause);
      resultBody.textContent = "";

      // a. Do this now
      var secA = el("section", "result-card");
      secA.appendChild(el("h2", "result-heading", "Do this now"));
      var ol = el("ol", "result-steps");
      var steps = STEPS_BY_SITUATION[state.situationId] || STEPS_BY_SITUATION.delayed;
      var shownArt = {};
      var headArt = STATE_ART[state.situationId];
      if (headArt) {
        secA.insertBefore(artFigure(headArt, "art-head"), secA.firstChild);
      }
      steps.forEach(function (stepText) {
        var li = el("li", null, stepText);
        var key = stepArtKey(stepText);
        if (key && !shownArt[key]) {
          shownArt[key] = true;
          li.appendChild(artFigure(STEP_ART[key], "art-strip"));
        }
        ol.appendChild(li);
      });
      secA.appendChild(ol);
      resultBody.appendChild(secA);

      // a2. Ask before you pay (short version; the full section is on this page)
      var ask = buildAskFirstModel(state.situationId, effectiveCause);
      if (ask) {
        var secAsk = el("section", "result-card ask-short");
        secAsk.id = "result-ask-first";
        secAsk.appendChild(el("h2", "result-heading", ask.heading));
        secAsk.appendChild(el("p", null, ask.intro));
        var askList = el("ul", "ask-list");
        ask.items.forEach(function (t) { askList.appendChild(el("li", null, t)); });
        secAsk.appendChild(askList);
        var askLinkP = el("p", null);
        var askLink = el("a", "tap", ask.pageLabel);
        askLink.href = ask.pageUrl;
        askLinkP.appendChild(askLink);
        secAsk.appendChild(askLinkP);
        var askSrc = el("p", "small", "Source: ");
        var askSrcLink = el("a", "tap", ask.sourceLabel);
        askSrcLink.href = ask.sourceUrl;
        askSrcLink.target = "_blank";
        askSrcLink.rel = "noopener noreferrer";
        askSrc.appendChild(askSrcLink);
        askSrc.appendChild(document.createTextNode(", read " + ask.read + "."));
        secAsk.appendChild(askSrc);
        resultBody.appendChild(secAsk);
      }

      // b. Say this at the counter + Say this on the phone
      var scripts = buildScripts(airlineName, isOther, state.situationId, effectiveCause);
      var secB = el("section", "result-card");
      secB.appendChild(el("h2", "result-heading", "Say this at the counter"));
      secB.appendChild(el("blockquote", "script-quote", scripts.counter));
      secB.appendChild(el("h3", "result-subheading", "Say this on the phone"));
      secB.appendChild(el("blockquote", "script-quote", scripts.phone));
      resultBody.appendChild(secB);

      // c. What [Airline] has committed to
      var cm = buildCommitmentsModel(state.data, state.airlineId, effectiveCause);
      var secC = el("section", "result-card");
      secC.appendChild(el("h2", "result-heading", cm.heading));
      secC.appendChild(el("p", "commit-cause-note", cm.causeNote));
      if (cm.kind === "listed") {
        secC.appendChild(el("p", null, cm.intro));
        var table = el("table", "commit-table");
        table.appendChild(el("caption", "sr-only", cm.heading));
        var tbody = el("tbody");
        cm.rows.forEach(function (r) {
          var tr = el("tr");
          var th = el("th", null, r.label);
          th.setAttribute("scope", "row");
          var td = el("td");
          td.appendChild(el("span", "badge " + (r.committed ? "badge--yes" : "badge--no"), r.text));
          tr.appendChild(th);
          tr.appendChild(td);
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        secC.appendChild(table);
        secC.appendChild(el("p", "small", cm.noNote));
      } else {
        secC.appendChild(el("p", null, cm.message));
        if (cm.note) { secC.appendChild(el("p", "small", cm.note)); }
      }
      secC.appendChild(el("p", "small", cm.moneyNote));
      secC.appendChild(el("p", "small", cm.sourceText));
      if (cm.dotUrl) {
        var dotLink = el("a", "tap", "Open U.S. DOT airline dashboard");
        dotLink.href = cm.dotUrl;
        dotLink.target = "_blank";
        dotLink.rel = "noopener noreferrer";
        secC.appendChild(dotLink);
      }
      if (cm.pageUrl) {
        var pageP = el("p", "small");
        var pageLink = el("a", "tap", cm.pageLabel);
        pageLink.href = cm.pageUrl;
        pageP.appendChild(pageLink);
        secC.appendChild(pageP);
      }
      resultBody.appendChild(secC);

      // d. Refund line (always, any cause)
      var secD = el("section", "result-card");
      secD.appendChild(el("h2", "result-heading", "Refund rule"));
      secD.appendChild(el("p", "refund-line", REFUND_QUOTE));
      secD.appendChild(el("p", "small", PLAIN_READING));
      secD.appendChild(el("p", "small", "This applies whatever the cause. What you may be eligible for depends on your flight and whether you choose not to travel."));
      resultBody.appendChild(secD);

      // e. Checklist (page memory only, not stored)
      var secE = el("section", "result-card");
      secE.appendChild(el("h2", "result-heading", "Checklist"));
      secE.appendChild(el("p", "small", "Ticks stay only on this screen while it is open and are not saved."));
      var ul = el("ul", "checklist");
      CHECKLIST_ITEMS.forEach(function (item, idx) {
        var li = el("li", "checklist-item");
        var lbl = el("label", "checklist-label");
        lbl.setAttribute("for", "chk-" + idx);
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = "chk-" + idx;
        cb.className = "checklist-box";
        lbl.appendChild(cb);
        lbl.appendChild(el("span", "checklist-text", item));
        li.appendChild(lbl);
        ul.appendChild(li);
      });
      secE.appendChild(ul);
      resultBody.appendChild(secE);

      // f. Email draft + Copy button
      var secF = el("section", "result-card");
      secF.appendChild(el("h2", "result-heading", "Email draft"));
      secF.appendChild(el("p", "small", "Replace the [FLIGHT], [DATE], and other bracketed fields before sending. Nothing you type is stored or sent."));
      var ta = document.createElement("textarea");
      ta.id = "email-draft-text";
      ta.className = "email-draft-box";
      ta.rows = 20;
      ta.setAttribute("aria-label", "Email draft to the airline");
      ta.value = buildEmailDraft(airlineName, isOther, state.situationId, effectiveCause);
      secF.appendChild(ta);

      function autoSizeDraft() {
        ta.style.height = "auto";
        if (ta.scrollHeight) {
          ta.style.height = (ta.scrollHeight + 4) + "px";
        }
      }
      ta.addEventListener("input", autoSizeDraft);

      var copyRow = el("div", "copy-row");
      var copyBtn = el("button", "btn btn-secondary", "Copy");
      copyBtn.type = "button";
      copyBtn.id = "copy-email-btn";
      var copyStatus = el("span", "copy-status", "");
      copyStatus.id = "copy-status";
      copyStatus.setAttribute("role", "status");
      copyStatus.setAttribute("aria-live", "polite");

      copyBtn.addEventListener("click", function () {
        var text = ta.value;
        function fallbackSelect() {
          ta.focus();
          ta.select();
          var copied = false;
          try { copied = document.execCommand("copy"); } catch (e) { copied = false; }
          copyStatus.textContent = copied ? "Copied to clipboard." : "Text selected — copy it with your device menu.";
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            copyStatus.textContent = "Copied to clipboard.";
          }, fallbackSelect);
        } else {
          fallbackSelect();
        }
      });

      copyRow.appendChild(copyBtn);
      copyRow.appendChild(copyStatus);
      secF.appendChild(copyRow);
      resultBody.appendChild(secF);
      autoSizeDraft();

      // g. Link: Check what you may be owed in detail
      var secG = el("section", "result-card result-card--cta");
      secG.appendChild(el("p", "owed-detail-note", "Want help checking what you may be eligible for on your flight?"));
      var dcLink = el("a", "btn btn-primary", "Check what you may be owed in detail");
      dcLink.href = DOWNTIME_URL;
      dcLink.target = "_blank";
      dcLink.rel = "noopener noreferrer";
      secG.appendChild(dcLink);
      resultBody.appendChild(secG);

      // h. Footer note
      resultBody.appendChild(el("p", "result-footer-note", "Sources: U.S. DOT airline dashboard (updated " + cm.updated + "), 14 CFR 260.6."));
    }

    document.getElementById("step-1-next").addEventListener("click", function () {
      if (!state.airlineId) {
        err1.textContent = "Choose an airline (or Other airline) to continue.";
        err1.hidden = false;
        return;
      }
      showStep(2, true);
    });

    document.getElementById("step-2-back").addEventListener("click", function () { showStep(1, true); });
    document.getElementById("step-2-next").addEventListener("click", function () {
      if (!state.situationId) {
        err2.textContent = "Choose what happened to continue.";
        err2.hidden = false;
        return;
      }
      showStep(3, true);
    });

    document.getElementById("step-3-back").addEventListener("click", function () { showStep(2, true); });
    document.getElementById("step-3-next").addEventListener("click", function () { showStep(4, true); });

    document.getElementById("step-4-back").addEventListener("click", function () { showStep(3, true); });
    document.getElementById("step-4-restart").addEventListener("click", function () {
      state.airlineId = "";
      state.situationId = "";
      state.causeId = "";
      err1.hidden = true;
      err2.hidden = true;
      renderAirlines();
      renderSituations();
      renderCauses();
      showStep(1, true);
    });

    renderSituations();
    renderCauses();
    renderAirlines();
    showStep(1, false);

    fetch("data/dot-commitments.json")
      .then(function (r) {
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (json) {
        state.data = json;
        var dotDate = document.getElementById("dot-updated-date");
        if (dotDate && json && json.source_last_updated) {
          dotDate.textContent = json.source_last_updated;
        }
        dataNotice.hidden = true;
        renderAirlines();
      })
      .catch(function () {
        dataNotice.textContent = "Could not load the DOT airline commitments table. Visit once while online so your device saves it for offline use.";
        dataNotice.hidden = false;
      });
  }

  return {
    SITUATIONS: SITUATIONS,
    CAUSES: CAUSES,
    CHECKLIST_ITEMS: CHECKLIST_ITEMS,
    STEPS_BY_SITUATION: STEPS_BY_SITUATION,
    REFUND_QUOTE: REFUND_QUOTE,
    PLAIN_READING: PLAIN_READING,
    DOWNTIME_URL: DOWNTIME_URL,
    STEP_ART: STEP_ART,
    STATE_ART: STATE_ART,
    stepArtKey: stepArtKey,
    buildScripts: buildScripts,
    buildCommitmentsModel: buildCommitmentsModel,
    buildEmailDraft: buildEmailDraft,
    buildAskFirstModel: buildAskFirstModel,
    initAskFirst: initAskFirst,
    ASK_FIRST_PAGE: ASK_FIRST_PAGE,
    ASK_FIRST_SITUATIONS: ASK_FIRST_SITUATIONS,
    init: init
  };
});
