const assert = require('assert');
const fs = require('fs');
const A = require('../../lib.js');
const audit = JSON.parse(fs.readFileSync(require('path').join(__dirname, '../FRESHNESS-AUDIT.md'), 'utf8').match(/```json\n([\s\S]*?)\n```/)[1]);
const now = Date.parse('2026-11-17T20:00:00Z');
const state = {updated_utc: new Date(now - 3 * 3600000).toISOString(), board: []};
assert(A.isStale((now - Date.parse(state.updated_utc)) / 60000));
assert(!A.isStale(5));
assert(A.isStale(null));
for (const kind of audit.event_kinds) {
  const stale = A.impactText({kind}, 'Example', true);
  const fresh = A.impactText({kind}, 'Example', false);
  for (const claim of audit.forbidden_stale) assert(!stale.includes(claim), stale);
  assert.notStrictEqual(stale, fresh);
}
const airports = Array.from({length: 5}, (_, i) => ({code: 'X' + i, level: 'stop', events: [{kind: 'ground_stop'}]}));
assert(A.troubleLine(airports, true).includes('more airports had'));
assert(!A.troubleLine(airports, true).includes(' has '));
assert.strictEqual(A.nationalSummary([{level:'clear'}], ''), 'No FAA delays at the 100 busiest airports.');
assert(!A.nationalSummary([{level:'clear'}], 'as of 1 pm').includes('right now'));
assert.strictEqual(A.nationalSummary([], ''), 'Airport readings unavailable');
// Exercise actual home render functions with a tiny text-only DOM, no browser.
const vm = require('vm');
const source = fs.readFileSync(require('path').join(__dirname, '../../app.js'), 'utf8');
function element(tag, cls, value) {
  return {children: [], textContent: value || '', setAttribute() {}, appendChild(n) { this.children.push(n); }};
}
const ctx = {A, D:{state}, Date: class extends Date { static now() { return now; } }, Intl,
  el: element, currentCode: '', LEVEL_WORD:{clear:'No FAA program listed',stop:'Ground stop'},
  histCells:() => element(), histTrouble:() => true, nbspUnits:x=>x, shortDur:x=>String(x)};
vm.createContext(ctx);
for (const name of ['ageMin','ageText','isStaleIso','fmtTime','shortCheckText','asOfText','staleChipText','rowStatus','chipFor','makeTile']) {
  const body = source.match(new RegExp('  function ' + name + '\\([^]*?\\n  }'))[0];
  vm.runInContext(body, ctx);
}
function text(n) { return n.textContent + n.children.map(text).join(' '); }
const a = {code:'ZZZ',name:'Example',level:'clear',events:[]};
assert(!/as of|hours ago/i.test(text(ctx.makeTile(a, {}))));
assert(text(ctx.makeTile(a, {})).includes('No FAA program listed'));
assert(!/as of|hours ago/i.test(text(ctx.chipFor(a))));
ctx.D.state = {updated_utc:new Date(now - 5 * 60000).toISOString()};
assert(text(ctx.makeTile(a, {})).includes('listed now'));
assert(!text(ctx.chipFor(a)).includes('As of'));
ctx.D.state.stale_feeds = ['FAA'];
assert(!/as of|hours ago/i.test(text(ctx.makeTile(a, {}))));
assert(text(ctx.makeTile(a, {})).includes('No FAA program listed'));

ctx.D.state = state;
assert(text(ctx.chipFor({...a, faa_updated_utc: state.updated_utc})).includes('None listed'));
assert(!text(ctx.chipFor({...a, faa_updated_utc: state.updated_utc})).includes('as of'));
assert(!text(ctx.chipFor({...a, faa_updated_utc: '2026-11-17T16:00:00Z'})).includes('as of'));
for (const level of ['clear', 'stop', 'delay']) {
  const sample = {...a, level};
  for (const rendered of [ctx.makeTile(sample, {}), ctx.chipFor(sample)]) {
    for (const claim of audit.forbidden_stale) assert(!text(rendered).includes(claim), text(rendered));
    assert(!/as of|hours ago/i.test(text(rendered)));
  }
}
for (const [word, expected] of [['No FAA delays reported', 'No FAA program listed'], ['Closed', 'Closure listed'], ['Ground stop', 'Delay listed']]) {
  assert.strictEqual(ctx.staleChipText(word, state.updated_utc), expected);
}
assert.strictEqual(A.nationalSummary([a], '12:00 PM (3 hours ago)'),
  'Last FAA check 12:00 PM (3 hours ago)');
