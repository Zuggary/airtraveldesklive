const assert = require("assert");
const w = require("../../watch.js");
const src = w.playerSrc(w.CHANNEL);
assert.strictEqual(src, "https://www.youtube.com/embed/live_stream?channel=UCtEAjmjCJdR-pHgcZtIFI9w&autoplay=0");
assert.ok(!src.includes("autoplay=1"));
const now = Date.parse("2026-11-17T01:00:00Z");
const fresh = { checked_utc: "2026-11-17T00:56:00Z", live: true, twitch_live: true };
assert.strictEqual(w.liveState({ ...fresh, youtube_live: true, twitch_live: false }, now), "live");
assert.strictEqual(w.liveState({ ...fresh, youtube_live: false }, now), "off");
assert.strictEqual(w.liveState({ ...fresh, youtube_live: null }, now), "unknown");
assert.strictEqual(w.liveState(fresh, now), "unknown");
assert.strictEqual(w.liveState({ ...fresh, youtube_live: "true" }, now), "unknown");
assert.strictEqual(w.liveState({ youtube_live: true, checked_utc: "2026-11-17T00:45:00Z" }, now), "live");
assert.strictEqual(w.liveState({ youtube_live: true, checked_utc: "2026-11-17T00:44:59Z" }, now), "unknown");
assert.strictEqual(w.liveState({ youtube_live: true, checked_utc: "2026-11-17T01:30:00Z" }, now), "unknown");
assert.strictEqual(w.liveState({ youtube_live: true, checked_utc: "invalid" }, now), "unknown");
assert.strictEqual(w.liveState({ youtube_live: true }, now), "unknown");
assert.strictEqual(w.liveState(null, now), "unknown");
console.log("watch ok");

// Exercise the facade with a minimal DOM: no third-party element exists until click.
const fs = require('fs'), vm = require('vm');
const created = [];
class Element {
  constructor(tag, cls = '') {
    this.tag = tag; this.className = cls; this.children = []; this.handlers = {}; this.style = {};
    this.classList = {add() {}, remove() {}};
  }
  setAttribute(k, v) { this[k] = v; }
  removeAttribute(k) { delete this[k]; }
  appendChild(n) { this.children.push(n); n.parentNode = this; return n; }
  insertBefore(n, before) { const i = this.children.indexOf(before); this.children.splice(i < 0 ? this.children.length : i, 0, n); n.parentNode = this; }
  removeChild(n) { this.children.splice(this.children.indexOf(n), 1); n.parentNode = null; }
  addEventListener(k, fn) { this.handlers[k] = fn; }
  removeEventListener() {}
  querySelector(selector) {
    for (const n of this.children) {
      if (selector.split(',').some(s => s.trim() === n.tag || s.trim() === '.' + n.className)) return n;
      const found = n.querySelector(selector); if (found) return found;
    }
    return null;
  }
  focus() {}
}
const parent = new Element('div'), header = new Element('header'), headerIn = new Element('div');
parent.appendChild(header); header.appendChild(headerIn);
const doc = {
  querySelector: s => s === '.site-header' ? header : s === '.site-header .header-in' ? headerIn : null,
  querySelectorAll: () => [],
  createElement: tag => { const n = new Element(tag); created.push(n); return n; },
  addEventListener() {}, removeEventListener() {}
};
const win = {document: doc, matchMedia: () => ({matches: true}), addEventListener() {}, removeEventListener() {},
  setTimeout: () => 1, clearTimeout() {}, scrollY: 0};
vm.runInNewContext(fs.readFileSync(require('path').join(__dirname, '../../watch.js'), 'utf8'), {window: win});
assert.strictEqual(created.filter(n => n.tag === 'iframe' || n.tag === 'script').length, 0);
const button = created.find(n => n.className === 'watch-btn');
button.handlers.click();
const frames = created.filter(n => n.tag === 'iframe');
assert.strictEqual(frames.length, 1);
assert.strictEqual(frames[0].src, src);
assert.strictEqual(frames[0].allow, 'fullscreen');
assert.strictEqual(created.filter(n => n.tag === 'script').length, 0);
button.handlers.click();
assert.strictEqual(frames[0].parentNode, null);
console.log('watch facade click/load/close ok');
