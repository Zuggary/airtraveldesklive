"""AN25: the 'Ask before you pay' section of stuck.html, its short version in the wizard result,
the links from the airline pages, and the data file of DOT sources.

No network. Pages are built in a temp dir. The DOT pages were read by hand on 2026-11-14; the exact sentences are in
data/ask-first-sources.json and every citation link on the page must be listed there.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
NODE = shutil.which("node")

from tools import build_airline_pages as bal  # noqa: E402

READ = "2026-11-14"
DOWNTIME_URL = "https://www.downtimecredit.com/flights/?utm_source=airtraveldesklive"
BANNED = ("must cover", "entitled", "guaranteed", "you are owed", "you will receive")
URL_RE = re.compile(r"https?://[^\s'\"<>`]+", re.IGNORECASE)


def is_official(host: str) -> bool:
    """U.S. DOT's own site is transportation.gov; the complaint form is on dot.gov; the rule text is on ecfr.gov."""
    # AN43: govinfo.gov is the Government Publishing Office, which publishes the official Federal Register (the rule text).
    return any(host == h or host.endswith("." + h) for h in ("transportation.gov", "dot.gov", "ecfr.gov", "govinfo.gov"))


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def visible_text(html_text: str) -> str:
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html_text, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def section_html(html_text: str) -> str:
    start = html_text.index('<section id="ask-first"')
    end = html_text.index("</section>", start)
    return html_text[start:end]


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href") or "")


class TestSourcesFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(read_text("data/ask-first-sources.json"))
        cls.by_url = {s["url"]: s for s in cls.doc["sources"]}

    def test_every_entry_has_url_read_date_and_quotes(self):
        self.assertEqual(self.doc["read"], READ)
        for s in self.doc["sources"]:
            host = urlparse(s["url"]).hostname or ""
            self.assertTrue(is_official(host), s["url"])
            self.assertGreaterEqual(s["read"], READ, s["id"])     # AN43: later entries may carry a later read date
            if s.get("cited"):
                self.assertTrue(s["quotes"], s["id"])
                for q in s["quotes"]:
                    self.assertGreater(len(q), 40, s["id"])

    def test_urls_are_unique(self):
        self.assertEqual(len(self.by_url), len(self.doc["sources"]))

    def test_archived_page_is_never_a_citation(self):
        arch = [s for s in self.doc["sources"] if s.get("archived")]
        self.assertTrue(arch)
        for s in arch:
            self.assertFalse(s["cited"])
            self.assertNotIn(s["url"], read_text("stuck.html"))
            self.assertNotIn(s["url"], read_text("stuck.js"))


class TestStaticSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_text("stuck.html")
        cls.js = read_text("stuck.js")
        cls.sources = json.loads(read_text("data/ask-first-sources.json"))
        cls.known = {s["url"]: s for s in cls.sources["sources"]}
        cls.sec = section_html(cls.html)

    def test_section_exists_in_static_html_outside_noscript_and_script(self):
        self.assertIn('id="ask-first"', self.html)
        self.assertIn('<h2 id="ask-first-heading" class="result-heading">Ask before you pay</h2>', self.html)
        # the section is plain markup: not inside <noscript>, and not built by stuck.js
        self.assertGreater(self.html.index('id="ask-first"'), self.html.index("</noscript>"))
        self.assertNotIn("ask-first-heading", self.js)
        self.assertGreaterEqual(self.sec.count("<details"), 6)
        for title in ("Why ask first", "What to say", "What to ask for in writing", "Airline cause or weather?",
                      "The DOT rules that apply", "Copy-paste message", "Keep receipts"):
            self.assertIn(f"<summary>{title}", self.sec)

    def test_top_of_page_links_to_the_section(self):
        main = self.html[self.html.index('<main id="main-content"'):]
        first_link = main.index('href="#ask-first"')
        self.assertLess(first_link, main.index('id="step-1"'))

    def test_three_short_lines_for_counter_phone_chat(self):
        for label in ("At the counter:", "On the phone:", "In chat:"):
            self.assertIn(f"<strong>{label}</strong>", self.sec)

    def test_ask_for_in_writing_has_four_items(self):
        block = self.sec[self.sec.index("What to ask for in writing"):self.sec.index("Airline cause or weather?")]
        self.assertEqual(block.count("<li>"), 4)
        for word in ("reason", "voucher", "name or ID", "time"):
            self.assertIn(word, block)

    def test_every_rule_has_a_citation_link_and_read_date(self):
        rules = re.findall(r'<p class="rule">(.*?)</p>', self.sec, flags=re.S)
        self.assertGreaterEqual(len(rules), 12)
        for r in rules:
            p = _Anchors()
            p.feed(r)
            self.assertTrue(p.hrefs, r[:80])
            for href in p.hrefs:
                host = urlparse(href).hostname or ""
                self.assertTrue(is_official(host), href)
                self.assertIn(href, self.known, href)
                self.assertTrue(self.known[href]["cited"], href)
            self.assertIn(f"read {READ}", visible_text(r), r[:80])
            self.assertIn('class="cite"', r)

    def test_every_dot_or_ecfr_url_on_the_page_is_in_the_sources_file(self):
        for url in URL_RE.findall(self.html):
            host = urlparse(url).hostname or ""
            if is_official(host):
                self.assertIn(url, self.known, url)

    def test_only_allowed_urls_on_the_page_and_in_the_script(self):
        allowed = set(self.known) | {DOWNTIME_URL, "https://www.usa.gov/government-works"}
        for name, text in (("stuck.html", self.html), ("stuck.js", self.js)):
            for url in URL_RE.findall(text):
                self.assertIn(url, allowed, f"{name}: {url}")

    def test_rules_cover_the_required_topics(self):
        text = visible_text(self.sec)
        for needle in ("14 CFR 260.6", "customer service plan", "3 hours", "complaint", "snack and water",
                       "five years", "does not investigate every complaint", "maintenance or crew problems",
                       "weather, air traffic control and security"):
            self.assertIn(needle.lower(), text.lower(), needle)
        for url in ("airline-cancellation-delay-dashboard", "/refunds", "section-260.6", "/tarmac-delays",
                    "/file-consumer-complaint", "airconsumer.dot.gov/consumer/s/oacp-form"):
            self.assertIn(url, self.sec, url)

    def test_honest_wording_and_banned_words(self):
        low = visible_text(self.sec).lower()
        for bad in BANNED:
            self.assertNotIn(bad, low, bad)
            self.assertNotIn(bad, self.js.lower(), bad)
        self.assertIn("not legal advice", low)
        self.assertIn("possibly owed", low)
        self.assertIn("the airline's own plan decides", low)
        self.assertIn("has committed to", low)
        # no promise that meals or hotels are owed
        self.assertNotIn("free hotel", low)
        self.assertNotIn("always", low)

    def test_copy_button_markup_and_script(self):
        self.assertIn('<textarea id="ask-message"', self.sec)
        self.assertIn('id="ask-copy-btn" hidden>', self.sec)  # shown by script only; the text still works by hand
        self.assertIn('id="ask-copy-status"', self.sec)
        self.assertIn("select all", self.sec)  # visible by-hand fallback
        for slot in ("[AIRLINE]", "[FLIGHT]", "[AIRPORT]", "[TIME]", "[NEED: meal / hotel / rebooking]"):
            self.assertIn(slot, self.sec)
        for needle in ("initAskFirst", "ask-copy-btn", "navigator.clipboard", "execCommand", "box.select()"):
            self.assertIn(needle, self.js)
        scripts = re.findall(r'<script[^>]*\bsrc="([^"]+)"', self.html)
        self.assertEqual(scripts, ["theme.js", "stuck.js", "/count.js"])  # no library, no network

    def test_slots_message_is_short(self):
        m = re.search(r'<textarea id="ask-message"[^>]*>(.*?)</textarea>', self.sec, flags=re.S)
        self.assertLess(len(m.group(1).split()), 90)

    def test_airline_pages_link_list_and_section_keep_working(self):
        for a in ("alaska", "delta", "spirit"):
            self.assertIn(f'href="airlines/{a}.html"', self.html)
        self.assertGreater(self.html.index('id="ask-first"'), self.html.index('id="step-4"'))


class TestAirlinePagesLink(unittest.TestCase):
    def test_every_airline_page_and_the_index_link_to_the_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            out = base / "airlines"
            sm = base / "sitemap.xml"
            shutil.copy(ROOT / "sitemap.xml", sm)
            written = bal.build_pages(data_dir=ROOT / "data", out_dir=out, sitemap_path=sm, build_date=READ)
            self.assertGreaterEqual(len(written), 11)
            for p in sorted(out.glob("*.html")):
                text = p.read_text(encoding="utf-8")
                self.assertIn('href="../stuck.html#ask-first"', text, p.name)
                for bad in BANNED:
                    self.assertNotIn(bad, visible_text(text).lower(), p.name)


