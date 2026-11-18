const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const watchSource = fs.readFileSync(path.join(__dirname, "../../watch.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../../style.css"), "utf8");
const w = require("../../watch.js");
const src = w.playerSrc(w.CHANNEL);
assert.strictEqual(src, "https://www.youtube.com/embed/live_stream?channel=UCtEAjmjCJdR-pHgcZtIFI9w&autoplay=0");

function element(tagName) {
  return {
    tagName,
    hidden: false,
    children: [],
    attributes: {},
    addEventListener() {},
    appendChild(child) { this.children.push(child); },
    insertBefore(child) { this.appendChild(child); },
    querySelector() { return null; },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}

const header = element("header");
header.parentNode = element("body");
const headerIn = element("div");
const document = {
  createElement(tagName) {
    assert.notStrictEqual(tagName, "iframe", "the player must wait for a click");
    return element(tagName);
  },
  querySelector(selector) {
    return { ".site-header": header, ".site-header .header-in": headerIn }[selector];
  },
  querySelectorAll() { return []; },
  addEventListener() {},
};
const window = {
  document,
  addEventListener() {},
  fetch() { assert.fail("initializing the watch pill must not fetch"); },
};

vm.runInNewContext(watchSource, { window });
const [button] = headerIn.children;
assert.strictEqual(button.className, "watch-btn");
const [dot, label] = button.children;
assert.strictEqual(label.textContent, "Live");
assert.strictEqual(dot.className, "watch-btn-dot");
assert.strictEqual(dot.hidden, false);
assert.strictEqual(dot.attributes["aria-hidden"], "true");
assert.match(css, /^\.watch-btn-dot\s*\{[^}]*background:\s*var\(--green\);/m);
