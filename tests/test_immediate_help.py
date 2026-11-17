"""Immediate help order, using synthetic data and no browser."""
import unittest
from pathlib import Path
from datetime import datetime, timezone
from tools import prerender_home as ph

ROOT = Path(__file__).resolve().parents[1]

class ImmediateHelp(unittest.TestCase):
    def test_home_order(self):
        page = (ROOT / "index.html").read_text()
        markers = ['id="summary"', 'id="airports"', 'id="trouble"', 'id="live-card"', 'id="airport-card-slot"', 'id="mine"', 'id="board-section"']
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

    def test_affected_rows_keep_plain_meaning_and_order(self):
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        state = {"events": [{"airport": "ZZZ", "kind": "ground_stop", "source": "FAA"}]}
        rows = ph.render_events(state, {"ZZZ": {"name": "Example Airport"}}, now.isoformat(), now)
        self.assertIn("ZZZ", rows)
        self.assertIn("event-impact", rows)
        self.assertIn("Source: FAA", rows)
        page = ph._slot((ROOT / "index.html").read_text(), "events", rows)
        self.assertLess(page.index("event-impact"), page.index('id="live-card"'))
        self.assertLess(page.index("event-impact"), page.index('id="board-section"'))

    def test_static_actions_before_wizard(self):
        page = (ROOT / "stuck.html").read_text()
        start = page.index('<section class="do-first"')
        end = page.index('</section>', start)
        block = page[start:end]
        self.assertLess(end, page.index('id="wizard-progress"'))
        self.assertLess(end, page.index('id="airline-options"'))
        self.assertEqual(block.count('<a '), 3)
        for target in ['/airlines/', '#ask-first', '#keep-receipts']:
            self.assertIn('href="' + target + '"', block)
        self.assertIn('id="keep-receipts"', page)
        self.assertNotIn('?', block)
        self.assertNotIn('<input', block)