@unittest.skipUnless(NODE, "node not installed")
class TestWizardShortVersion(unittest.TestCase):
    def run_js(self, expr: str):
        code = "const S=require(%s);process.stdout.write(JSON.stringify(%s));" % (json.dumps(str(ROOT / "stuck.js")), expr)
        res = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        if res.returncode:
            raise RuntimeError(res.stderr)
        return json.loads(res.stdout)

    def test_short_card_for_the_four_situations_and_not_for_diverted(self):
        for sit in ("delayed", "cancelled", "missed_connection", "overnight"):
            for cause in ("airline", "weather", "unsure"):
                m = self.run_js(f"S.buildAskFirstModel('{sit}','{cause}')")
                self.assertEqual(m["heading"], "Ask before you pay")
                self.assertEqual(m["pageUrl"], "stuck.html#ask-first")
                self.assertEqual(m["read"], READ)
                self.assertTrue(m["sourceUrl"].startswith("https://www.transportation.gov/"))
                self.assertEqual(len(m["items"]), 4)
                blob = json.dumps(m).lower()
                for bad in BANNED:
                    self.assertNotIn(bad, blob)
        self.assertIsNone(self.run_js("S.buildAskFirstModel('diverted','airline')"))
        self.assertIsNone(self.run_js("S.buildAskFirstModel('','airline')"))

    def test_source_url_is_in_the_sources_file(self):
        known = {s["url"] for s in json.loads(read_text("data/ask-first-sources.json"))["sources"]}
        m = self.run_js("S.buildAskFirstModel('cancelled','weather')")
        self.assertIn(m["sourceUrl"], known)

    def test_weather_line_says_airline_decides(self):
        m = self.run_js("S.buildAskFirstModel('delayed','weather')")
        self.assertIn("usually up to the airline", " ".join(m["items"]))

    def test_render_hook_in_result(self):
        js = read_text("stuck.js")
        self.assertIn("buildAskFirstModel(state.situationId, effectiveCause)", js)
        self.assertIn("if (ask)", js)

    def test_copy_button_logic_with_stubbed_dom(self):
        script = r"""
const path = %s;
function run(hasClipboard, execResult) {
  const status = {textContent: ""};
  const box = {value: "hello", focus() { this.focused = true; }, select() { this.selected = true; }};
  const btn = {hidden: true, handler: null, addEventListener(t, f) { this.handler = f; }};
  const els = {"ask-copy-btn": btn, "ask-message": box, "ask-copy-status": status};
  globalThis.document = {getElementById: (id) => els[id] || null, execCommand: () => execResult};
  document.execCommand = () => { if (execResult === "throw") { throw new Error("x"); } return execResult; };
  let written = null;
  Object.defineProperty(globalThis, "navigator", {configurable: true, value: hasClipboard === "ok"
    ? {clipboard: {writeText: (t) => { written = t; return Promise.resolve(); }}}
    : hasClipboard === "reject" ? {clipboard: {writeText: () => Promise.reject(new Error("no"))}} : {}});
  delete require.cache[path];
  const S = require(path);
  S.initAskFirst();
  btn.handler();
  return new Promise((r) => setTimeout(() => r({hidden: btn.hidden, status: status.textContent, written, selected: !!box.selected}), 20));
}
(async () => {
  const out = {};
  out.ok = await run("ok", true);
  out.none = await run("none", true);
  out.noneFail = await run("none", false);
  out.reject = await run("reject", true);
  out.throws = await run("none", "throw");
  process.stdout.write(JSON.stringify(out));
})();
""" % json.dumps(str(ROOT / "stuck.js"))
        res = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        out = json.loads(res.stdout)
        self.assertFalse(out["ok"]["hidden"])
        self.assertEqual(out["ok"]["written"], "hello")
        self.assertEqual(out["ok"]["status"], "Copied.")
        self.assertEqual(out["none"]["status"], "Copied.")
        self.assertTrue(out["none"]["selected"])
        self.assertIn("Text selected", out["noneFail"]["status"])
        self.assertTrue(out["reject"]["selected"])
        self.assertIn("Text selected", out["throws"]["status"])


if __name__ == "__main__":
    unittest.main()
