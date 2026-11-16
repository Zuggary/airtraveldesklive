"""AN43: no timed refresh on site pages (AdSense ad placement policy, support.google.com/adsense/answer/1346295:
no refresh of a page or a page element without the user asking). The stream page tv.html is exempt (no ads)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_JS = ["app.js", "lib.js", "stuck.js", "apmap.js", "sun.js", "theme.js", "sources.js", "count.js", "airport.js"]


class NoTimedRefresh(unittest.TestCase):
    def test_no_set_interval_in_site_scripts(self):
        for name in SITE_JS:
            p = ROOT / name
            if p.exists():
                self.assertNotIn("setInterval", p.read_text(), name)

    def test_airport_pages_have_no_timer(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from tools import build_airport_pages as b
        self.assertNotIn("setInterval", b.airport_js())
        src = (ROOT / "tools" / "build_airport_pages.py").read_text()
        self.assertNotIn("setInterval", src)
        self.assertNotIn("http-equiv", src.lower())

    def test_no_meta_refresh_in_pages(self):
        pages = [ROOT / "index.html", ROOT / "stuck.html", ROOT / "about.html", ROOT / "privacy.html", ROOT / "sources.html"]
        pages += sorted((ROOT / "airports").glob("*.html"))[:5]
        for p in pages:
            if p.exists():
                self.assertIsNone(re.search(r'http-equiv=["\']?refresh', p.read_text(), re.I), p.name)

    def test_home_has_refresh_button_and_fixed_stamp(self):
        html = (ROOT / "index.html").read_text()
        self.assertIn('id="refresh-btn"', html)
        js = (ROOT / "app.js").read_text()
        self.assertIn('"FAA data as of "', js)
        self.assertNotIn("visibilitychange", js)


if __name__ == "__main__":
    unittest.main()
