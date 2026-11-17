const assert = require("assert");
const w = require("../../watch.js");
const src = w.playerSrc(w.CHANNEL, w.PARENTS);
assert.ok(src.startsWith("https://player.twitch.tv/?channel=airtraveldesklive"));
assert.ok(src.includes("&parent=www.airtraveldesklive.com") && src.includes("&parent=airtraveldesklive.com"));
assert.ok(src.endsWith("&muted=true"));
console.log("watch ok");
