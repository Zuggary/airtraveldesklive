"use strict";
const assert = require("assert");
const path = require("path");
const S = require(path.join(__dirname, "..", "..", "sun.js"));
const ref = require("./ref.js");
let n = 0;
function t(name, fn) { fn(); n++; console.log("ok - " + name); }
const angDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);

const INSTANTS = [Date.UTC(2026, 2, 20, 14, 46), Date.UTC(2026, 5, 21, 3, 15), Date.UTC(2026, 8, 23, 0, 5), Date.UTC(2026, 11, 21, 17, 30), Date.UTC(2026, 10, 14, 20, 0)];
t("subsolar point matches the independent reference within 0.5 deg at 5 instants", () => {
  for (const ms of INSTANTS) {
    const a = S.subsolar(ms), b = ref.sunAA(ms);
    assert.ok(Math.abs(a.lat - b.lat) < 0.5, "lat " + new Date(ms).toISOString() + " " + a.lat + " vs " + b.lat);
    assert.ok(angDiff(a.lon, b.lon) < 0.5, "lon " + new Date(ms).toISOString() + " " + a.lon + " vs " + b.lon);
  }
});
t("subsolar point at 12:00 UTC sits near the prime meridian (within the equation of time)", () => {
  const a = S.subsolar(Date.UTC(2026, 3, 15, 12, 0));
  assert.ok(Math.abs(a.lon) < 1.2, String(a.lon));
});
t("equinox terminator passes through both poles", () => {
  let best = null;
  for (let m = 0; m < 365 * 24 * 60; m += 20) { const ms = Date.UTC(2026, 8, 20) + m * 60000; const d = Math.abs(S.subsolar(ms).lat); if (best === null || d < best.d) best = { d: d, ms: ms }; }
  assert.ok(best.d < 0.05, "decl " + best.d);
  const sp = S.subsolar(best.ms);
  assert.ok(Math.abs(S.altitude(90, 0, best.ms)) < 0.1);
  assert.ok(Math.abs(S.altitude(-90, 0, best.ms)) < 0.1);
  for (let lat = -85; lat <= 85; lat += 10) {
    assert.ok(Math.abs(S.altitude(lat, S.wrap180(sp.lon + 90), best.ms)) < 0.2, "east limb lat " + lat);
    assert.ok(Math.abs(S.altitude(lat, S.wrap180(sp.lon - 90), best.ms)) < 0.2, "west limb lat " + lat);
  }
  // flat map: the day/night edge is a vertical meridian, from pole to pole
  const g = S.flatBands(best.ms, 360, 180), px = (lon, lat) => g.rgba[(Math.floor((90 - lat) / 180 * 180) * 360 + Math.floor(S.wrap180(lon) + 180)) * 4 + 3];
  for (let lat = -80; lat <= 80; lat += 10) {
    assert.strictEqual(px(sp.lon + 80, lat), 0, "day side at lat " + lat);
    assert.ok(px(sp.lon + 100, lat) > 40, "night side at lat " + lat);
  }
});
const HUBS = [["LAX", 33.942, -118.408, "America/Los_Angeles"], ["JFK", 40.641, -73.778, "America/New_York"], ["DEN", 39.856, -104.674, "America/Denver"],
  ["SEA", 47.450, -122.309, "America/Los_Angeles"], ["MIA", 25.796, -80.287, "America/New_York"]];
t("sunrise and sunset for 5 hubs are within 2 minutes of the reference", () => {
  for (const [code, lat, lon, tz] of HUBS) for (const day of [Date.UTC(2026, 10, 14, 18, 0), Date.UTC(2026, 5, 21, 18, 0)]) {
    const s = S.hubSun(lat, lon, tz, day);
    const cs = ref.crossings(lat, lon, day - 30 * 3600000, day + 30 * 3600000);
    const rise = cs.find((c) => c.kind === "sunrise" && S.localDate(c.ms, tz) === S.localDate(day, tz));
    const set = cs.find((c) => c.kind === "sunset" && S.localDate(c.ms, tz) === S.localDate(day, tz));
    assert.ok(Math.abs(s.sunrise - rise.ms) < 120000, code + " sunrise off by " + (s.sunrise - rise.ms) / 1000 + " s");
    assert.ok(Math.abs(s.sunset - set.ms) < 120000, code + " sunset off by " + (s.sunset - set.ms) / 1000 + " s");
  }
});
t("known value: Los Angeles sunset on 14 Nov 2026 is about 4:50 pm PT", () => {
  const txt = S.hubCardText(33.942, -118.408, "America/Los_Angeles", Date.UTC(2026, 10, 14, 20, 0));
  assert.ok(/sunset 4:(4[7-9]|5[0-2]) pm PT/.test(txt), txt);
});
t("hub card text: day shows sunrise, sunset, daylight left and the word computed", () => {
  const txt = S.hubCardText(40.641, -73.778, "America/New_York", Date.UTC(2026, 10, 14, 18, 0));
  assert.ok(/^Sun: sunrise \d{1,2}:\d{2} am, sunset \d{1,2}:\d{2} pm ET, daylight left \d+ h \d{2} min · computed$/.test(txt), txt);
});
t("hub card text: night says no daylight left", () => {
  const txt = S.hubCardText(40.641, -73.778, "America/New_York", Date.UTC(2026, 10, 15, 4, 0));
  assert.ok(/no daylight left/.test(txt), txt);
});
t("polar night: no sunrise", () => {
  const txt = S.hubCardText(71.29, -156.77, "America/Anchorage", Date.UTC(2026, 11, 21, 20, 0));
  assert.ok(/no sunrise/.test(txt) && /no sunset/.test(txt) && /sun stays down/.test(txt), txt);
});
t("polar day: no sunset", () => {
  const txt = S.hubCardText(71.29, -156.77, "America/Anchorage", Date.UTC(2026, 5, 21, 20, 0));
  assert.ok(/no sunrise/.test(txt) && /no sunset/.test(txt) && /sun stays up/.test(txt), txt);
});
t("shade: night darker than twilight, twilight bands grow darker, day side is warm and light", () => {
  const a = (alt) => S.shade(alt)[3];
  assert.ok(a(-30) > a(-15) && a(-15) > a(-9) && a(-9) > a(-3) && a(-3) > a(-0.1) - 1e-9);
  const day = S.shade(40);
  assert.ok(day[0] > day[2] && day[3] > 0 && day[3] < 128);
  assert.strictEqual(S.shade(40, { dayTint: false })[3], 0);
});
t("flatBands: night side on the far side of the sun, day side clear, phone mode has no day tint", () => {
  const ms = Date.UTC(2026, 10, 14, 12, 0), g = S.flatBands(ms, 72, 36);
  const px = (lon, lat) => g.rgba[(Math.floor((90 - lat) / 180 * 36) * 72 + Math.floor((lon + 180) / 360 * 72)) * 4 + 3];
  assert.ok(px(180 - 1, -20) > 150, "antipode should be night");
  assert.strictEqual(px(0, -18), 0);
  assert.ok(g.sub.lat < -17 && g.sub.lat > -19);
});
t("hub card text: before sunrise says when the sun rises, not daylight left", () => {
  const txt = S.hubCardText(37.619, -122.375, "America/Los_Angeles", Date.UTC(2026, 10, 14, 9, 50));
  assert.ok(/sun rises in \d+ h \d{2} min/.test(txt) && !/daylight left/.test(txt), txt);
});
console.log(n + " tests passed");
