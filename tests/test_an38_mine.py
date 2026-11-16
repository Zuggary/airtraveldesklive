"""AN38: Your airports: remove one tile, Clear with Undo, the note line. Real browser, local server, localStorage."""
import functools
import http.server
import socketserver
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from playwright.sync_api import sync_playwright
except Exception:          # the site test environment may lack Playwright: the static checks still run
    sync_playwright = None


class TestStatic(unittest.TestCase):
    def test_markup_and_note(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="mine-clear"', html)
        self.assertIn("Airports you star or open show here. Saved in this browser only.", html)
        self.assertNotIn("No account.</p>\n    </div>\n\n    <section id=\"trouble\"", html)

    def test_js_clears_both_keys_and_labels_the_buttons(self):
        js = (ROOT / "app.js").read_text(encoding="utf-8")
        for need in ('"Remove " + c + " from your airports"', 'removeItem("atd.last")', '"Cleared. "', "6000", "mine-undo-btn"):
            self.assertIn(need, js, need)

    def test_buttons_are_44px_targets(self):
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertIn(".mine-x { flex: none; width: 44px; min-height: 44px;", css)
        self.assertIn("min-height: 44px", css[css.index(".mine-clear, .mine-undo-btn"):][:200])


@unittest.skipIf(sync_playwright is None, "Playwright not installed")
class TestBrowser(unittest.TestCase):
    def test_remove_clear_undo(self):
        class Q(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(ROOT), **k)

            def log_message(self, *a):
                pass
        srv = socketserver.TCPServer(("127.0.0.1", 0), Q)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        try:
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page(viewport={"width": 1000, "height": 900})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
                pg.evaluate("localStorage.setItem('atd.mine', JSON.stringify(['JFK','ATL'])); localStorage.setItem('atd.last','DEN')")
                pg.reload(wait_until="load")
                pg.wait_for_selector("#mine-list .mine-item")
                self.assertEqual(pg.locator("#mine-list .mine-item").count(), 3)
                self.assertEqual(pg.get_attribute("#mine-list .mine-x >> nth=0", "aria-label").startswith("Remove "), True)
                pg.click("button[aria-label='Remove DEN from your airports']")           # the last-opened one
                self.assertIsNone(pg.evaluate("localStorage.getItem('atd.last')"))
                self.assertEqual(pg.locator("#mine-list .mine-item").count(), 2)
                pg.click("#mine-clear")
                self.assertEqual(pg.evaluate("localStorage.getItem('atd.mine')"), "[]")
                self.assertEqual(pg.locator("#mine-list .mine-item").count(), 0)
                self.assertIn("Cleared.", pg.inner_text("#mine-undo"))
                pg.click(".mine-undo-btn")
                self.assertEqual(pg.locator("#mine-list .mine-item").count(), 2)
                self.assertEqual(pg.evaluate("localStorage.getItem('atd.mine')"), '["JFK","ATL"]')
                pg.click("#mine-clear")
                pg.wait_for_timeout(6400)
                self.assertTrue(pg.evaluate("document.getElementById('mine-undo').hidden"))
                self.assertTrue(pg.evaluate("document.getElementById('mine').hidden"))
                self.assertEqual(errs, [])
                b.close()
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
