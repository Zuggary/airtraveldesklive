/* Air Travel Desk: breaking-news block. Reads /data/alert.json (hand-written when something the FAA feed does not show is happening,
   such as an airline outage). With no file, an inactive file or an expired one it does nothing at all: no layout change, no cookies,
   no storage. While active it puts one red block at the top of the page and checks the file again every 60 seconds. Text only
   (textContent), links only to the sources listed in the file. Not an ad slot and not an ad refresh. */
(function (root) {
  "use strict";

  var POLL_MS = 60000;
  var MAX_POINTS = 5;
  var MAX_SOURCES = 4;

  /* The model the block shows, or null when nothing should show. Pure: no DOM. */
  function alertModel(doc, nowMs) {
    if (!doc || typeof doc !== "object" || doc.active !== true) { return null; }
    var headline = typeof doc.headline === "string" ? doc.headline.trim() : "";
    if (!headline || headline.length > 160) { return null; }
    if (doc.expires_utc) {
      var exp = Date.parse(doc.expires_utc);
      if (isNaN(exp) || nowMs >= exp) { return null; }
    }
    var points = (Array.isArray(doc.points) ? doc.points : []).filter(function (p) { return typeof p === "string" && p.trim(); })
      .slice(0, MAX_POINTS).map(function (p) { return p.trim().slice(0, 300); });
    var sources = (Array.isArray(doc.sources) ? doc.sources : []).filter(function (s) {
      return s && typeof s.name === "string" && typeof s.url === "string" && /^https:\/\//.test(s.url);
    }).slice(0, MAX_SOURCES).map(function (s) { return { name: s.name.trim().slice(0, 60), url: s.url }; });
    var upd = doc.updated_utc ? Date.parse(doc.updated_utc) : NaN;
    return {
      id: String(doc.id || "alert"),
      level: doc.level === "watch" ? "watch" : "warning",
      label: typeof doc.label === "string" ? doc.label.trim().slice(0, 40) : "",
      headline: headline,
      status: typeof doc.status_line === "string" ? doc.status_line.trim().slice(0, 160) : "",
      points: points,
      sources: sources,
      updatedMs: isNaN(upd) ? null : upd
    };
  }

  function timeText(ms) {
    try {
      return new Date(ms).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short" });
    } catch (e) { return ""; }
  }

  function el(doc, tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) { n.className = cls; }
    if (text) { n.textContent = text; }
    return n;
  }

  var CSS = ".atd-alert{background:#b91c1c;color:#fff;border-bottom:3px solid #7f1d1d;padding:.75rem 1rem;font-size:1rem;line-height:1.45}" +
    ".atd-alert.watch{background:#92400e;border-bottom-color:#78350f}" +
    ".atd-alert-in{max-width:70rem;margin:0 auto}" +
    ".atd-alert-top{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}" +
    ".atd-alert-tag{background:#fff;color:#7f1d1d;font-weight:800;letter-spacing:.04em;padding:.1rem .5rem;border-radius:4px;font-size:.85rem}" +
    ".atd-alert-label{border:1px solid rgba(255,255,255,.7);padding:.1rem .5rem;border-radius:4px;font-weight:700;font-size:.85rem}" +
    ".atd-alert-h{font-weight:800;font-size:1.15rem;margin:.35rem 0 .2rem}" +
    ".atd-alert-status{font-weight:700;margin:.1rem 0 .4rem}" +
    ".atd-alert ul{margin:.3rem 0 .4rem 1.2rem;padding:0}.atd-alert li{margin:.15rem 0}" +
    ".atd-alert summary{cursor:pointer;font-weight:700;padding:.35rem 0;min-height:2.75rem;display:flex;align-items:center}" +
    ".atd-alert summary::before{content:\"\\25B8\";margin-right:.5rem}.atd-alert details[open] summary::before{content:\"\\25BE\"}" +
    ".atd-alert summary:focus-visible,.atd-alert a:focus-visible{outline:3px solid #fff;outline-offset:2px}" +
    ".atd-alert a{color:#fff;text-decoration:underline;font-weight:600}" +
    ".atd-alert-meta{font-size:.9rem;opacity:.95}";

  function render(doc, model) {
    var old = doc.getElementById("atd-alert");
    if (old && old.parentNode) { old.parentNode.removeChild(old); }
    if (!model) { return; }
    if (!doc.getElementById("atd-alert-css")) {
      var st = el(doc, "style");
      st.id = "atd-alert-css";
      st.textContent = CSS;
      doc.head.appendChild(st);
    }
    var box = el(doc, "section", "atd-alert " + model.level);
    box.id = "atd-alert";
    box.setAttribute("role", "alert");
    box.setAttribute("aria-label", "Breaking news");
    var inner = el(doc, "div", "atd-alert-in");
    var top = el(doc, "div", "atd-alert-top");
    top.appendChild(el(doc, "span", "atd-alert-tag", "BREAKING"));
    if (model.label) { top.appendChild(el(doc, "span", "atd-alert-label", model.label)); }
    inner.appendChild(top);
    inner.appendChild(el(doc, "p", "atd-alert-h", model.headline));
    if (model.status) { inner.appendChild(el(doc, "p", "atd-alert-status", model.status)); }
    if (model.points.length) {
      var det = el(doc, "details", "atd-alert-more");
      if (doc.defaultView && doc.defaultView.innerWidth >= 700) { det.open = true; }      /* a phone starts folded; the headline and status stay in view */
      det.appendChild(el(doc, "summary", "", "What we know"));
      var ul = el(doc, "ul");
      model.points.forEach(function (p) { ul.appendChild(el(doc, "li", "", p)); });
      det.appendChild(ul);
      inner.appendChild(det);
    }
    var meta = el(doc, "p", "atd-alert-meta");
    var bits = [];
    if (model.updatedMs !== null) { bits.push("Updated " + timeText(model.updatedMs)); }
    meta.appendChild(doc.createTextNode(bits.join(" ") + (bits.length && model.sources.length ? ". Sources: " : (model.sources.length ? "Sources: " : ""))));
    model.sources.forEach(function (s, i) {
      var a = el(doc, "a", "", s.name);
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      meta.appendChild(a);
      if (i < model.sources.length - 1) { meta.appendChild(doc.createTextNode(", ")); }
    });
    inner.appendChild(meta);
    box.appendChild(inner);
    var skip = doc.querySelector(".skip-link");
    if (skip && skip.parentNode === doc.body) { doc.body.insertBefore(box, skip.nextSibling); } else { doc.body.insertBefore(box, doc.body.firstChild); }
  }

  function start(win) {
    var doc = win.document;
    var timer = null;
    function check() {
      var ctl = typeof win.AbortController === "function" ? new win.AbortController() : null;
      var t = win.setTimeout(function () { if (ctl) { ctl.abort(); } }, 8000);
      win.fetch("/data/alert.json?m=" + Math.floor(Date.now() / 60000), { cache: "no-store", signal: ctl ? ctl.signal : undefined })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { win.clearTimeout(t); render(doc, alertModel(d, Date.now())); })
        .catch(function () { win.clearTimeout(t); })
        .then(function () { if (!timer) { timer = win.setInterval(check, POLL_MS); } });
    }
    if (typeof win.fetch === "function") { check(); }
  }

  var api = { alertModel: alertModel, POLL_MS: POLL_MS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  if (root && root.document) { root.ATDAlert = api; start(root); }
})(typeof window !== "undefined" ? window : null);
