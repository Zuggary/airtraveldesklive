// Exercise actual live hero functions with made-up FAA data, without a browser.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require('path').join(__dirname, '../../airport.js'), 'utf8');
const ctx = {document: {getElementById: id => ctx.nodes[id]}, nodes: {}};
vm.createContext(ctx);
for (const name of ['statusMeaning', 'scaleHelp']) {
  vm.runInContext(source.match(new RegExp('    function ' + name + '\\([^]*?\\n    }'))[0], ctx);
}
for (const [level, events, expected] of [
  ['stop', [{kind:'ground_stop'}], 'departures to this airport'],
  ['delay', [{kind:'ground_delay'}], 'arrivals are held'],
  ['delay', [{kind:'delay', direction:'Departure'}], 'departures from this airport'],
  ['delay', [{kind:'delay', direction:'Arrival'}], 'arrivals at this airport'],
  ['closed', [{kind:'closure'}], 'arrivals and departures'],
  ['clear', [], 'no FAA arrival or departure programs']
]) {
  const a = {level, events};
  const text = ctx.statusMeaning(a, level, false);
  assert(text.includes(expected), text);
  assert(text.includes('Airport-wide') && text.includes('individual flight'));
  assert(!/\d|expect|reopens/.test(text));
  const stale = ctx.statusMeaning(a, level, true);
  assert(stale.includes('Last known status') && !stale.includes('clear'));
}
for (const a of [null, {}, {level:'unknown'}]) assert(ctx.statusMeaning(a, 'clear', false).includes('Last known status'));
ctx.nodes = {'help-card': {querySelector: () => null}, 'flight-btn': {}, 'stuck-btn': {}};
for (const level of ['stop', 'closed', 'delay', 'clear', 'stale', 'night', 'unknown', 'stop', 'clear']) {
  ctx.scaleHelp(level);
  assert.strictEqual(ctx.nodes['flight-btn'].className, 'btn btn-accent');
  assert.strictEqual(ctx.nodes['stuck-btn'].className, 'btn btn-ghost');
}
console.log('Airport hero checks passed');
function node() { return {textContent:'', hidden:false, className:'ap-hero ap-hero--clear', appendChild() {}, querySelectorAll() { return []; }}; }
Object.assign(ctx, {
  CODE:'ZZZ', INITIAL_LVL:'clear',
  heading:node(), checkedLine:node(), statusChip:node(), wxChip:node(), verdictEl:node(),
  hero:node(), box:node(), window:{},
  ageMin:() => 5, isStale:() => false, showStale() {},
  datelineText:() => 'Example observation', faaParts:() => ['Source: ', '.'],
  effLevel:a => a.level, badgeLabel:(a, lvl) => lvl,
  clockLabel:() => '12:00 PM', agoText:() => '5 min ago',
  BADGE_CLASS:{clear:'badge', stop:'badge', delay:'badge', closed:'badge'},
  verdict:() => node(), reasonPlain:x => x,
  el:() => node(), srcLine:() => node()
});
ctx.document.createTextNode = x => ({textContent:x});
ctx.document.querySelector = () => null;
ctx.nodes['ap-meaning'] = node();
for (const name of ['meaningElement', 'setUnavailable', 'render']) {
  vm.runInContext(source.match(new RegExp('    function ' + name + '\\([^]*?\\n    }'))[0], ctx);
}
for (const [level, kind, expected] of [['stop','ground_stop','departures to'], ['delay','ground_delay','arrivals are held'], ['clear',null,'no FAA arrival']]) {
  ctx.render({updated_utc:'2026-11-17T20:00:00Z', airports:{ZZZ:{level, events:kind ? [{kind}] : []}}});
  assert(ctx.nodes['ap-meaning'].textContent.includes(expected));
  assert.strictEqual(ctx.nodes['ap-meaning'].hidden, false);
  assert.strictEqual(ctx.nodes['flight-btn'].className, 'btn btn-accent');
}
ctx.render({stale_feeds:['FAA'], airports:{ZZZ:{level:'clear', events:[]}}});
assert(ctx.nodes['ap-meaning'].textContent.includes('Last known status'));
ctx.render({airports:{}});
assert(ctx.nodes['ap-meaning'].textContent.includes('Last known status'));
assert.strictEqual(ctx.heading.textContent, 'Last known status');

// Existing generated pages gain the explanation beside their single source line.
delete ctx.nodes['ap-meaning'];
let inserted;
ctx.checkedLine.parentNode = {insertBefore(n, before) { inserted = n; assert.strictEqual(before, ctx.checkedLine); }};
ctx.render({airports:{ZZZ:{level:'delay', events:[{kind:'ground_delay'}]}}});
assert.strictEqual(inserted.id, 'ap-meaning');
assert(inserted.textContent.includes('arrivals are held'));
