const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const watchSource = fs.readFileSync(path.join(__dirname, "../../watch.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../style.css"), "utf8");
const w = require("../../watch.js");
const src = w.playerSrc(w.CHANNEL);
assert.strictEqual(src, "https://www.youtube.com/embed/live_stream?channel=UCtEAjmjCJdR-pHgcZtIFI9w&autoplay=0");
assert.strictEqual(w.playerSrc(w.CHANNEL, "PGMoCSMC5oU"), "https://www.youtube.com/embed/PGMoCSMC5oU?autoplay=0");
assert.strictEqual(w.playerSrc(w.CHANNEL, "bad id"), src, "a bad id falls back to the channel stream");

let focused;
let allowIframe = false;

function element(tagName) {
  return {
    tagName,
    hidden: false,
    children: [],
    attributes: {},
    isConnected: true,
    handlers: {},
    style: {},
    classList: new Set(),
    addEventListener(name, handler) { this.handlers[name] = handler; },
    appendChild(child) { child.parentNode = this; this.children.push(child); },
    removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
    focus() { focused = this; },
    insertBefore(child) { this.appendChild(child); },
    querySelector(selector) {
      return this.children.find(child => child.tagName === "iframe" && selector.includes("iframe"));
    },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}

const header = element("header");
header.parentNode = element("body");
const headerIn = element("div");
let teaser = element("button");
const documentHandlers = {};
const timers = [];

const document = {
  createElement(tagName) {
    if (!allowIframe) assert.notStrictEqual(tagName, "iframe", "the player must wait for a click");
    return element(tagName);
  },
  querySelector(selector) {
    return { ".site-header": header, ".site-header .header-in": headerIn }[selector];
  },
  querySelectorAll() { return [teaser]; },
  addEventListener(name, handler) { (documentHandlers[name] ||= []).push(handler); },
};
const window = {
  document,
  matchMedia: () => ({ matches: true }),
  clearTimeout() {},
  setTimeout(handler) { timers.push(handler); },
  addEventListener() {},
  fetch(url) { assert.ok(allowIframe, "initializing the watch pill must not fetch"); assert.ok(url === "/data/live-main.json" || url === "/data/live-music.json"); return Promise.resolve({ ok: false }); },      /* only the first press may ask for the main broadcast id */
};

vm.runInNewContext(watchSource, { window });
const [button] = headerIn.children;
assert.strictEqual(button.className, "watch-btn");
const [dot, label] = button.children;
assert.strictEqual(label.textContent, "Live stream");
assert.strictEqual(dot.className, "watch-btn-dot");
assert.strictEqual(dot.hidden, false);
assert.strictEqual(dot.attributes["aria-hidden"], "true");
assert.match(css, /^\.watch-btn-dot\s*\{[^}]*background:\s*var\(--green\);/m);

const [drawer] = header.parentNode.children;
const [bar] = drawer.children[0].children;
const close = bar.children.find(child => child.className === "watch-close");
drawer.classList.remove = drawer.classList.delete;
const frame = drawer.children[0].children[1];
frame.classList.remove = frame.classList.delete;
const click = target => {
  const event = { target: { closest: selector => selector === "[data-watch-open]" ? target : null } };
  for (const handler of documentHandlers.click) handler(event);
};

assert.equal(teaser.attributes["aria-controls"], drawer.id);
assert.equal(drawer.inert, true);
allowIframe = true;
click(teaser);
assert.equal(drawer.inert, false);
assert.equal(focused, close);
click(teaser);
assert.equal(focused, teaser);
assert.equal(drawer.inert, true);
assert.equal(drawer.hidden, false);
timers.shift()();
assert.equal(drawer.hidden, true);

// A replacement teaser uses the same delegated listener.
teaser.isConnected = false;
teaser = element("button");
click(teaser);
assert.equal(teaser.attributes["aria-expanded"], "true");
teaser.isConnected = false;
close.handlers.click();
assert.equal(focused, button);

button.handlers.click();
click(button);
assert.equal(button.attributes["aria-expanded"], "true", "a marked header button must toggle once");
