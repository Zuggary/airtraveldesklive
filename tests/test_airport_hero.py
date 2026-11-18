"""Airport-wide hero meaning and actions, with synthetic FAA programs only."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tools import build_airport_pages as b

NOW = datetime(2026, 11, 17, 20, tzinfo=timezone.utc)

def render_page(code, entry, now=NOW, observed=NOW):
    return b.render_airport_page(
        code, guide_entry={}, guide_checked_date='', places_entry=None, places_fetched_date='',
        bts_data={}, build_date='2026-11-17',
        airport_info={'name': 'Example Airport', 'short': 'Example', 'tz': 'America/New_York',
                      'lat': 26.07, 'lon': -80.15},
        live_entry=entry, live_updated_utc=observed.isoformat(), now=now,
    )


class AirportHero(unittest.TestCase):
    def test_program_meanings(self):
        cases = [('stop', [{'kind': 'ground_stop'}], 'Flights bound for this airport are held at their departure airports.'),
                 ('delay', [{'kind': 'ground_delay'}], 'Flights bound for this airport are delayed at their departure airports.'),
                 ('delay', [{'kind': 'delay', 'direction': 'Departure'}], 'Departures are delayed airport-wide.'),
                 ('delay', [{'kind': 'delay', 'direction': 'Arrival'}], 'Arrivals are delayed airport-wide.'),
                 ('closed', [{'kind': 'closure'}], 'The airport is closed to arrivals and departures.'),
                 ('clear', [], 'No FAA program is listed. Your flight may still be delayed.')]
        for level, events, expected in cases:
            with self.subTest(level=level, events=events):
                entry = {'level': level, 'events': events}
                text = b._status_meaning(entry, level, False)
                self.assertEqual(text, expected + ' Check your flight with your airline.')
                self.assertNotRegex(text, r'\d|expect|reopens')
                stale = b._status_meaning(entry, level, True)
                self.assertIn('Last known status', stale)
                self.assertNotIn('clear', stale.lower())
        self.assertIn('Last known status', b._status_meaning(None, 'clear', False))
        self.assertIn('Last known status', b._status_meaning({'events': []}, 'clear', False))

    def test_rendered_hero_and_shared_script(self):
        self.assertEqual(Path('airport.js').read_text(), b.airport_js())
        for level in ['clear', 'delay', 'stop', 'closed', 'unknown']:
            page = render_page('ZZZ', {'level': level, 'events': []})
            self.assertEqual(page.count('id="checked-line"'), 1)
            self.assertLess(page.index('id="ap-meaning"'), page.index('id="checked-line"'))
            self.assertLess(page.index('id="checked-line"'), page.index('id="flight-btn"'))
            self.assertIn('id="flight-btn" class="btn btn-accent"', page)
            self.assertIn('id="stuck-btn" class="btn btn-ghost"', page)
            hero = page[page.index('<h1'):page.index('id="ap-reason"')]
            self.assertNotRegex(hero, r'held about|Expect|reopens about')
            for _, (_, _, url) in b.FLIGHT_STATUS.items():
                self.assertIn(url, page)

    def test_clear_reminder_and_mapped_reason(self):
        for level in ('clear', 'delay', 'stop', 'closed', 'unknown', None):
            entry = {
                'level': level, 'reason': 'TM Initiatives:MIT:WX',
                'events': [{'kind': 'delay', 'direction': 'Departure'}] if level == 'delay' else [],
            } if level else None
            page = render_page('ZZZ', entry)
            self.assertEqual('Your flight may still be delayed.' in page, level == 'clear')
            if level == 'delay':
                self.assertIn('Reason listed: Traffic spacing (miles-in-trail) due to weather.', page)
                self.assertNotIn('TM Initiatives', page)
        scheduled = {'level': 'closed', 'events': [{'kind': 'closure'}]}
        self.assertNotIn('Your flight may still be delayed.', b._status_meaning(scheduled, 'clear', False))
        stale = render_page('ZZZ', {'level': 'clear', 'events': []}, observed=NOW.replace(hour=18))
        self.assertNotIn('Your flight may still be delayed.', stale)
        self.assertIn('Last known status: airport-wide conditions are unconfirmed.', stale)

    def test_aerial_art_follows_airport_daylight_and_has_generic_fallback(self):
        for now, phase in [(NOW, 'day'), (NOW.replace(hour=4), 'night')]:
            with self.subTest(phase=phase):
                page = render_page('FLL', {'level': 'stop'}, now=now, observed=now)
                url = f'../assets/art/airports/ap-FLL-{phase}.webp'
                self.assertIn(f'type="image/webp" href="{url}"', page)
                self.assertIn(f'srcset="{url} 1600w" sizes="100vw"', page)
                self.assertIn(f'src="{url}" alt="" width="1600" height="700"', page)
                self.assertIn(b.AERIAL_CREDIT, page)
                self.assertIn('ap-hero--stop', page)
        fallback = render_page('FAI', {'level': 'clear'}, now=NOW.replace(hour=4), observed=NOW.replace(hour=4))
        self.assertRegex(fallback, r'data-art="airport-[a-z]+')
        self.assertNotIn('assets/art/airports/ap-FAI', fallback)
        self.assertNotIn(b.AERIAL_CREDIT, fallback)

    def test_script_builds_a_few_airports_with_synthetic_data(self):
        import json
        import tempfile
        from unittest.mock import patch
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            data = Path(tmp) / 'data'
            data.mkdir()
            codes = ['ATL', 'SFO', 'JFK']
            (data / 'airport-guide.json').write_text(json.dumps({'airports': {code: {} for code in codes}}))
            (data / 'airports.json').write_text(json.dumps({'updated_utc': NOW.isoformat(), 'airports': {
                'ATL': {'level':'stop', 'events':[{'kind':'ground_stop'}]},
                'SFO': {'level':'delay', 'events':[{'kind':'ground_delay'}]},
                'JFK': {'level':'clear', 'events':[]},
            }}))
            sitemap = root / 'sitemap.xml'
            before = sitemap.read_bytes()
            with patch.object(b.desk_airports, 'BUSIEST_100', codes):
                written = b.build_pages(data_dir=data, out_dir=Path(tmp) / 'airports', sitemap_path=None, now=NOW)
            self.assertEqual(len(written), 4)  # three airport pages and their index
            for path in written[:3]:
                page = path.read_text()
                self.assertIn('id="ap-meaning"', page)
                self.assertIn('id="flight-btn" class="btn btn-accent"', page)
            self.assertEqual(sitemap.read_bytes(), before)
