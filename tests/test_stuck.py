"""Tests for the 'I'm stuck' wizard (stuck.html, stuck.js, sw.js, privacy.html, status.yml)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

# The site's reviewed refund line (AN9); no stronger claim without the CoS.
REFUND_SENTENCE = (
    "Refunds are a separate rule, 14 CFR 260.6, and it applies whatever the cause "
    "of the delay or cancellation."
)
DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive"
URL_RE = re.compile(r"https?://[^\s'\"<>`]+", re.IGNORECASE)


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class TestStuckStaticChecks(unittest.TestCase):
    def setUp(self):
        self.stuck_html = read_text("stuck.html")
        self.stuck_js = read_text("stuck.js")
        self.sw_js = read_text("sw.js")
        self.combined = self.stuck_html + "\n" + self.stuck_js

    def test_no_must_cover_anywhere(self):
        for name, text in (("stuck.html", self.stuck_html), ("stuck.js", self.stuck_js)):
            self.assertNotIn("must cover", text.lower(), name)
            self.assertNotIn("you are owed", text.lower(), name)

    def test_required_phrases_present(self):
        self.assertIn("possibly owed", self.combined.lower())
        self.assertIn("not legal advice", self.combined.lower())
        self.assertIn(REFUND_SENTENCE, self.combined)
        self.assertIn("This is our plain reading, not legal advice.", self.combined)

    def test_only_allowed_http_urls_in_stuck_files(self):
        for name, text in (("stuck.html", self.stuck_html), ("stuck.js", self.stuck_js)):
            found = URL_RE.findall(text)
            for url in found:
                self.assertEqual(
                    url,
                    DOWNTIME_URL,
                    f"Unexpected http(s) URL in {name}: {url}",
                )

    def test_no_browser_storage_in_stuck_js(self):
        for forbidden in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
            self.assertNotIn(forbidden, self.stuck_js)

    def test_service_worker_same_origin_only(self):
        self.assertEqual(URL_RE.findall(self.sw_js), [])
        self.assertIn("self.location.origin", self.sw_js)
        for required in (
            "index.html",
            "stuck.html",
            "style.css",
            "app.js",
            "lib.js",
            "stuck.js",
            "data/dot-commitments.json",
            "data/airports.json",
            "favicon.svg",
            "favicon.png",
        ):
            self.assertIn(required, self.sw_js)
        self.assertIn(".json", self.sw_js)

    def test_links_and_registrations(self):
        index_html = read_text("index.html")
        self.assertIn('href="stuck.html"', index_html)
        self.assertIn("I'm stuck at the airport", index_html)
        self.assertIn('serviceWorker.register("sw.js")', index_html)
        self.assertIn('serviceWorker.register("sw.js")', self.stuck_html)

    def test_style_css_has_an14_section(self):
        css = read_text("style.css")
        self.assertIn("/* AN14 stuck */", css)

    def test_privacy_html_updated_and_keeps_twitch(self):
        privacy = read_text("privacy.html")
        self.assertIn(
            "The site caches its own files on your device so it works offline; nothing you type is stored or sent.",
            privacy,
        )
        self.assertNotIn("stores nothing in your browser", privacy)
        self.assertIn("player.twitch.tv", privacy)

    def test_workflow_copies_all_public_root_files(self):
        yml = read_text(".github/workflows/status.yml")
        m = re.search(r"for file in ([^;]+); do", yml)
        self.assertIsNotNone(m)
        copied = set(m.group(1).split())
        for expected in ("stuck.html", "stuck.js", "sw.js"):
            self.assertIn(expected, copied)
        # Mirror the workflow root-file publish guard.
        exts = (".html", ".js", ".css", ".txt", ".xml", ".svg", ".png", ".geojson")
        for p in ROOT.iterdir():
            if p.is_file() and (p.name == "CNAME" or p.suffix in exts):
                self.assertIn(p.name, copied, f"{p.name} missing from status.yml copy list")


@unittest.skipUnless(NODE, "node not installed")
class TestStuckLogicWithNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.commit_data = json.loads(read_text("data/dot-commitments.json"))

    def run_js(self, expr: str, **kwargs):
        code = "const S=require(%s);const DATA=%s;process.stdout.write(JSON.stringify(%s));" % (
            json.dumps(str(ROOT / "stuck.js")),
            json.dumps(kwargs),
            expr,
        )
        res = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        if res.returncode:
            raise RuntimeError(res.stderr)
        return json.loads(res.stdout)

    def test_commitments_model_uses_data_file_rules(self):
        delta = self.run_js("S.buildCommitmentsModel(DATA.c, 'delta', 'airline')", c=self.commit_data)
        self.assertEqual(delta["dotUrl"], self.commit_data["source_url"])
        self.assertEqual(delta["updated"], self.commit_data["source_last_updated"])
        self.assertIn("has committed to", delta["intro"])
        self.assertNotIn("must cover", json.dumps(delta).lower())

        frontier = self.run_js("S.buildCommitmentsModel(DATA.c, 'frontier', 'weather')", c=self.commit_data)
        by_key = {r["key"]: r for r in frontier["rows"]}
        self.assertEqual(by_key["hotel"]["text"], "No commitment")
        self.assertEqual(by_key["meal"]["text"], "Committed")
        self.assertIn("only delays and cancellations the airline causes", frontier["causeNote"].lower())

        spirit = self.run_js("S.buildCommitmentsModel(DATA.c, 'spirit', 'unsure')", c=self.commit_data)
        self.assertIn("not listed on the DOT dashboard", spirit["message"])

        other = self.run_js("S.buildCommitmentsModel(DATA.c, 'other', 'airline')", c=self.commit_data)
        self.assertEqual(other["kind"], "other")

    def test_scripts_and_email_draft(self):
        scripts = self.run_js("S.buildScripts('Delta Air Lines', false, 'cancelled', 'airline')")
        self.assertIn("Delta Air Lines", scripts["counter"])
        self.assertIn("Delta Air Lines", scripts["phone"])
        self.assertNotIn("must cover", json.dumps(scripts).lower())
        self.assertNotIn("you are owed", json.dumps(scripts).lower())

        draft = self.run_js("S.buildEmailDraft('Delta Air Lines', false, 'cancelled', 'airline')")
        self.assertIn("[FLIGHT]", draft)
        self.assertIn("[DATE]", draft)
        self.assertIn("refund of my unused ticket", draft)
        self.assertIn("possibly owed", draft)
        self.assertNotIn("you are owed", draft.lower())


if __name__ == "__main__":
    unittest.main()
