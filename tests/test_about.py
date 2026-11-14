"""Tests for AN16 Part A: about.html, ads.txt, footers, sitemap.xml, metadata, and workflow."""
from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OWN_HOSTS = {"", "www.airtraveldesklive.com"}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_lang: str | None = None
        self.title_parts: list[str] = []
        self._in_title = False
        self.h1_count = 0
        self.h2_count = 0
        self.table_count = 0
        self.caption_count = 0
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.footer_anchors: list[dict[str, str]] = []
        self._in_footer = False
        self._current_a: dict[str, str] | None = None
        self._a_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t == "html":
            self.html_lang = attr_map.get("lang")
        elif t == "title":
            self._in_title = True
        elif t == "h1":
            self.h1_count += 1
        elif t == "h2":
            self.h2_count += 1
        elif t == "table":
            self.table_count += 1
        elif t == "caption":
            self.caption_count += 1
        elif t == "meta":
            self.metas.append(attr_map)
        elif t == "link":
            self.links.append(attr_map)
        elif t == "script":
            self.scripts.append(attr_map)
        elif t == "footer":
            self._in_footer = True
        elif t == "a":
            self._current_a = dict(attr_map)
            self._a_text = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        elif t == "footer":
            self._in_footer = False
        elif t == "a" and self._current_a is not None:
            self._current_a["text"] = "".join(self._a_text).strip()
            self.anchors.append(self._current_a)
            if self._in_footer:
                self.footer_anchors.append(self._current_a)
            self._current_a = None
            self._a_text = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._current_a is not None:
            self._a_text.append(data)


def parse_html(rel: str) -> tuple[str, _PageParser]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    parser = _PageParser()
    parser.feed(text)
    parser.close()
    return text, parser


class TestAboutPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text, cls.p = parse_html("about.html")

    def test_single_h1_title_and_structure(self) -> None:
        self.assertEqual(self.p.html_lang, "en")
        self.assertEqual("".join(self.p.title_parts).strip(), "About Air Travel Desk")
        self.assertEqual(self.p.h1_count, 1)
        self.assertGreaterEqual(self.p.h2_count, 6)
        self.assertEqual(self.p.table_count, 1)
        self.assertEqual(self.p.caption_count, 1)

    def test_canonical_description_and_og_tags(self) -> None:
        canon = [l.get("href") for l in self.p.links if l.get("rel") == "canonical"]
        self.assertEqual(canon, ["https://www.airtraveldesklive.com/about.html"])
        meta_names = {m.get("name"): m.get("content") for m in self.p.metas if "name" in m}
        meta_props = {m.get("property"): m.get("content") for m in self.p.metas if "property" in m}
        self.assertTrue(meta_names.get("description"))
        for prop in ("og:title", "og:description", "og:image", "og:url", "og:type"):
            self.assertTrue(meta_props.get(prop), f"Missing {prop}")

    def test_required_email_and_forbidden_strings(self) -> None:
        self.assertIn("hello@airtraveldesklive.com", self.text)
        emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", self.text))
        self.assertEqual(emails, {"hello@airtraveldesklive.com"})
        self.assertEqual(
            self.text.count("@"),
            self.text.count("hello@airtraveldesklive.com"),
            "No '@' other than hello@airtraveldesklive.com should appear in about.html",
        )
        lower = self.text.lower()
        for forbidden in ("zach", "lucas", "gmail"):
            self.assertNotIn(forbidden, lower)

    def test_no_script_src_or_link_href_to_another_host(self) -> None:
        for s in self.p.scripts:
            src = s.get("src", "")
            if src:
                self.assertIn((urlparse(src).hostname or "").lower(), OWN_HOSTS, src)
        for l in self.p.links:
            href = l.get("href", "")
            if href:
                self.assertIn((urlparse(href).hostname or "").lower(), OWN_HOSTS, href)

    def test_required_sections_and_corrections(self) -> None:
        for expected in (
            "What this is",
            "How pages are made",
            "Where the data comes from",
            "Limits of the data",
            "Report an error or ask a question",
            "Corrections",
            "2026-11-14: site launched",
            "Privacy",
            "privacy.html",
            "Skip to main content",
        ):
            self.assertIn(expected, self.text)


class TestAdsTxtAndSiteIntegration(unittest.TestCase):
    def test_ads_txt_matches_reference_exactly(self) -> None:
        actual = (ROOT / "ads.txt").read_text(encoding="utf-8")
        # The publisher line, in the same format as the sister site's ads.txt. It carries no ad code.
        ref = "google.com, pub-4144533231524022, DIRECT, f08c47fec0942fa0\n"
        self.assertEqual(actual, ref)

    def test_every_page_footer_has_about_link(self) -> None:
        for page in ("index.html", "stuck.html", "privacy.html", "about.html", "tv.html"):
            _, parser = parse_html(page)
            about_links = [a for a in parser.footer_anchors if a.get("href") == "about.html"]
            self.assertTrue(about_links, f"{page} footer missing about.html link")
            self.assertTrue(any(a.get("text") == "About" for a in about_links), page)

        for page in ("index.html", "stuck.html", "privacy.html", "about.html"):
            text, parser = parse_html(page)
            hrefs = {a.get("href") for a in parser.footer_anchors}
            self.assertIn("privacy.html", hrefs, page)
            self.assertIn("mailto:hello@airtraveldesklive.com", hrefs, page)
            self.assertIn("Contact:", text, page)

        tv_text, tv_parser = parse_html("tv.html")
        robots_meta = [m.get("content", "") for m in tv_parser.metas if m.get("name") == "robots"]
        self.assertTrue(any("noindex" in c for c in robots_meta), tv_text[:200])

    def test_sitemap_and_workflow_include_new_files(self) -> None:
        sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn("https://www.airtraveldesklive.com/about.html", sitemap)

        yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        m = re.search(r"for file in ([^;]+); do", yml)
        self.assertIsNotNone(m)
        copied = set(m.group(1).split())
        self.assertIn("about.html", copied)
        self.assertIn("ads.txt", copied)

    def test_stuck_and_airport_guide_show_purpose_sources_and_date(self) -> None:
        stuck_html = (ROOT / "stuck.html").read_text(encoding="utf-8")
        self.assertIn("Purpose: help you decide what to do when your flight is delayed or cancelled.", stuck_html)
        self.assertIn("Sources: U.S. DOT airline dashboard (updated", stuck_html)
        self.assertIn("14 CFR 260.6. Last checked 2026-11-14.", stuck_html)

        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("This guide is independent and not affiliated with the airport or the FAA.", app_js)
        self.assertIn("Sources:", app_js)
        self.assertIn("Last checked ", app_js)


if __name__ == "__main__":
    unittest.main()


class TestStaticPagesFix2(unittest.TestCase):
    def test_no_live_dot_on_static_pages_and_inline_twitch_link(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("about.html", "privacy.html", "sources.html", "stuck.html"):
            self.assertNotIn("live-dot", (root / name).read_text(encoding="utf-8"), name)
        self.assertIn("live-dot", (root / "index.html").read_text(encoding="utf-8"))
        css = (root / "style.css").read_text(encoding="utf-8")
        self.assertIn(".prose-card p .tap", css)
        self.assertIn("display: inline;", css.split(".prose-card p .tap", 1)[1].split("}", 1)[0])
