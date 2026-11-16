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
