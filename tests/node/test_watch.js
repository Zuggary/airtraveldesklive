const assert = require("assert");
const w = require("../../watch.js");
const src = w.playerSrc(w.CHANNEL, w.PARENTS);
assert.ok(src.startsWith("https://player.twitch.tv/?channel=airtraveldesklive"));
assert.ok(src.includes("&parent=www.airtraveldesklive.com") && src.includes("&parent=airtraveldesklive.com"));
assert.ok(src.endsWith("&muted=true"));
const now = Date.parse("2026-11-17T01:00:00Z");
assert.strictEqual(w.liveState({ live: true, checked_utc: "2026-11-17T00:56:00Z" }, now), "live");
assert.strictEqual(w.liveState({ live: false, checked_utc: "2026-11-17T00:56:00Z" }, now), "off");
assert.strictEqual(w.liveState({ live: true, checked_utc: "2026-11-17T00:40:00Z" }, now), "unknown");      // older than 15 minutes: never a false green
assert.strictEqual(w.liveState({ live: true, checked_utc: "2026-11-17T01:30:00Z" }, now), "unknown");      // a time in the future
assert.strictEqual(w.liveState({ live: null, checked_utc: "2026-11-17T00:59:00Z" }, now), "unknown");
assert.strictEqual(w.liveState({ live: true }, now), "unknown");
assert.strictEqual(w.liveState(null, now), "unknown");
console.log("watch ok");
