"""Stream migration and judge fixes; synthetic airport data only."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tools import build_airport_pages as b

ROOT = Path(__file__).resolve().parents[1]

class StreamJudge(unittest.TestCase):
    def test_airline_action_leads_in_every_state(self):
        for level in ['clear', 'delay', 'stop', 'closed', 'stale']:
            text = '\n'.join(b._actions('ZZZ', [], '', level))
            self.assertLess(text.index('id="flight-btn"'), text.index('id="stuck-btn"'))
            self.assertIn('>Check flight status with your airline</summary>', text)

    def test_stale_prerender_and_refresh_agree(self):
        page = b.render_airport_page('ZZZ', guide_entry={}, guide_checked_date='',
            places_entry=None, places_fetched_date='', bts_data={}, build_date='2026-11-17',
            airport_info={'name':'Example Airport', 'short':'Example', 'tz':'UTC', 'lat':40, 'lon':-80},
            live_entry={'level':'clear', 'events':[]}, live_updated_utc='2026-11-17T18:00:00Z',
            now=datetime(2026, 11, 17, 20, tzinfo=timezone.utc))
        self.assertIn('id="ap-map" data-status="stale"', page)
        self.assertIn('ap-hero--stale', page)
        js = (ROOT / 'airport.js').read_text()
        self.assertEqual(js, b.airport_js())
        self.assertIn('map.setAttribute("data-status", stale || unknown ? "stale" : lvl)', js)

    def test_stream_links_and_facade(self):
        for name in ['index.html', 'about.html', 'privacy.html', 'stuck.html', 'sources.html', 'tv.html']:
            text = (ROOT / name).read_text()
            self.assertIn('https://www.youtube.com/@AirTravelDeskLive/live', text, name)
            self.assertNotIn('twitch', text.lower(), name)   # 22 Nov: Twitch is off the site
            self.assertNotRegex(text, r'<(?:iframe|script|link)[^>]+(?:src|href)="https://[^\"]*youtube')
