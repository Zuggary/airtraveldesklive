"""Offline freshness regressions using invented FAA readings and the audit's claim list."""
import html
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tools import prerender_home as ph, prerender_text as pt, build_airport_pages as bap

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 17, 20, tzinfo=timezone.utc)
AUDIT = ROOT / 'tests/FRESHNESS-AUDIT.md'


def claims():
    return json.loads(re.search(r'```json\n(.*?)\n```', AUDIT.read_text(), re.S)[1])


class Freshness(unittest.TestCase):
    def render(self, age, missing=False, raw=False):
        stamp = (NOW - timedelta(minutes=age)).isoformat()
        airport = dict(code='ZZZ', name='Example Airport', short='Example', level='clear', events=[], tz='America/New_York')
        state = dict(updated_utc=stamp, board=[dict(code='ZZZ', level='green')], events=[])
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d)
            (dest / 'state.json').write_text(json.dumps(state))
            if not missing:
                (dest / 'airports.json').write_text(json.dumps(dict(updated_utc=stamp, airports={'ZZZ': airport})))
            page = ph.prerender((ROOT / 'index.html').read_text(), dest, NOW)
        return (page if raw else html.unescape(re.sub('<[^>]+>', ' ', page))), airport, stamp

    def test_stale_and_fresh_home(self):
        stale, _, _ = self.render(180)
        fresh, _, _ = self.render(5)
        for phrase in claims()['forbidden_stale']:
            self.assertNotIn(phrase, stale, phrase)
        self.assertIn('Delays and closures (last check)', stale)
        self.assertNotIn('FAA status as of', stale)
        self.assertIn('Delays and closures now', fresh)
        self.assertIn('right now', fresh)
        self.assertIn('Last FAA check 12:00 PM (3 hours ago)', stale)

    def test_stale_home_scan_budget(self):
        for age in (31, 180, 4320, 14400):
            for missing in (False, True):
                page, _, _ = self.render(age, missing, raw=True)
                text = html.unescape(re.sub('<[^>]+>', ' ', page))
                h1 = html.unescape(re.sub('<[^>]+>', '', re.search(r'<h1[^>]*id="summary"[^>]*>(.*?)</h1>', page, re.S)[1]))
                self.assertLessEqual(len(h1), 60)
                self.assertTrue(h1.startswith('Last FAA check '))
                self.assertLessEqual(len(re.findall(r'\d{1,2}:\d{2} [AP]M', text)), 2)
                for phrase in claims()['forbidden_stale']:
                    self.assertNotIn(phrase, text)
                stamp = (NOW - timedelta(minutes=age)).isoformat()
                verdict = ph.national_summary([], pt.short_check_text(stamp, ph.HOME_TZ, NOW))
                self.assertLessEqual(len(verdict), 60)
                self.assertIn(verdict, text)
        text, _, _ = self.render(4320)
        self.assertIn('Last FAA check Sat 3:00 PM (3 days ago)', text)

    def test_airport_hero_dated_and_disclaimer(self):
        for age in (5, 180):
            _, a, stamp = self.render(age)
            live = bap._render_live('ZZZ', a['tz'], a, stamp, NOW)
            verdict = bap._verdict(a, a['name'], a['short'], live, NOW, a['tz'])
            self.assertEqual(live['stale'], age == 180)
            self.assertIn('as of' if age == 180 else 'right now', verdict)
        self.assertIn(claims()['reminder'], (ROOT / 'index.html').read_text())
        self.assertIn(claims()['reminder'], (ROOT / 'tools/build_airport_pages.py').read_text())

    def test_every_event_impact(self):
        for kind in claims()['event_kinds']:
            event = dict(kind=kind)
            stale = ph.impact_text(event, 'Example', True)
            fresh = ph.impact_text(event, 'Example', False)
            for phrase in claims()['forbidden_stale']:
                self.assertNotIn(phrase, stale)
            self.assertNotEqual(stale, fresh)

    def test_missing_is_not_clear(self):
        text, _, _ = self.render(180, missing=True)
        self.assertIn('Last FAA check', text)
        self.assertNotIn('clear', pt.fallback_status({}).lower())
        self.assertEqual(pt.fallback_status({}), pt.FALLBACK_STATUS)
        self.assertEqual(ph.national_summary([]), 'Airport readings unavailable')

    @unittest.skipUnless(shutil.which('node'), 'node unavailable')
    def test_node_freshness(self):
        subprocess.run(['node', str(ROOT / 'tests/node/test_freshness.js')], check=True, capture_output=True)
