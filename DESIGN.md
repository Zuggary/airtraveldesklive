# Air Travel Desk: design direction (AN32)

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
