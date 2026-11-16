# Air Travel Desk: design direction (AN34, replaces AN32 where they differ)

Winner of the AN34 panel: the "modern departures board" prototype (demo/an34/board), with grafts from "calm" and "map".
Panel notes: research/AN34-designs.md.

## What the site is in 5 seconds
- Home: one verdict at display size ("98 of the 100 busiest US airports have no FAA delays right now"), one plain line
  naming the exceptions, then a big "Check your airport" search with one-tap picks (yours, then trouble now).
- Airport page: a giant code lockup on a surface tinted by status, and an H1 that is the answer in words
  ("Flights into San Francisco are held about 2 h 46 min.").

## System
- Surfaces: ground (--navy), panel (--surface), raised (--surface-alt, --surface-3); hairlines --line and --border.
- One radius family: 14 px panels, 12 px controls, pills for chips and badges.
- Type: Barlow Condensed for codes, numbers and verdicts; Public Sans for text. Title size --fs-title; display --fs-display.
- Status colour is the only strong colour: green clear, sign-yellow delay (dark ink on it), red stop or closed.
- Dark by default; a warm light theme follows prefers-color-scheme (style.css, html selector, tokens only).
- Icons are drawn stroke icons on a 24 grid, inline, no outside requests.

## Home order
Verdict, trouble line, search and picks, source line; map beside it on wide screens (tap a dot for the answer card).
Then "Delays and closures now" (big departures rows: code, plain meaning, one big number), the 30-airport board
(rows of links with a 24-hour strip), changes and the 24-hour chart, travel volume (TSA bars, Thanksgiving, BTS),
the help band, Lantern Drift. Twitch and TV mode live in the footer.

## Airport page order
Tinted hero (lockup, verdict H1, one explanation, "Flying out of X?" note and "What is a ground delay?" for ground
delays, status chips, source line) with a regional radar map on wide screens (apmap.js). Then "Right now" tiles
(FAA, weather now, next 3 hours, daylight; each with its source and age), the help card scaled to the state
(quiet when clear, three steps when delayed or closed; sticky right rail on wide screens), the last 3 days,
a typical month (BTS), official pages as an icon grid, hotels folded, facts, sources folded.

## Round 2 (AN34 r2, CoS default, open for Zach)
- The hero is a dark band in both themes (style.css `.band` redefines the dark tokens inside it), on GPU-made
  night-airfield art: home band full width; airport heroes by airport type (hub, coastal, mountain, desert);
  the stuck page title band reuses the hub picture. Art is decoration only; files and prompts in design/art-log.md.
- Airport page order: hero (lockup, answer, one action strip: "I'm stuck guide" and "Check my flight"), then the
  record (last 3 days beside a typical month), then weather and daylight, help, official pages, hotels, sources, about (facts fold here).
- Every clock and date on the home page is in the visitor's own zone; the pre-render uses Eastern.
- Wind in mph, temperature in deg F (METAR). Captions 13 px or more.

## Copy rules (unchanged)
Every number carries its source and age. "May be owed" / "possibly owed", never "must cover"; the airline decides
each claim. Arrivals and departures are kept apart for ground delays.

---

# Earlier direction (AN32)

Rules used: `research/FA7-web-design-rules.md` (steps 1 to 3, slop list, font rules).

## The idea
The site is a departures board you can read from across a terminal, not a dashboard of cards.
Reference by eye (public pages, not copied): airport wayfinding signs (FHWA/Clearview style), the FAA's own
NAS status table (plain rows, no chrome), split-flap departure boards, the New York Times weather and
election result pages (one big answer, small print for sources), Swiss railway timetables (rows, hairlines, no boxes).

## What we take from each
- Wayfinding signs: big condensed capitals for codes, strong colour as a status signal only, nothing decorative.
- FAA NAS table: rows with codes on the left and reason text on the right. Honest and dense. We keep the rows and
  translate the jargon.
- NYT result pages: the answer is a sentence at 40+ px; everything else is below it and smaller.
- Rail timetables: hairline row dividers, tabular numbers, no card borders.

## Layout
- One column of content, max 72rem, left aligned. A wide board on desktop uses a 2 column row list, not a card grid.
- The answer comes first on every page: a sentence in display type, then the status rows.
- Sections are separated by space and one hairline, never by boxes. Cards only for the one thing that is a object
  you act on: the "what you may be owed" block.
- 375 px is designed first. The board is a single list of rows at 375 px.

## Type
- Display and codes: Barlow Condensed 600/700 (OFL, local file in `fonts/`). Used for airport codes, the answer sentence
  and section headings. Size with clamp(); line-height 1.05 or more.
- Text: Public Sans variable (OFL, local file in `fonts/`), 16 px base, tabular figures for numbers.
- Fallback: matched `@font-face` fallbacks with size-adjust on Arial, tested with the site fonts blocked.

## Colour
Dark stays (people use it in dim gates and it matches the stream), but moves off the stock navy-and-cyan.
- Ground: #0b0f14 (ink), rows: hairlines #263040, text #e9edf2, muted #9aa7b6.
- Status uses the signage colours and is the only strong colour on the page:
  clear #3ccf91, delay #f5b301 (sign yellow, black text on it), stop #ff4d3d, closed #b06bff-free: use #c9d1da outline.
- One accent for links and focus: #7cc4ff.
- No gradients, no glows, no purple.

## Motion
Only a 120 ms colour change on rows and the fade of new data. `prefers-reduced-motion` removes it.

## Signature moment
The status strip at the top: one row per US airport with a program, in the order of the worst first, each row reading
"EWR  Ground stop  weather, thunderstorms  since 2:10 pm  to 4:00 pm". It is the first thing at 375 px.

## Things we remove
Section kickers and counters, the stock illustration card, the game promo block, the Twitch embed in the page
(a single small link stays), repeated status pills, the "Latest" TAF feed on the home page (it moves to the airport
page where it belongs), emoji and decorative icons.

## Copy rules
Plain, first person plural only when we did something ("we read the FAA feed every 5 minutes"). Every number carries its
source and its age. No "may be owed" wording changes: "possibly owed", never "must cover".
