// alert.js: the model is null unless the alert is active, well formed and not expired; only https sources survive; limits hold.
const assert = require("assert");
const { alertModel } = require("../../alert.js");
const now = Date.parse("2026-11-16T23:30:00Z");
const base = { id: "x", active: true, level: "warning", label: "Confirmed by United", headline: "Outage", points: ["a", "b"],
  sources: [{ name: "AP", url: "https://example.org/a" }], updated_utc: "2026-11-16T23:25:00Z", expires_utc: "2026-11-17T03:00:00Z" };
assert.strictEqual(alertModel(null, now), null);
assert.strictEqual(alertModel({}, now), null);
assert.strictEqual(alertModel(Object.assign({}, base, { active: false }), now), null);
assert.strictEqual(alertModel(Object.assign({}, base, { headline: "" }), now), null);
assert.strictEqual(alertModel(Object.assign({}, base, { headline: "x".repeat(161) }), now), null);
assert.strictEqual(alertModel(Object.assign({}, base, { expires_utc: "2026-11-16T23:00:00Z" }), now), null);
assert.strictEqual(alertModel(Object.assign({}, base, { expires_utc: "not a date" }), now), null);
const m = alertModel(base, now);
assert.strictEqual(m.level, "warning");
assert.strictEqual(m.label, "Confirmed by United");
assert.deepStrictEqual(m.points, ["a", "b"]);
assert.strictEqual(m.sources.length, 1);
assert.strictEqual(alertModel(Object.assign({}, base, { sources: [{ name: "x", url: "http://insecure.example" }, { name: "y", url: "javascript:alert(1)" }] }), now).sources.length, 0);
assert.strictEqual(alertModel(Object.assign({}, base, { points: Array(9).fill("p") }), now).points.length, 5);
assert.strictEqual(alertModel(Object.assign({}, base, { points: ["x".repeat(400)] }), now).points[0].length, 300);
assert.strictEqual(alertModel(Object.assign({}, base, { level: "weird" }), now).level, "warning");
assert.strictEqual(alertModel(Object.assign({}, base, { level: "watch" }), now).level, "watch");
assert.strictEqual(alertModel(Object.assign({}, base, { expires_utc: undefined }), now).id, "x");
console.log("alert.js: all checks passed");
