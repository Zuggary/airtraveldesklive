(function () {
  // Staging wall. No external hosts: map images and snapshot come from this origin only. No audio, no ads, no analytics.
  var cv = document.getElementById('map'), ctx = cv.getContext('2d');
  var relief = new Image(), lights = new Image(), snap = null, dpr = Math.min(window.devicePixelRatio || 1, 2);
  var loaded = 0, statesGeo = null;
  fetch('us-states.geojson').then(function (r) { return r.ok ? r.json() : null; }).then(function (g) { statesGeo = g; draw(); }).catch(function () {});
  function ready() { if (++loaded === 2) draw(); }
  relief.onload = ready; lights.onload = ready;
  relief.src = '/wall/img/relief_conus8.webp'; lights.src = '/wall/img/lights_conus8.webp';
  function size() {
    cv.width = Math.round(innerWidth * dpr); cv.height = Math.round(innerHeight * dpr);
    cv.style.width = innerWidth + 'px'; cv.style.height = innerHeight + 'px';
    draw();
  }
  // The maps are continental-US only (conus8). Fit the image to the screen with its aspect ratio kept, then
  // project lon/lat into that rectangle. Bounds are an assumption calibrated in the screenshot review.
  var LON0 = -127, LON1 = -65, LAT0 = 51, LAT1 = 23;
  var rect = { x: 0, y: 0, w: 0, h: 0 };
  function fitRect() {
    var ar = relief.naturalWidth && relief.naturalHeight ? relief.naturalWidth / relief.naturalHeight : 1.79;
    var w = cv.width, h = cv.height, fw, fh;
    if (h > w) {
      // Portrait phone: fill the screen height and crop the sides, centred on the middle of the US. Never stretched.
      fh = h; fw = h * ar;
      rect = { x: (w - fw) / 2, y: 0, w: fw, h: fh };
    } else {
      // Landscape: fit the whole map inside the screen, aspect kept.
      fw = w; fh = w / ar;
      if (fh > h) { fh = h; fw = h * ar; }
      rect = { x: (w - fw) / 2, y: (h - fh) / 2, w: fw, h: fh };
    }
  }
  function px(lon, lat) {
    return [rect.x + (lon - LON0) / (LON1 - LON0) * rect.w, rect.y + (LAT0 - lat) / (LAT0 - LAT1) * rect.h];
  }
  function draw() {
    if (!cv.width) return size();
    // 21 Nov (CoS): palette fix. The relief image's own purple oceans and muddy red terrain are replaced:
    // greyscale relief, navy-blue tint, amber city lights, bigger brighter aircraft dots.
    fitRect();
    ctx.fillStyle = '#0a1424'; ctx.fillRect(0, 0, cv.width, cv.height);
    if (relief.complete && relief.naturalWidth) {
      ctx.filter = 'grayscale(0.9) brightness(0.62) contrast(1.15)';
      ctx.drawImage(relief, rect.x, rect.y, rect.w, rect.h);
      ctx.filter = 'none';
      ctx.globalCompositeOperation = 'multiply';
      ctx.fillStyle = 'rgba(29, 59, 102, 0.85)';
      ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
      ctx.globalCompositeOperation = 'source-over';
    }
    if (lights.complete && lights.naturalWidth) {
      ctx.globalCompositeOperation = 'screen';
      ctx.filter = 'sepia(1) saturate(2.4) hue-rotate(-10deg) brightness(0.9)';
      ctx.globalAlpha = 0.22;
      ctx.drawImage(lights, rect.x, rect.y, rect.w, rect.h);
      ctx.globalAlpha = 1; ctx.filter = 'none'; ctx.globalCompositeOperation = 'source-over';
    }
    if (statesGeo && statesGeo.features) {
      // 21 Nov (CoS): subtle state borders for orientation on the dark basemap.
      ctx.lineWidth = 0.8 * dpr; ctx.strokeStyle = 'rgba(190, 220, 245, 0.5)';
      ctx.beginPath();
      statesGeo.features.forEach(function (f) {
        var polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
        polys.forEach(function (poly) { poly.forEach(function (ring) {
          ring.forEach(function (c, j) { var q = px(c[0], c[1]); if (j) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]); });
        }); });
      });
      ctx.stroke();
    }
    if (snap && snap.aircraft) {
      // 21 Nov (CoS): heading-aware plane icons (small arrows from the track field); dots remain the fallback when no track.
      var t0 = performance.now();
      var r = 2.6 * dpr;
      for (var i = 0; i < snap.aircraft.length; i++) {
        var a = snap.aircraft[i], p = px(a[2], a[1]), tr = a[5];
        if (typeof tr === 'number' && isFinite(tr)) {
          ctx.save(); ctx.translate(p[0], p[1]); ctx.rotate(tr * Math.PI / 180);
          ctx.beginPath(); ctx.moveTo(0, -4.2 * dpr); ctx.lineTo(2.9 * dpr, 3 * dpr); ctx.lineTo(0, 1.4 * dpr); ctx.lineTo(-2.9 * dpr, 3 * dpr); ctx.closePath();
          ctx.fillStyle = '#bff3ff'; ctx.fill();
          ctx.lineWidth = 0.7 * dpr; ctx.strokeStyle = '#0a1424'; ctx.stroke();
          ctx.restore();
        } else {
          ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, Math.PI * 2);
          ctx.fillStyle = '#bff3ff'; ctx.fill();
          ctx.lineWidth = 0.8 * dpr; ctx.strokeStyle = '#0a1424'; ctx.stroke();
        }
      }
      window.__wallDrawMs = performance.now() - t0;
    }
  }
  function show(doc) {
    snap = doc;
    document.getElementById('count').innerHTML = '<span id="dot"></span>aircraft: ' + doc.count;
    var t = doc.desk_fetched_utc ? doc.desk_fetched_utc.replace('T', ' ').replace('Z', ' UTC') : 'unknown';
    document.getElementById('asof').textContent = 'data as of: ' + t;
    // Judge staleness when the viewer looks, not when the snapshot was built: the desk time is the reference.
    var ageS = doc.desk_fetched_utc ? (Date.now() - Date.parse(doc.desk_fetched_utc)) / 1000 : Infinity;
    document.getElementById('stale').classList.toggle('on', !!doc.stale || ageS > (doc.stale_after_s || 360));
    draw();
  }
  async function load() {
    try {
      var r = await fetch('/api/wall-snapshot', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      var ds = new DecompressionStream('gzip');
      var text = await new Response(r.body.pipeThrough(ds)).text();
      show(JSON.parse(text));
    } catch (e) {
      // 21 Nov (CoS): a failed feed shows a clear note, not a blank map.
      document.getElementById('count').innerHTML = '<span id="dot"></span>aircraft: unavailable';
      document.getElementById('asof').textContent = 'Live aircraft temporarily unavailable. The map is still shown; it will update when the feed returns.';
      document.getElementById('stale').classList.add('on');
    }
  }
  addEventListener('resize', size);
  size(); load(); setInterval(load, 60000);
})();
