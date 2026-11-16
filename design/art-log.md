# Art log

| Slot | File | Prompt (start) | Model | Licence | Host | Date | Cull |
|---|---|---|---|---|---|---|---|
| Home hero | assets/art/home-hero-{1440,2880}.{avif,jpg} | "night satellite-style view of a hub airport with crossing runways drawn in lines of light, deep navy blue darkness all around, sign yellow apron lights, emerald green taxi lights, small red obstruction lights, the airport placed on the right third of the frame, minimal stylised digital painting ..." (queue id AN34r2-hero-v4) | FLUX still via scripts/media.sh (render queue), 1280x720; SwinIR-M x4 (scripts/upscale.sh); downscaled to 2880 and 1440 | FLUX model licence as recorded for the factory still worker (FA16); SwinIR Apache-2.0; output ours | laptop (5070 Ti) | 2026-11-15 | 1 of 8 (v2 runner-up) |
| Airport hub | assets/art/airport-hub-* | "control tower and terminal roofline at blue hour seen from the airfield, deep navy sky, sign yellow window glow, emerald green runway lights ..." (AN34r2-hub-v4) | same | same | laptop | 2026-11-15 | 1 of 4 |
| Airport coastal | assets/art/airport-coastal-* | "palm silhouettes beside an airport runway at blue hour near the ocean, deep navy sky and sea, sign yellow and emerald green runway lights ..." (AN34r2-coastal-v4) | same | same | laptop | 2026-11-15 | 1 of 4 |
| Airport mountain | assets/art/airport-mountain-* | "a runway in a high valley beneath dark mountain ridges with snow at dusk ..." (AN34r2-mountain-v1) | same | same | laptop | 2026-11-15 | 1 of 4 |
| Airport desert | assets/art/airport-desert-* | "long runway stretching toward red rock buttes at twilight ..." (AN34r2-desert-v4) | same | same | laptop | 2026-11-15 | 1 of 4 |

Encoding: ffmpeg libsvtav1 (AVIF, crf 36 at 1440, 40 at 2880) and JPEG fallback through <picture>. Sizes: 20 to 45 KB AVIF, 95 to 215 KB JPEG.
Cull: by the builder from contact sheets (demo/an34/art/*-sheet.png). The vision judge runs on the 5090 desktop, which was in "game" mode (in use), so it was not used; this cull needs a judge pass.
Raw renders and 4x upscales: demo/an34/art/raw and demo/an34/art/up (factory repo, not committed).

## AN38 (2026-11-16): state art for the airport hero and the stuck guide

Plan: GPU stills from the render queue (88 jobs queued as `AN38-*`, outputs in demo/an38/art/raw in the factory repo). On 2026-11-16 the laptop render lane was blocked from 00:18 by a stale lock (`/tmp/media-lock-laptop`, an orphaned ssh from a timed-out ZS2 job; the laptop GPU sat at 100% and 11 GB) and no AN38 still was rendered. Per the job rule, the slots shipped as hand-written vector scenes (plan B), rendered to PNG and encoded the same way. A GPU still of the same file name replaces a vector scene with no code change.

| Slot | File | Prompt or source | Model | Licence | Host | Date | Cull |
|---|---|---|---|---|---|---|---|
| Hero, clear, day | assets/art/ap-clear-day-{720,1440}.{avif,jpg} | demo/an38/svgart.py `ap-clear-day` (vector scene: daytime airfield, terminal, tower, runway lights) | none (hand-written SVG, Chromium raster, ffmpeg libsvtav1 crf 28) | ours | Mac | 2026-11-16 | 1 of 1 (GPU variants queued) |
| Hero, delay, night / day | assets/art/ap-delay-{night,day}-* | svgart.py: a line of waiting aircraft, amber taxi-line lights | same | ours | Mac | 2026-11-16 | 1 of 1 |
| Hero, ground stop, night / day | assets/art/ap-stop-{night,day}-* | svgart.py: aircraft standing at gates, red stop bar across the taxiway | same | ours | Mac | 2026-11-16 | 1 of 1 |
| Hero, closed, night / day | assets/art/ap-closed-{night,day}-* | svgart.py: runway with an X of red lights | same | ours | Mac | 2026-11-16 | 1 of 1 |
| Hero, closed overnight (scheduled) | assets/art/ap-sched-night-* | svgart.py: sleeping airfield under a moon | same | ours | Mac | 2026-11-16 | 1 of 1 |
| Hero, clear, night | assets/art/airport-{hub,coastal,mountain,desert}-* | AN34 GPU stills (unchanged) | FLUX | see above | laptop | 2026-11-15 | AN34 |
| Stuck: meal, hotel, rebooking, refund | assets/art/step-*-960 and step-*-light-960 | demo/an38/svgsteps.py (night and pale paintings of each scene) | none (SVG) | ours | Mac | 2026-11-16 | 1 of 1 |
| Stuck: card head delayed, cancelled | assets/art/state-{delayed,cancelled}-960 and -light-960 | svgsteps.py | none (SVG) | ours | Mac | 2026-11-16 | 1 of 1 |

Light page: each step and head picture has a pale painting (`-light`) that stuck.js picks by the theme switch or the system setting. The airport hero is a dark band in both themes (AN34 rule).
Honest labelling: one footer line on every page type that carries art (`Pictures on this site are generated illustrations, not photos of real events or airports.`) and one line under the stuck card head. No pill on a picture.

## AN38 day stills, batch 1 (2026-11-16)
| Asset | Source render | Pick | Encode |
|---|---|---|---|
| assets/art/ap-clear-day-{720,1440} | demo/an38/art/raw/clear-day-v8.png (5090, AN38-clear-day-v8) | blind Gemini panel median 8.5 of 8 variants | demo/an38/encode.sh crf 42 (AVIF 2.6 / 5.1 KB) |
| assets/art/ap-delay-day-{720,1440} | demo/an38/art/raw/delay-day-v8.png (AN38-delay-day-v8) | panel median 8.0 | crf 42 (AVIF 2.8 / 5.4 KB) |
Not used: stop-day-v8 (median 8.5, but it shows a "CLOSED" text sign) and closed-day-v8 (6.5, a red X glyph). Those two keep their placeholders until re-renders land.
Checks: AA contrast on ATL, BWI, SFO at 375 and 1440 (small text 5.4:1 or more); Lighthouse mobile vs live ATL +6 ms, BWI +73 ms LCP, perf equal.
