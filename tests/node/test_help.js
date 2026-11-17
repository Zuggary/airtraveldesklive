// Test actual hero helper with a minimal DOM and no browser or network.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(require('path').join(__dirname, '../../airport.js'), 'utf8');
const ctx = {el: (tag, cls, text) => ({tag, text})};
vm.createContext(ctx);
vm.runInContext(source.match(/    function addHelpLinks\([^]*?\n    }/)[0], ctx);
const children = [];
ctx.addHelpLinks({appendChild: child => children.push(child)});
assert.deepStrictEqual(children.filter(c => c.tag === 'a').map(c => c.href), [
  '/help/ground-stop.html', '/help/ground-delay.html', '/help/weather-disruption.html', '/help/cancellation.html'
]);
ctx.addHelpLinks(null);
console.log('Help links passed');
