import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SweepFixes(unittest.TestCase):
    def test_player_controls_are_assigned_after_drawer_insertion(self):
        home = (ROOT / "index.html").read_text()
        for tag in re.findall(r"<button\b[^>]*\bdata-watch-open\b[^>]*>", home):
            self.assertNotIn("aria-controls", tag)
        watch = (ROOT / "watch.js").read_text()
        insert = watch.index("header.parentNode.insertBefore(drawer")
        self.assertLess(insert, watch.index('btn.setAttribute("aria-controls"'))
        self.assertLess(insert, watch.index('teasers[i].setAttribute("aria-controls"'))
        self.assertIn("syncTeasers();", watch.split("function swapIn(", 1)[1].split("function go(", 1)[0])

    def test_search_announcements_use_a_visually_hidden_status(self):
        home = (ROOT / "index.html").read_text()
        self.assertIn('<p id="search-status" class="sr-only" role="status"></p>', home)
        app = (ROOT / "app.js").read_text()
        self.assertIn('status.textContent = empty.textContent;', app)
        self.assertIn('status.textContent = res.length +', app)
        self.assertIn('if (e.key === "/"', app)

    def test_stuck_canonical_matches_the_public_path(self):
        stuck = (ROOT / "stuck.html").read_text()
        self.assertEqual(
            re.findall(r'<link rel="canonical" href="([^"]+)">', stuck),
            ["https://www.airtraveldesklive.com/stuck"],
        )

    def test_drawer_link_has_dark_background_color_in_both_themes(self):
        css = (ROOT / "style.css").read_text()
        tokens = (ROOT / "tokens.css").read_text()
        self.assertRegex(css, r"\.watch-drawer-bar a\s*\{[^}]*color: var\(--link-on-dark, #8fcbff\)")
        self.assertIn("--link-on-dark: #8fcbff;", tokens)
