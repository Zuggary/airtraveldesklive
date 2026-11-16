"""AN38: the theme switch (System, Light, Dark): inline head snippet, button, theme.js, CSS tokens, service worker and the deploy copy list."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["index.html", "about.html", "privacy.html", "sources.html", "stuck.html"]
SNIP = 'try{var t=localStorage.getItem("atd-theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}'


class TestThemeSwitch(unittest.TestCase):
    def test_every_page_has_snippet_before_the_stylesheet_and_one_button(self):
        for name in PAGES:
            html = (ROOT / name).read_text(encoding="utf-8")
            self.assertEqual(html.count(SNIP), 1, name)
            self.assertLess(html.index(SNIP), html.index('rel="stylesheet"'), name)                  # no flash: runs before paint
            self.assertIn('<script src="theme.js" defer></script>', html, name)
            self.assertEqual(html.count("data-theme-toggle"), 1, name)
            self.assertRegex(html, r'<button class="theme-toggle" type="button" data-theme-toggle[^>]*aria-label="Theme: System')

    def test_generated_pages_share_the_markup(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from tools import build_airport_pages as bap
        head = bap._render_head(title="T", description="D", canonical="https://x/", breadcrumb={})
        self.assertIn(SNIP, head)
        self.assertIn('<script src="../theme.js" defer></script>', head)
        self.assertLess(head.index(SNIP), head.index('rel="stylesheet"'))
        self.assertIn("data-theme-toggle", bap._render_header())

    def test_script_is_guarded_and_cycles_three_states(self):
        js = (ROOT / "theme.js").read_text(encoding="utf-8")
        self.assertIn('ORDER = ["system", "light", "dark"]', js)
        self.assertGreaterEqual(js.count("localStorage"), 3)
        for fn in ("function read", "function write"):
            seg = js[js.index(fn):js.index(fn) + 260]
            self.assertIn("try {", seg)
        self.assertNotIn("fetch(", js)

    def test_css_has_forced_light_and_dark_tokens(self):
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        auto = re.search(r'@media \(prefers-color-scheme: light\) \{\n  html:not\(\[data-theme="dark"\]\) \{\n(.*?)\n  \}\n\}', css, re.S).group(1)
        forced = re.search(r'html\[data-theme="light"\] \{\n(.*?)\n\}', css, re.S).group(1)
        self.assertEqual(auto.strip(), forced.strip())                       # same light tokens, forced
        self.assertIn(".theme-toggle { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px", css)

    def test_deploy_and_offline_lists_carry_theme_js(self):
        self.assertIn("theme.js", (ROOT / ".github/workflows/status.yml").read_text(encoding="utf-8"))
        self.assertIn('"./theme.js"', (ROOT / "sw.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
