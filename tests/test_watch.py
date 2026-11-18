"""AN52: the Watch live button (watch.js): on every page, no YouTube request until pressed, deploy and offline lists carry it."""
import re, subprocess, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


class WatchTest(unittest.TestCase):
    def test_every_page_with_a_header_loads_watch_js(self):
        pages = [p for p in list(ROOT.glob("*.html")) + list(ROOT.glob("airports/*.html")) + list(ROOT.glob("airlines/*.html")) if "site-header" in p.read_text(encoding="utf-8")]
        self.assertGreaterEqual(len(pages), 4)      # CI has only the committed pages; the generated airport and airline pages come from the builders (next test)
        for p in pages:
            self.assertRegex(p.read_text(encoding="utf-8"), r'<script src="(\.\./)?watch\.js" defer></script>', p.name)

    def test_no_twitch_address_in_any_page_before_the_press(self):
        for p in [ROOT / "index.html", ROOT / "stuck.html"]:
            self.assertNotIn("player.twitch.tv", p.read_text(encoding="utf-8"), p.name)

    def test_builder_adds_the_script_to_generated_pages(self):
        self.assertIn('<script src="../watch.js" defer></script>', (ROOT / "tools/build_airport_pages.py").read_text(encoding="utf-8"))

    def test_js_loads_the_iframe_only_on_press_and_parents_are_set(self):
        js = (ROOT / "watch.js").read_text(encoding="utf-8")
        self.assertIn("UCtEAjmjCJdR-pHgcZtIFI9w", js)
        self.assertNotIn("innerHTML", js)
        self.assertIn('e.key === "Escape"', js)

    def test_lists_and_home_card(self):
        self.assertIn("watch.js", (ROOT / ".github/workflows/status.yml").read_text(encoding="utf-8"))
        self.assertIn('"./watch.js"', (ROOT / "sw.js").read_text(encoding="utf-8"))
        home = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertRegex(home, r'<button[^>]+data-watch-open[^>]*>Watch live on YouTube</button>')
        self.assertNotRegex(home, r'<link[^>]+(?:preconnect|dns-prefetch)[^>]+(?:youtube|ytimg|google)')
        self.assertIn('id="live-card"', home)
        self.assertLess(home.index('id="live-card"'), home.index('id="airport-card-slot"'))
        self.assertTrue((ROOT / "assets/live/stream-thumb.jpg").exists())

    def test_mini_player_never_moves_the_iframe_and_keeps_its_slot(self):
        js = (ROOT / "watch.js").read_text(encoding="utf-8")
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn("IntersectionObserver", js)
        self.assertEqual(len(re.findall(r"appendChild\(f\)|insertBefore\(f,", js)), 1)       # the iframe is made once, never re-parented
        self.assertIn(".watch-frame.docked .watch-box", css)
        self.assertIn("env(safe-area-inset-bottom", css)
        self.assertIn("320px", css)

    def test_soft_navigation_only_while_open_and_falls_back(self):
        js = (ROOT / "watch.js").read_text(encoding="utf-8")
        self.assertIn("pushState", js)
        self.assertIn("popstate", js)
        self.assertIn("if (!isOpen ||", js)                      # closed player: every link stays a normal full load
        self.assertIn("win.location.href = u.href", js)         # any failure falls back to a normal navigation
        for guard in ("e.metaKey", "e.ctrlKey", "e.shiftKey", "a.target", 'hasAttribute("download")', "u.origin !== win.location.origin"):
            self.assertIn(guard, js)
        self.assertIn("SKIP_SCRIPTS", js)
        self.assertIn("text/atd-late", js)      # held-back airport scripts must still run after a swap

    def test_youtube_facade_without_autoplay_or_twitch_sdk(self):
        js = (ROOT / "watch.js").read_text()
        self.assertIn("https://www.youtube.com/embed/live_stream?channel=", js)
        self.assertIn("&autoplay=0", js)
        self.assertNotIn("player.twitch.tv", js)
        self.assertNotIn("autoplay: true", js)
        self.assertIn("Also on Twitch", js)
        for p in [ROOT / "index.html", ROOT / "stuck.html"]:
            self.assertNotRegex(p.read_text(), r'<(?:iframe|script)[^>]+(?:src=[\"\']https://[^\"\']*youtube)')

    def test_node_unit(self):
        r = subprocess.run(["node", str(ROOT / "tests/node/test_watch.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
