# Air Travel Desk site

Static site for www.airtraveldesklive.com. An automated job (`.github/workflows/status.yml`) fetches public feeds about every 5 minutes, writes the JSON files in `data/`, and publishes the site.

## Public data files (stable schema)

Other desks may read these files with credit to Air Travel Desk and the original source. Existing fields keep their names and meaning. New fields may be added. A removed or renamed field is announced to the Chief of Staff first.

- `data/state.json`: `updated_utc` (ISO time), `stale_feeds` (list), `events` (list of `id`, `kind`, `airport`, `reason`, `fields`, `source`, `status`, `sources`), `board` (list of `code`, `name`, `level` green/yellow/red, `kind`, `status`, `fill`, `avg_min`, `text`), `ticker` (list of `id`, `kind`, `tag`, `text`, `src`, `as_of_utc`, `t_utc`), `last_lines`, `zones`, `holiday`, `holding`, `layer_notes`.
- `data/status.json`: `updated_utc`, `board`, `events`, `sources` (the site status feed).
- `data/board-history.json`: `source`, `points` (list of hourly `hour_utc`, `t_utc`, `board`: airport code to `level` and `avg_min`).
- `data/national.json`: aircraft positions, ODbL 1.0. Credit adsb.lol.

Every item carries its source and a time. The charter for all desks is in `kits/desk/CHARTER.md` of the factory repo.
