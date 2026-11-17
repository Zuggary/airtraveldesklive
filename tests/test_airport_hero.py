"""Airport-wide hero meaning and actions, with synthetic FAA programs only."""
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tools import build_airport_pages as b

NOW = datetime(2026, 11, 17, 20, tzinfo=timezone.utc)

class AirportHero(unittest.TestCase):
    def test_program_meanings(self):
        cases = [('stop', [{'kind': 'ground_stop'}], 'departures to this airport'),
                 ('delay', [{'kind': 'ground_delay'}], 'arrivals are held'),
                 ('delay', [{'kind': 'delay', 'direction': 'Departure'}], 'departures from this airport'),
                 ('delay', [{'kind': 'delay', 'direction': 'Arrival'}], 'arrivals at this airport'),
                 ('closed', [{'kind': 'closure'}], 'arrivals and departures'),
                 ('clear', [], 'no FAA arrival or departure programs')]
        for level, events, expected in cases:
            with self.subTest(level=level, events=events):
                entry = {'level': level, 'events': events}
                text = b._status_meaning(entry, level, False)
                self.assertIn(expected, text)
                self.assertIn('individual flight', text)
                self.assertIn('Airport-wide', text)
                self.assertNotRegex(text, r'\d|expect|reopens')
                stale = b._status_meaning(entry, level, True)
                self.assertIn('Last known status', stale)
                self.assertNotIn('clear', stale.lower())
        self.assertIn('Last known status', b._status_meaning(None, 'clear', False))
        self.assertIn('Last known status', b._status_meaning({'events': []}, 'clear', False))

    def test_rendered_hero_and_shared_script(self):
        self.assertEqual(Path('airport.js').read_text(), b.airport_js())
        for level in ['clear', 'delay', 'stop', 'closed', 'unknown']:
            page = b.render_airport_page('ZZZ', guide_entry={}, guide_checked_date='', places_entry=None, places_fetched_date='', bts_data={}, build_date='2026-11-17', airport_info={'name':'Example Airport', 'short':'Example', 'tz':'UTC'}, live_entry={'level':level, 'events':[]}, live_updated_utc=NOW.isoformat(), now=NOW)
            self.assertEqual(page.count('id="checked-line"'), 1)
            self.assertLess(page.index('id="ap-meaning"'), page.index('id="checked-line"'))
            self.assertLess(page.index('id="checked-line"'), page.index('id="flight-btn"'))
            self.assertIn('id="flight-btn" class="btn btn-accent"', page)
            self.assertIn('id="stuck-btn" class="btn btn-ghost"', page)
            hero = page[page.index('<h1'):page.index('id="ap-reason"')]
            self.assertNotRegex(hero, r'held about|Expect|reopens about')
            for _, (_, _, url) in b.FLIGHT_STATUS.items():
                self.assertIn(url, page)

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
