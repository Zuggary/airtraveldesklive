/* Independent reference: Astronomical Almanac low-precision sun (not the NOAA series), plus bisection for rise/set. */
"use strict";
const R = Math.PI / 180, D = 180 / Math.PI;
function sunAA(ms) {
  const n = ms / 86400000 + 2440587.5 - 2451545.0;
  const L = (280.460 + 0.9856474 * n) % 360, g = ((357.528 + 0.9856003 * n) % 360) * R;
  const lam = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * R, eps = (23.439 - 0.0000004 * n) * R;
  const ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam));
  const dec = Math.asin(Math.sin(eps) * Math.sin(lam));
  const gmst = ((18.697374558 + 24.06570982441908 * n) % 24 + 24) % 24 * 15;      // degrees
  let lon = ra * D - gmst; lon = ((lon + 540) % 360 + 360) % 360 - 180;
  return { lat: dec * D, lon: lon };
}
function alt(lat, lon, ms) {
  const s = sunAA(ms);
  const sa = Math.sin(lat * R) * Math.sin(s.lat * R) + Math.cos(lat * R) * Math.cos(s.lat * R) * Math.cos((lon - s.lon) * R);
  return Math.asin(sa) * D;
}
// all crossings of altitude -0.833 between [t0, t1] at 1-minute scan, refined by bisection
function crossings(lat, lon, t0, t1) {
  const out = []; let pt = t0, pv = alt(lat, lon, pt) + 0.833;
  for (let t = t0 + 60000; t <= t1; t += 60000) {
    const v = alt(lat, lon, t) + 0.833;
    if ((pv < 0) !== (v < 0)) {
      let a = pt, b = t;
      for (let i = 0; i < 30; i++) { const m = (a + b) / 2; ((alt(lat, lon, m) + 0.833 < 0) === (pv < 0)) ? (a = m) : (b = m); }
      out.push({ kind: v > 0 ? "sunrise" : "sunset", ms: (a + b) / 2 });
    }
    pt = t; pv = v;
  }
  return out;
}
module.exports = { sunAA, alt, crossings };
