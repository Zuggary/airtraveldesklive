"""Tests for the shared design tokens (tokens.css) and their use."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["index.html", "about.html", "stuck.html", "privacy.html", "sources.html"]


def _vars(css: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", css)}


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TokensTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tokens = (ROOT / "tokens.css").read_text(encoding="utf-8")
        self.v = _vars(self.tokens)

    def test_required_tokens_exist(self) -> None:
        for name in ("navy", "surface", "surface-alt", "border", "text", "text-muted", "link",
                     "red", "red-text", "red-soft", "green", "green-text", "green-soft",
                     "amber", "amber-soft", "accent", "accent-soft", "on-accent",
                     "fs-xs", "fs-sm", "fs-md", "fs-lg", "fs-xl", "lh",
                     "space-1", "space-2", "space-3", "space-4", "radius", "gutter", "focus-ring"):
            self.assertIn("--" + name, self.v, name)

    def test_tokens_file_is_variables_only(self) -> None:
        body = re.sub(r"/\*.*?\*/", "", self.tokens, flags=re.S)
        self.assertEqual([x.strip() for x in re.findall(r"([^{}]+)\{", body)],
                         [":root", "@media (min-width: 700px)", ":root"])

    def test_accent_contrast_at_least_4_5(self) -> None:
        accent = self.v["--accent"]
        for bg in ("--navy", "--surface", "--surface-alt"):
            self.assertGreaterEqual(ratio(accent, self.v[bg]), 4.5, f"accent on {bg}")
        self.assertGreaterEqual(ratio(self.v["--on-accent"], accent), 4.5, "on-accent on accent")
        self.assertGreaterEqual(ratio(self.v["--on-accent"], self.v["--accent-hover"]), 4.5, "on-accent on hover")

    def test_style_css_has_no_root_block(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        self.assertNotIn(":root", css)

    def test_pages_link_tokens_before_style(self) -> None:
        for name in PAGES:
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn('href="tokens.css"', text, name)
            self.assertLess(text.index('href="tokens.css"'), text.index('href="style.css"'), name)

    def test_airport_generator_links_tokens_first(self) -> None:
        src = (ROOT / "tools" / "build_airport_pages.py").read_text(encoding="utf-8")
        self.assertLess(src.index("../tokens.css"), src.index("../style.css"))

    def test_published_and_cached(self) -> None:
        self.assertIn("./tokens.css", (ROOT / "sw.js").read_text(encoding="utf-8"))
        self.assertIn(" tokens.css ", (ROOT / ".github/workflows/status.yml").read_text(encoding="utf-8"))

    def test_every_css_var_used_is_defined(self) -> None:
        css = (ROOT / "style.css").read_text(encoding="utf-8")
        used = set(re.findall(r"var\((--[\w-]+)", css))
        local = set(re.findall(r"(--[\w-]+)\s*:", css))
        self.assertEqual(sorted(used - set(self.v) - local), [])


if __name__ == "__main__":
    unittest.main()
