"""Tests for AN14 item 2: airport guide data, app.js integration, sw.js, and privacy.html."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desk.airports import BUSIEST_30  # noqa: E402

URL_RE = re.compile(r"https?://[^\s'\"<>`]+", re.IGNORECASE)
ALLOWED_APP_URLS = {
    "https://player.twitch.tv/?channel=airtraveldesklive&parent=www.airtraveldesklive.com&parent=airtraveldesklive.com&muted=true",
    "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive",
}


class TestAirportGuideData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "data" / "airport-guide.json").read_text(encoding="utf-8"))

    def test_json_has_all_30_airports_and_metadata(self):
        self.assertRegex(self.data.get("checked_utc", ""), r"^\d{4}-\d{2}-\d{2}$")
        airports = self.data.get("airports", {})
        self.assertEqual(sorted(airports), sorted(BUSIEST_30))
        for code, entry in airports.items():
            self.assertIsInstance(entry.get("operator"), str, code)
            self.assertTrue(entry["operator"].strip(), code)
            links = entry.get("links")
            self.assertIsInstance(links, list, code)
            self.assertTrue(links, f"{code} has no links")

    def test_links_are_https_without_whitespace_and_consistent_hosts(self):
        for code, entry in self.data["airports"].items():
            verified_base_domains = set()
            for item in entry["links"]:
                self.assertIsInstance(item.get("label"), str, code)
                self.assertTrue(item["label"].strip(), code)
                self.assertIsInstance(item.get("verified"), bool, code)
                url = item.get("url", "")
                self.assertTrue(url.startswith("https://"), f"{code}: {url!r}")
                self.assertFalse(any(ch.isspace() for ch in url), f"{code}: whitespace in {url!r}")
                host = urlparse(url).hostname or ""
                self.assertTrue(host, f"{code}: missing host in {url!r}")
                if item["verified"]:
                    parts = host.lower().split(".")
                    base = ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()
                    verified_base_domains.add(base)
            # SFO is run under two official domains: fly.sfo.gov redirects to flysfo.com.
            if code == "SFO":
                verified_base_domains -= {"flysfo.com", "sfo.gov"}
            if verified_base_domains:
                self.assertEqual(
                    len(verified_base_domains),
                    1,
                    f"{code} has mixed verified host families: {verified_base_domains}",
                )


class TestAirportGuideIntegration(unittest.TestCase):
    def test_app_js_loads_guide_json_and_has_no_new_hardcoded_urls(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("data/airport-guide.json", app_js)
        found_urls = set(URL_RE.findall(app_js))
        self.assertEqual(
            found_urls - ALLOWED_APP_URLS,
            set(),
            f"Unexpected hard-coded URLs in app.js: {found_urls - ALLOWED_APP_URLS}",
        )
        for required in (
            "Airport guide",
            "Official pages for ",
            "This guide is independent and not affiliated with the airport or the FAA.",
            "Open the full ",
            '"airports/"',
            "guide-pills",
            "guide-pill",
            "(unchecked)",
            "we could not check this link by script",
            "Right now: ",
            "stuck.html",
            "Missed a flight? Open the I'm stuck guide",
            "Links from each airport operator's own website",
        ):
            self.assertIn(required, app_js)

        for removed in (
            "Purpose: official links and conditions for this airport",
            "Hotels and car rental are listed below.",
            "Not on this page",
        ):
            self.assertNotIn(removed, app_js)

    def test_sw_js_and_privacy_html_updated(self):
        sw_js = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertIn("./data/airport-guide.json", sw_js)

        privacy = (ROOT / "privacy.html").read_text(encoding="utf-8")
        self.assertIn(
            "Airport guide links come from the airports' own websites and are saved as a static file on this site; your browser does not contact them unless you open a link.",
            privacy,
        )


if __name__ == "__main__":
    unittest.main()
