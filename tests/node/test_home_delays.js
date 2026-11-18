const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../app.js"), "utf8");
const A = require("../../lib.js");
const now = Date.parse("2026-11-17T20:00:00Z");

function element(tag) {
  return {
    tag,
    children: [],
    set textContent(value) { this.text = value; this.children = []; },
    get textContent() { return (this.text || "") + this.children.map(child => child.textContent).join(""); },
    appendChild(child) { this.children.push(child); }
  };
}

const box = element("div");
const state = {
  updated_utc: new Date(now).toISOString(),
  faa_updated_utc: new Date(now - 60_000).toISOString(),
  events: [
    { airport: "ZZZ", source: "FAA", kind: "ground_delay", fields: { avg: "1 hour and 5 minutes" }, reason: "TM Initiatives:MIT: WX" },
    { airport: "zzz", source: "FAA", kind: "delay" },
    { airport: "YYY", source: "FAA", kind: "ground_stop", reason: "EQUIPMENT" },
    { airport: "XXX", source: "FAA", kind: "closure", reason: "RUNWAY" },
  ]
};
const context = {
  window: { ATD: A },
  document: { createElement: tag => Object.assign(element(tag), { firstChild: { namespaceURI: "" } }), getElementById: id => id === "events" ? box : null },
  Date: class extends Date { static now() { return now; } },
  fixture: state
};
// Run the normal renderer with synthetic state and a text-only DOM.
vm.runInNewContext(source.replace("  init();", `
  D.state = fixture;
  allByCode.ZZZ = { name: "Example Airport" };
  window.renderEvents = renderEvents;
  window.reasonText = reasonText;
`), context);

const cases = {
  "TM Initiatives:MIT: WX": "Traffic spacing (miles-in-trail) due to weather",
  "tm initiatives: MINIT : VOLUME": "Traffic spacing (minutes-in-trail) due to traffic volume",
  "MIT": "Traffic spacing (miles-in-trail)",
  "WX:WIND": "Weather, wind",
  "WX": "Weather",
  "VOLUME: VOLUME": "Traffic volume",
  "EQUIPMENT; RUNWAY; STAFFING": "Equipment; Runway; Staffing",
  "TM Initiatives:  UNLISTED:: EXAMPLE": "Unlisted, Example",
  "": ""
};
for (const [raw, expected] of Object.entries(cases)) {
  assert.equal(context.window.reasonText(raw), expected, raw);
}

context.window.renderEvents();
assert.equal(box.children.length, 3);
const [stop, closure, delay] = box.children;
const [airport, status, reason, guide] = delay.children;
assert.equal(delay.children.length, 4);
assert.equal(airport.children[0].href, "/airports/ZZZ");
assert.equal(airport.children[0].children[1].textContent, "Example Airport");
assert.equal(status.textContent, "Delays · avg 1 h 5 min");
assert.equal(reason.textContent, cases["TM Initiatives:MIT: WX"]);
assert.equal(guide.href, "/help/ground-delay.html");
assert.equal(stop.children[1].textContent, "Ground stop");
assert.equal(stop.children[3].href, "/help/ground-stop.html");
assert.equal(closure.children[1].textContent, "Closed");
assert.equal(closure.children[3].href, "/help/");

state.faa_updated_utc = new Date(now - 3600_000).toISOString();
context.window.renderEvents();
assert.equal(box.children[0].children[1].textContent, "Ground stop listed");
assert.equal(box.children[1].children[1].textContent, "Closure listed");
assert.equal(box.children[2].children[1].textContent, "Delays listed · avg 1 h 5 min");
console.log("Home delay row checks passed");
