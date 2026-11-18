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
  ['stop', [{kind:'ground_stop'}], 'Flights bound for this airport are held at their departure airports.'],
  ['delay', [{kind:'ground_delay'}], 'Flights bound for this airport are delayed'],
  ['delay', [{kind:'delay', direction:'Departure'}], 'Departures are delayed airport-wide.'],
  ['delay', [{kind:'delay', direction:'Arrival'}], 'Arrivals are delayed airport-wide.'],
  ['closed', [{kind:'closure'}], 'The airport is closed to arrivals and departures.'],
  ['clear', [], 'No FAA program is listed. Your flight may still be delayed.']
]) {
  const a = {level, events};
  const text = ctx.statusMeaning(a, level, false);
  assert(text.includes(expected), text);
  assert(text.endsWith(' Check your flight with your airline.'));
  assert.strictEqual(text.includes('Your flight may still be delayed.'), level === 'clear');
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
  verdict:() => node(),
  el:() => node(), srcLine:() => node()
});
ctx.document.createTextNode = x => ({textContent:x});
ctx.document.querySelector = () => null;
ctx.nodes['ap-meaning'] = node();
ctx.nodes['ap-reason'] = node();
vm.runInContext(source.match(/    var CARD_REASON_WORDS = [^]*?\n    function reasonText\([^]*?\n    }/)[0], ctx);
for (const raw of ['TM Initiatives:MIT:WX', 'TM Initiatives:MIT: WX', 'WX:WIND', 'RUNWAY']) {
  assert.strictEqual(ctx.reasonText(raw), require('../../lib.js').reasonText(raw));
}
for (const name of ['addHelpLinks', 'meaningElement', 'setUnavailable', 'render']) {
  vm.runInContext(source.match(new RegExp('    function ' + name + '\\([^]*?\\n    }'))[0], ctx);
}
for (const [level, kind, expected] of [['stop','ground_stop','Flights bound for this airport are held'], ['delay','ground_delay','Flights bound for this airport are delayed'], ['clear',null,'No FAA program is listed']]) {
  ctx.render({updated_utc:'2026-11-17T20:00:00Z', airports:{ZZZ:{level, reason:'TM Initiatives:MIT:WX', events:kind ? [{kind}] : []}}});
  assert(ctx.nodes['ap-meaning'].textContent.includes(expected));
  assert.strictEqual(ctx.nodes['ap-meaning'].hidden, false);
  assert.strictEqual(ctx.nodes['ap-meaning'].textContent.includes('Your flight may still be delayed.'), level === 'clear');
  assert.strictEqual(ctx.nodes['ap-reason'].textContent, level === 'clear' ? '' : 'Reason listed: Traffic spacing (miles-in-trail) due to weather.');
  assert.strictEqual(ctx.nodes['flight-btn'].className, 'btn btn-accent');
}
ctx.render({stale_feeds:['FAA'], airports:{ZZZ:{level:'clear', events:[]}}});
assert(ctx.nodes['ap-meaning'].textContent.includes('Last known status'));
assert(!ctx.nodes['ap-meaning'].textContent.includes('Your flight may still be delayed.'));
ctx.render({airports:{}});
assert(ctx.nodes['ap-meaning'].textContent.includes('Last known status'));
assert(!ctx.nodes['ap-meaning'].textContent.includes('Your flight may still be delayed.'));
assert.strictEqual(ctx.heading.textContent, 'Last known status');

// Existing generated pages gain the explanation beside their single source line.
delete ctx.nodes['ap-meaning'];
let inserted;
ctx.checkedLine.parentNode = {insertBefore(n, before) { inserted = n; assert.strictEqual(before, ctx.checkedLine); }};
ctx.render({airports:{ZZZ:{level:'delay', events:[{kind:'ground_delay'}]}}});
assert.strictEqual(inserted.id, 'ap-meaning');
assert(inserted.textContent.includes('Flights bound for this airport are delayed'));

const Sun = require('../../sun.js');
const artScript = source.match(/  \(function \(\) \{(?=\s*"use strict";\s*var KIND)[^]*?\n  \}\)\(\);/)[0];

function artElement(attributes = {}) {
  return {
    attributes,
    getAttribute: name => attributes[name],
    setAttribute: (name, value) => { attributes[name] = value; },
    removeAttribute: name => { delete attributes[name]; }
  };
}

function artPage(code, kind, lat, lon) {
  const src = artElement({type: 'image/avif'});
  const img = artElement({width: '1440', height: '810', srcset: 'generic'});
  const box = Object.assign(artElement(), {querySelector: tag => tag === 'source' ? src : img});
  const hero = {className: 'ap-hero ap-hero--delay'};
  let now = Date.parse('2026-11-17T20:00:00Z');
  let credit;
  const checked = {insertAdjacentElement: (_, element) => { credit = element; }};
  const artCtx = {
    ATD_ME: artElement({'data-code': code, 'data-kind': kind, 'data-lat': lat, 'data-lon': lon}),
    window: {Sun},
    document: {
      getElementById: id => ({'ap-hero': hero, 'checked-line': checked, 'ap-art-credit': credit})[id],
      querySelector: () => box,
      createElement: () => ({})
    },
    Date: class extends Date { static now() { return now; } }
  };
  vm.runInNewContext(artScript, artCtx);
  return {
    img, src, box, credit,
    update(time, level) { now = Date.parse(time); artCtx.window.ATDHeroArt(level); }
  };
}

const fll = artPage('FLL', 'coastal', 26.07, -80.15);
assert.strictEqual(fll.img.attributes.src, '../assets/art/airports/ap-FLL-day.webp');
assert.strictEqual(fll.src.attributes.srcset, '../assets/art/airports/ap-FLL-day.webp 1600w');
assert.strictEqual(fll.img.attributes.width, '1600');
assert.strictEqual(fll.img.attributes.height, '700');
assert.strictEqual(fll.credit.textContent, 'Aerial imagery: USGS NAIP (public domain). Night view is a rendering, not a photograph.');
fll.update('2026-11-18T04:00:00Z', 'stop');
assert.strictEqual(fll.img.attributes.src, '../assets/art/airports/ap-FLL-night.webp');
fll.update('2026-11-18T04:00:00Z', 'closed');
assert.strictEqual(fll.img.attributes.src, '../assets/art/airports/ap-FLL-night.webp');

const abq = artPage('FAI', 'mountain', 64.8, -147.86);
assert.strictEqual(abq.box.attributes['data-art'], 'ap-delay-day');
assert.strictEqual(abq.credit, undefined);
abq.update('2026-11-18T04:00:00Z', 'clear');
assert.strictEqual(abq.img.attributes.src, '../assets/art/airport-mountain-1440.jpg');

console.log('Airport hero checks passed');
