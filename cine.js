/* AN10 cinematic map: pure helpers (no DOM). Loaded by index.html, tested with node (tests/test_an10.py). */
(function (root) {
  "use strict";

  // Altitude bands: ground grey, under 10k ft teal, 10-25k ft cyan, over 25k ft white-blue.
  function altBand(alt) {
    if (alt === "ground") return "ground";
    const n = typeof alt === "number" ? alt : parseFloat(alt);
    if (!isFinite(n)) return "mid";
    if (n < 10000) return "low";
    if (n < 25000) return "mid";
    return "high";
  }
  const BAND_COLORS = { ground: "#94a3b8", low: "#2dd4bf", mid: "#22d3ee", high: "#dbeafe" };

  // Dead reckoning. dtSec is clamped to [0, maxSec]: a position is never pushed past the poll interval.
  function clampDt(dtSec, maxSec) {
    if (!isFinite(dtSec) || dtSec < 0) return 0;
    return Math.min(dtSec, Math.max(0, maxSec));
  }
  function deadReckon(lat, lon, trackDeg, gsKt, dtSec, maxSec) {
    const dt = clampDt(dtSec, maxSec);
    if (typeof trackDeg !== "number" || typeof gsKt !== "number" || !isFinite(trackDeg) || !isFinite(gsKt) || gsKt <= 0 || dt === 0) return [lat, lon];
    const nm = gsKt * dt / 3600;
    const tr = trackDeg * Math.PI / 180;
    const dLat = nm * Math.cos(tr) / 60;
    const cl = Math.max(0.2, Math.cos(lat * Math.PI / 180));
    const dLon = nm * Math.sin(tr) / (60 * cl);
    return [lat + dLat, lon + dLon];
  }

  function capTrail(points, n) {
    return points.length > n ? points.slice(points.length - n) : points.slice();
  }

  function parseAvgMinutes(text) {
    if (!text) return 0;
    const h = /(\d+)\s*hours?/i.exec(text), m = /(\d+)\s*minutes?/i.exec(text);
    return (h ? parseInt(h[1], 10) * 60 : 0) + (m ? parseInt(m[1], 10) : 0);
  }

  // Worst active event: ground stop first, then ground delay by longest average, then plain delay, then closure.
  // names: {code: short name}. Events without a usable position are skipped.
  function pickSpotlight(events, names) {
    let best = null;
    (events || []).forEach(function (ev, i) {
      const kind = String(ev.kind || "").toLowerCase();
      const rank = { ground_stop: 4, ground_delay: 3, delay: 2, closure: 1 }[kind];
      if (!rank || !ev.airport || typeof ev.lat !== "number" || typeof ev.lon !== "number") return;
      const avg = parseAvgMinutes(ev.fields && ev.fields.avg);
      const score = rank * 100000 + avg * 10 - i * 0.001;   // ties keep the event order
      if (!best || score > best.score) {
        const code = String(ev.airport).toUpperCase();
        const label = { ground_stop: "Ground stop", ground_delay: "Ground delay", delay: "Delay", closure: "Closure" }[kind];
        const reason = label + (kind === "ground_delay" && avg ? ", avg " + avg + " min" : "");
        best = { score: score, code: code, lat: ev.lat, lon: ev.lon, kind: kind, reason: reason, name: (names && names[code]) || code };
      }
    });
    if (!best) return null;
    delete best.score;
    return best;
  }

  function smoothstep(x) { x = Math.max(0, Math.min(1, x)); return x * x * (3 - 2 * x); }
  // 0 = home view, 1 = fully zoomed. In 3 s, hold, back out over 3 s starting at holdUntil (20 s). Over after holdUntil + out.
  function spotlightK(elapsedS, inS, holdUntilS, outS) {
    if (elapsedS < 0) return 0;
    if (elapsedS < inS) return smoothstep(elapsedS / inS);
    if (elapsedS < holdUntilS) return 1;
    return 1 - smoothstep((elapsedS - holdUntilS) / outS);
  }
  function spotlightOver(elapsedS, holdUntilS, outS) { return elapsedS >= holdUntilS + outS; }

  // Perspective tilt. Flat view (xv, yv) in a w x h frame -> screen. t = 0 at the bottom edge, 1 at the top.
  // Width scale s = 1 / (1 + a t); vertical position follows the same pinhole, compressed by m.
  function makeTilt(w, h, a, m, top) {
    const span = m * (1 - top);                     // share of the frame the flat map's height occupies
    function q(t) { return span * t * (1 + a) / (1 + a * t); }
    return {
      a: a,
      scale: function (t) { return 1 / (1 + a * t); },
      project: function (xv, yv) {
        const t = Math.max(-0.6, 1 - yv / h);
        const s = 1 / (1 + a * t);
        return [w / 2 + (xv - w / 2) * s, h * (1 - q(t))];
      },
      // screen row -> t (inverse of q); null when the row is above the far edge of the flat map
      rowToT: function (ys) {
        const qq = (1 - ys / h) / span;
        const den = (1 + a) - a * qq;
        if (den <= 0) return null;
        const t = qq / den;
        return t > 1 || t < -0.6 ? null : t;
      }
    };
  }

  const api = { altBand, BAND_COLORS, clampDt, deadReckon, capTrail, parseAvgMinutes, pickSpotlight, spotlightK, spotlightOver, smoothstep, makeTilt };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Cine = api;
})(typeof window !== "undefined" ? window : this);
