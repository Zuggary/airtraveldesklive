/* Air Travel Desk (AN34): the regional map on an airport page.
   A crop around the airport with state lines, NOAA MRMS radar and the FAA status of nearby airports.
   Same-origin files only (../us-states.geojson, ../data/airports.json, ../data/radar.json and radar.png). */
(function () {
  "use strict";
  var fig = document.getElementById("ap-map"), canvas = document.getElementById("ap-map-canvas");
  if (!fig || !canvas || !window.fetch) { return; }
  var CODE = fig.getAttribute("data-code");
  var LAT = parseFloat(fig.getAttribute("data-lat")), LON = parseFloat(fig.getAttribute("data-lon"));
  if (!isFinite(LAT) || !isFinite(LON)) { return; }
  var SPAN_LAT = 3.2;                       // degrees from the airport to the top and bottom edge
  var K = Math.cos(LAT * Math.PI / 180);    // equirectangular, scaled at the airport's latitude
  var geo = null, cards = null, radar = null, radarImg = null, marks = [];

  function get(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); }).catch(function () { return null; });
  }
  function cssVar(name, fb) {
    try { return window.getComputedStyle(canvas).getPropertyValue(name).trim() || fb; } catch (e) { return fb; }
  }
  function level(a) {
    var age = Date.now() - Date.parse(cards && cards.updated_utc || "");
    if (!isFinite(age) || age > 30 * 60000 || age < -5 * 60000 || (cards.stale_feeds || []).indexOf("FAA") >= 0 || ["clear", "delay", "stop", "closed"].indexOf(a.level) < 0) { return "none"; }
    if ((a.events || []).some(function (e) { return e && e.kind === "closure"; })) { return "stop"; }
    return a.level === "stop" || a.level === "delay" ? a.level : "clear";
  }
  function ago(iso) {
    var m = Math.floor((Date.now() - Date.parse(iso || "")) / 60000);
    if (!isFinite(m) || m < 0) { return ""; }
    if (m < 60) { return m < 1 ? "less than 1 min ago" : m + " min ago"; }
    var h = Math.floor(m / 60);
    return h === 1 ? "1 hour ago" : h + " hours ago";
  }

  function draw() {
    if (!geo) { return; }
    var w = Math.round(canvas.getBoundingClientRect().width), h = Math.round(canvas.getBoundingClientRect().height);
    if (w < 40 || h < 40) { return; }
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var scale = h / (2 * SPAN_LAT);         // px per degree of latitude
    function px(lon, lat) { return [w / 2 + (lon - LON) * K * scale, h / 2 - (lat - LAT) * scale]; }
    var col = {
      sea: cssVar("--map-sea", "#0b1016"), land: cssVar("--map-land", "#131b25"), edge: cssVar("--map-edge", "#2a3644"),
      ground: cssVar("--navy", "#080b0f"), text: cssVar("--board-text", "#f6f1e3"), muted: cssVar("--text-muted", "#a3afbd"),
      clear: cssVar("--green", "#3ccf91"), delay: cssVar("--amber", "#f5b301"), stop: cssVar("--red", "#ff5a47")
    };
    ctx.fillStyle = col.sea; ctx.fillRect(0, 0, w, h);
    ctx.beginPath();
    geo.features.forEach(function (f) {
      var g = f.geometry || {}, polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
      polys.forEach(function (poly) { poly.forEach(function (ring) {
        ring.forEach(function (pt, i) { var p = px(pt[0], pt[1]); if (i) { ctx.lineTo(p[0], p[1]); } else { ctx.moveTo(p[0], p[1]); } });
        ctx.closePath();
      }); });
    });
    ctx.fillStyle = col.land; ctx.fill();
    if (radarImg && radar && radar.bbox) {
      // radar.png is a plain lat/lon grid, so the crop is one scaled drawImage.
      var b = radar.bbox, tl = px(b[0], b[3]), br = px(b[2], b[1]);
      ctx.save(); ctx.clip(); ctx.globalAlpha = 0.6; ctx.imageSmoothingEnabled = true;
      ctx.drawImage(radarImg, tl[0], tl[1], br[0] - tl[0], br[1] - tl[1]);
      ctx.restore();
    }
    ctx.strokeStyle = col.edge; ctx.lineWidth = 1.2; ctx.stroke();

    marks = [];
    var airports = (cards && cards.airports) || {};
    var legacy = !airports.DJT && (airports.PBI || airports.KPBI || airports.KDJT);
    var list = Object.keys(airports).filter(function (c) { return !/^(PBI|KPBI|KDJT)$/.test(c); })
      .map(function (c) { return airports[c]; });
    if (legacy) { list.push(Object.assign({}, legacy, { code: "DJT" })); }
    list.forEach(function (a) {
      if (typeof a.lat !== "number" || typeof a.lon !== "number") { return; }
      var p = px(a.lon, a.lat);
      // AN34 round 4: a neighbour too close to the edge would have its label cut off; leave it out.
      if (a.code !== CODE && (p[0] < 16 || p[0] > w - 16 || p[1] < 16 || p[1] > h - 16)) { return; }
      marks.push({ code: a.code, x: p[0], y: p[1], lv: level(a), me: a.code === CODE });
    });
    if (!marks.some(function (m) { return m.me; })) { var me = px(LON, LAT); marks.push({ code: CODE, x: me[0], y: me[1], lv: "none", me: true }); }
    marks.sort(function (a, b) { return (a.me ? 1 : 0) - (b.me ? 1 : 0); });
    ctx.textBaseline = "middle";
    marks.forEach(function (m) {
      var c = col[m.lv] || col.muted, r = m.me ? 9 : 5.5;
      if (m.me) {
        ctx.beginPath(); ctx.arc(m.x, m.y, 26, 0, Math.PI * 2); ctx.globalAlpha = 0.18; ctx.fillStyle = c; ctx.fill(); ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(m.x, m.y, 16, 0, Math.PI * 2); ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(m.x, m.y, r, 0, Math.PI * 2); ctx.fillStyle = c; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = col.ground; ctx.stroke();
    });
    // Labels: this airport first, then the neighbours that do not collide with a label already drawn.
    var boxes = [];
    marks.slice().reverse().forEach(function (m) {
      ctx.font = (m.me ? "700 22px" : "700 15px") + " 'Barlow Condensed', 'Arial Narrow', sans-serif";
      var gap = m.me ? 22 : 9, tw = ctx.measureText(m.code).width, tx = m.x + gap, ty = m.y;
      if (tx + tw > w - 4) { tx = m.x - gap - tw; }
      var bx = { x: tx - 2, y: ty - (m.me ? 13 : 9), w: tw + 4, h: m.me ? 26 : 18 };
      function hits(b) { return boxes.some(function (o) { return !(b.x + b.w < o.x || o.x + o.w < b.x || b.y + b.h < o.y || o.y + o.h < b.y); }); }
      // AN34 round 4: when the right side is taken, try the left, so a dot is not left without its code.
      if (hits(bx) && !m.me) { tx = m.x - gap - tw; bx = { x: tx - 2, y: bx.y, w: bx.w, h: bx.h }; }
      if (hits(bx) || tx < 2) { return; }
      boxes.push(bx);
      if (m.me) { boxes.push({ x: m.x - 27, y: m.y - 27, w: 54, h: 54 }); }
      ctx.lineWidth = 4; ctx.strokeStyle = col.ground; ctx.strokeText(m.code, tx, ty);
      ctx.fillStyle = m.me ? col.text : col.muted; ctx.fillText(m.code, tx, ty);
    });
  }

  canvas.addEventListener("click", function (e) {
    var r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top, best = null, bd = 22;
    marks.forEach(function (m) { var d = Math.hypot(m.x - x, m.y - y); if (!m.me && d < bd) { bd = d; best = m; } });
    if (best) { window.location.href = "/airports/" + best.code; }
  });
  canvas.addEventListener("pointermove", function (e) {
    var r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    canvas.style.cursor = marks.some(function (m) { return !m.me && Math.hypot(m.x - x, m.y - y) < 22; }) ? "pointer" : "default";
  });

  Promise.all([get("../us-states.geojson"), get("../data/airports.json?ts=" + Date.now()), get("../data/radar.json?ts=" + Date.now())]).then(function (r) {
    geo = r[0]; cards = r[1]; radar = r[2];
    if (!geo || !geo.features) { return; }
    fig.hidden = false;
    var cap = document.getElementById("ap-map-cap");
    if (cap && radar && radar.fetched_utc) { cap.textContent = "Radar: NOAA MRMS, " + ago(radar.fetched_utc) + ". Status: FAA. Tap an airport to open it."; }
    draw();
    if (radar && radar.fetched_utc) {
      var img = new Image();
      img.onload = function () { radarImg = img; draw(); };
      img.src = "../data/radar.png?v=" + encodeURIComponent(radar.fetched_utc);
    }
    if (window.ResizeObserver) { new ResizeObserver(draw).observe(canvas); } else { window.addEventListener("resize", draw); }
    try { window.addEventListener("atd-theme", draw); } catch (e) { /* keep the first colours */ }
    try { window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", draw); } catch (e) { /* keep the first colours */ }
  });
})();
