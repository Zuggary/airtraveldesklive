"""Immediate help order, using synthetic data and no browser."""
import unittest
from pathlib import Path
from datetime import datetime, timezone
from tools import prerender_home as ph

ROOT = Path(__file__).resolve().parents[1]

class ImmediateHelp(unittest.TestCase):
    def test_home_order(self):
        page = (ROOT / "index.html").read_text()
        markers = ['id="summary"', 'id="airports"', 'id="trouble"', 'id="airport-card-slot"', 'id="mine"', 'id="board-section"']
        positions = [page.index(x) for x in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('<!--pr:events--><!--/pr:events-->', page)

    def test_quiet_and_stale_prerender(self):
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        state = {"events": [], "updated_utc": now.isoformat()}
        self.assertIn("No FAA delays or ground stops are listed right now.", ph.render_events(state, {}, now.isoformat(), now))
        old = ph.render_events(state, {}, now.isoformat(), now, stale=True)
        self.assertIn("were listed at the last check", old)
        self.assertNotIn("right now", old)

    def test_faa_reasons(self):
        cases = {
            "TM Initiatives:MIT: WX": "Traffic spacing (miles-in-trail) due to weather",
            "tm initiatives: MINIT : VOLUME": "Traffic spacing (minutes-in-trail) due to traffic volume",
            "MIT": "Traffic spacing (miles-in-trail)",
            "WX:WIND": "Weather, wind",
            "WX": "Weather",
            "VOLUME: VOLUME": "Traffic volume",
            "EQUIPMENT; RUNWAY; STAFFING": "Equipment; Runway; Staffing",
            "TM Initiatives:  UNLISTED:: EXAMPLE": "Unlisted, Example",
            "": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(ph.reason_text(raw), expected)

    def test_affected_rows_keep_plain_meaning_and_order(self):
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        state = {"events": [
            {"airport": "ZZZ", "kind": "ground_delay", "source": "FAA",
             "fields": {"avg": "1 hour and 5 minutes"}, "reason": "TM Initiatives:MIT: WX"},
            {"airport": "zzz", "kind": "delay", "source": "FAA"},
            {"airport": "YYY", "kind": "closure", "source": "FAA", "reason": "RUNWAY"},
        ]}
        airports = {"ZZZ": {"name": "Example & Airport"}}
        rows = ph.render_events(state, airports, now.isoformat(), now)
        self.assertEqual(rows.count("<article "), 2)
        self.assertIn('href="/airports/ZZZ"', rows)
        self.assertIn("Example &amp; Airport", rows)
        self.assertIn(">Delays · avg 1 h 5 min</span>", rows)
        self.assertIn(">Closed</span>", rows)
        self.assertIn(">Traffic spacing (miles-in-trail) due to weather</p>", rows)
        self.assertIn('href="/help/ground-delay.html">What is a ground delay?</a>', rows)
        self.assertNotIn("no size listed", rows)
        self.assertNotIn("event-big", rows)
        stale = ph.render_events(state, airports, now.isoformat(), now, stale=True)
        self.assertIn("Closure listed", stale)
        self.assertIn("Delays listed · avg 1 h 5 min", stale)
        page = ph._slot((ROOT / "index.html").read_text(), "events", rows)
        self.assertLess(page.index("event-reason"), page.index('id="board-section"'))

    def test_static_actions_before_wizard(self):
        page = (ROOT / "stuck.html").read_text()
        start = page.index('<section class="do-first"')
        end = page.index('</section>', start)
        block = page[start:end]
        self.assertLess(end, page.index('id="wizard-progress"'))
        self.assertLess(end, page.index('id="airline-options"'))
        self.assertEqual(block.count('<a '), 4)
        for target in ['/airlines/', '#ask-first', '#keep-receipts', '#step-1-heading']:
            self.assertIn('href="' + target + '"', block)
        self.assertIn('id="keep-receipts"', page)
        self.assertNotIn('?', block)
        self.assertNotIn('<input', block)
