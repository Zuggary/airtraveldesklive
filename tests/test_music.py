"""Tests for AN285: the /music page is built from data/music.json and its previews exist."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "music.html").read_text(encoding="utf-8")
DATA = json.loads((ROOT / "data" / "music.json").read_text(encoding="utf-8"))


class MusicPageTests(unittest.TestCase):
    def test_has_items_and_count_matches(self) -> None:
        self.assertGreater(DATA["count"], 0)
        self.assertEqual(DATA["count"], len(DATA["items"]))

    def test_every_item_is_on_the_page(self) -> None:
        for item in DATA["items"]:
            self.assertIn(item["title"], PAGE, item["id"])
            for part in item["facts"].split(" · "):
                self.assertIn(part.strip().replace("&", "&amp;"), PAGE, item["id"])
            self.assertEqual(len(item["wave"]), 56, item["id"])
            self.assertIn(item["kind"], ("ai", "synthesised"))
        if any(i["kind"] == "synthesised" for i in DATA["items"]):
            self.assertIn("Synthesised in code by Air Travel Desk", PAGE)
            self.assertIn("original work of Air Travel Desk", PAGE)

    def test_summary_comes_from_the_data(self) -> None:
        tracks = sum(i["variations"] for i in DATA["items"])
        self.assertIn("%d track families, %d tracks" % (DATA["count"], tracks), PAGE)

    def test_ai_tracks_are_labelled_and_name_the_tool(self) -> None:
        for item in DATA["items"]:
            if item["kind"] == "ai":
                self.assertIn("ACE-Step", item["method"])
                self.assertIn("AI-generated", PAGE)

    def test_previews_exist_and_are_small(self) -> None:
        for item in DATA["items"]:
            p = ROOT / item["preview"]
            self.assertTrue(p.exists(), item["preview"])
            self.assertLess(p.stat().st_size, 200_000, item["preview"])
            self.assertIn('data-play="%s"' % item["preview"], PAGE)

    def test_no_orphan_previews(self) -> None:
        names = {Path(i["preview"]).name for i in DATA["items"]}
        on_disk = {p.name for p in (ROOT / "assets" / "music").glob("*.mp3")}
        self.assertEqual(on_disk, names)

    def test_page_basics(self) -> None:
        self.assertEqual(len(re.findall(r"<h1[ >]", PAGE)), 1)
        self.assertIn('rel="canonical" href="https://www.airtraveldesklive.com/music"', PAGE)
        self.assertNotIn("adsbygoogle", PAGE)
        self.assertIn('href="/sources"', PAGE)

    def test_linked_from_shows_and_sitemap(self) -> None:
        self.assertIn('href="/music"', (ROOT / "shows.html").read_text(encoding="utf-8"))
        self.assertIn("https://www.airtraveldesklive.com/music", (ROOT / "sitemap.xml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
