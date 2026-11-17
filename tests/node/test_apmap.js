// Run the actual map marker classification with synthetic FAA data, no browser.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require('path').join(__dirname, '../../apmap.js'), 'utf8');
const now = Date.parse('2026-11-17T20:00:00Z');
const ctx = {Date: {now: () => now, parse: Date.parse}, cards: {updated_utc: new Date(now).toISOString()}};
vm.createContext(ctx);
vm.runInContext(source.match(/  function level\(a\) {[^]*?\n  }/)[0], ctx);
for (const level of ['clear', 'delay', 'stop']) {
  ctx.cards = {updated_utc: new Date(now).toISOString()};
  assert.strictEqual(ctx.level({level}), level);
  ctx.cards.stale_feeds = ['FAA'];
  assert.strictEqual(ctx.level({level}), 'none');
  ctx.cards = {updated_utc: new Date(now - 31 * 60000).toISOString()};
  assert.strictEqual(ctx.level({level}), 'none');
}
for (const updated_utc of [null, 'invalid', new Date(now + 10 * 60000).toISOString()]) {
  ctx.cards = {updated_utc};
  assert.strictEqual(ctx.level({level: 'clear'}), 'none');
}
ctx.cards = {updated_utc: new Date(now).toISOString()};
assert.strictEqual(ctx.level({level: 'unknown'}), 'none');
assert.strictEqual(ctx.level({level: 'closed', events: [{kind:'closure'}]}), 'stop');
assert.ok(source.includes('col[m.lv] || col.muted'));
console.log('map stale markers ok');