const css = fs.readFileSync(require('path').join(__dirname, '../../style.css'), 'utf8');
assert(/\.pick \{[^}]*white-space: nowrap/.test(css));
assert(/\.pick-tail \{[^}]*white-space: nowrap/.test(css));
// TV status chips and map tiles inherit the dated, prominent stale banner.
const tv = fs.readFileSync(require('path').join(__dirname, '../../tv.html'), 'utf8');
const nodes = {};
function node(id) {
  return nodes[id] || (nodes[id] = {textContent:'', className:'', classList:{add(){},remove(){}}});
}
const tvctx = {Date:ctx.Date, Intl, currentState:{...state,zones:{PT:{affected:0,hubs:1}}},
  document:{getElementById:node,querySelectorAll:()=>[]},
  fmtClock:()=>({format:()=> '12:00'}), isDay:()=>true,tickCountdowns(){}, updateBoardMode(){}, updateBoardNote(){}};
vm.createContext(tvctx);
for (const name of ['ageText','faaStale','faaAsOf','updateStaleBanner','updateClocks']) {
  vm.runInContext(tv.match(new RegExp('  function ' + name + '\\([^]*?\\n  }'))[0], tvctx);
}
tvctx.updateClocks();
assert.strictEqual(node('chip-PT').textContent, 'No FAA program listed');
assert(/Nov 17, 2026/.test(node('stale-detail').textContent));
assert(/3 h ago/.test(node('stale-detail').textContent));
const boardNode = {dataset:{n:'1'},children:[{dataset:{code:'ZZZ'},className:'',firstChild:{style:{}},
  querySelector: sel=>node(sel)}]};
tvctx.document.getElementById = id=>id === 'board' ? boardNode : node(id);
tvctx.escapeHtml = x=>x;
tvctx.TREND_WORD = {}; tvctx.TREND_MARK = {};
vm.runInContext(tv.match(/  function renderBoard\([^]*?\n  }/)[0], tvctx);
tvctx.renderBoard([{code:'ZZZ',level:'green'}]);
assert.strictEqual(node('.mins').textContent, 'No FAA program listed');
assert(/\.zchip \{[^}]*white-space: nowrap/.test(tv));
assert(/\.tile \{[^}]*white-space: nowrap/.test(tv));
ctx.$ = node;
ctx.STALE_MIN = A.STALE_MIN;
ctx.setStale = (n, s)=>{n.textContent = s;};
ctx.oldText = A.oldText;
vm.runInContext(source.match(/  function renderFreshness\([^]*?\n  }/)[0], ctx);
ctx.renderFreshness();
for (const id of ['board-date', 'mine-date', 'map-date']) {
  assert.strictEqual(node(id).textContent, '');
  assert.strictEqual(node(id).hidden, true);
}
for (const minutes of [5, 180, 4320, 14400]) {
  ctx.D.state = {updated_utc: new Date(now - minutes * 60000).toISOString()};
  ctx.renderFreshness();
  const verdict = A.nationalSummary([a], ctx.shortCheckText(ctx.D.state.updated_utc));
  assert(verdict.length <= 60, verdict);
}
ctx.D.state = {updated_utc: new Date(now - 4320 * 60000).toISOString()};
ctx.allAirports = [a]; ctx.airports = [a];
ctx.faaEvents = () => []; ctx.atMs = () => Date.parse(ctx.D.state.updated_utc);
ctx.renderChips = () => {}; ctx.nbspUnits = x => x;
node('summary').setAttribute = () => {};
vm.runInContext(source.match(/  function renderSummary\([^]*?\n  }/)[0], ctx);
ctx.renderFreshness(); ctx.renderSummary();
assert(node('summary').textContent.length <= 60);
assert(node('trouble-line').textContent.includes('No FAA programs were listed'));
assert(node('trouble-line').textContent.endsWith('Current conditions unknown.'));
const homeText = ['summary', 'trouble-line', 'board-date', 'mine-date', 'map-date', 'updated-line', 'trouble-heading', 'stale-notice'].map(id => node(id).textContent).join(' ');
assert((homeText.match(/\d{1,2}:\d{2} [AP]M/g) || []).length <= 2);
for (const claim of audit.forbidden_stale) assert(!homeText.includes(claim), homeText);
ctx.D.state = {};
assert.strictEqual(ctx.shortCheckText(''), 'time unknown');
assert(/\.page-home \.verdict \{ font-size: var\(--fs-display\)/.test(css));
assert(/\.tile-level, \.tile-ok \{ white-space: nowrap/.test(css));

console.log('freshness: all checks passed');
