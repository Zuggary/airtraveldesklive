"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const storyJs = require("../../stories/thanksgiving/story.js");

assert.strictEqual(storyJs.fmtInt(1956731), "1,956,731");
assert.strictEqual(storyJs.fmtInt(null), "Not yet published by TSA");
assert.strictEqual(storyJs.millions(3134613), "3.13 million");
assert.strictEqual(storyJs.millionsShort(1956731), "1.96M");

const pctUp = storyJs.signedPct(1956731, 1816617);
assert.strictEqual(pctUp.text, "+7.7%");
assert.strictEqual(pctUp.cls, "story-delta--up");

const pctDown = storyJs.signedPct(2324228, 2456308);
assert.strictEqual(pctDown.text, "-5.4%");
assert.strictEqual(pctDown.cls, "story-delta--down");

const pctMissing = storyJs.signedPct(null, 2753036);
assert.strictEqual(pctMissing.text, "awaiting TSA count");
assert.strictEqual(pctMissing.cls, "story-delta--warn");

assert.strictEqual(storyJs.signedDiff(1956731, 1816617), "+140,114");

// Tooltip clamping keeps tips inside both 375px phone and 1440px desktop viewports
const tipPhone = storyJs.clampTipPos(355, 30, 375, 812, 220, 70);
assert(tipPhone.x + 220 <= 375 - 12, "tooltip should not clip right edge on 375px phone");
assert(tipPhone.y >= 12, "tooltip should not clip top edge");

// Cursor pill horizontal clamping keeps sightline tags inside plot edges
assert.strictEqual(storyJs.clampCursorDx(400, 54, 48, 744), 0);
assert(storyJs.clampCursorDx(60, 54, 48, 744) + 60 - 54 >= 48, "left edge clamp");
assert(storyJs.clampCursorDx(730, 54, 48, 744) + 730 + 54 <= 744, "right edge clamp");

// Dynamic year takeaway calculation
const mockData = {
  target_year: 2026,
  core_counted: 0,
  trail7_label: "Nov 11 to Nov 17",
  trail7_now: 16246108,
  trail7_cmp: { "2019": { total: 15000000 } },
  years: { "2019": { peak_label: "Dec 1, 2019", peak_count: 2882915 } }
};
const tk = storyJs.yearTakeaway(mockData, "2019");
assert(tk.includes("Across the 7 days (Nov 11 to Nov 17), TSA screened 16,246,108 travelers this year vs 15,000,000 in 2019"), tk);
assert(tk.includes("+8.3% vs 2019"), tk);
assert(tk.includes("2.88 million"), tk);

const mockCorrData = {
  target_year: 2026,
  core_counted: 0,
  corr_counted: 3,
  corr_label: "Nov 15 to Nov 17",
  corr_now: 7232819,
  corr_cmp: { "2025": { total: 6770265 } },
  years: { "2025": { peak_label: "Nov 30, 2025", peak_count: 3134613 } }
};
const tkCorr = storyJs.yearTakeaway(mockCorrData, "2025");
assert(tkCorr.includes("7,232,819 travelers this year vs 6,770,265 in 2025 (+6.8%)"), tkCorr);

// Verify story.js makes zero network requests or storage calls
const src = fs.readFileSync(path.join(__dirname, "../../stories/thanksgiving/story.js"), "utf8");
assert(!/\bfetch\s*\(/.test(src), "story.js must not call fetch()");
assert(!/XMLHttpRequest/.test(src), "story.js must not use XMLHttpRequest");
assert(!/localStorage|sessionStorage|document\.cookie/.test(src), "story.js must not access storage/cookies");

console.log("story_ui: all checks passed");
