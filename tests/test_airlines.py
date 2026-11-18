"""AN23 phase 2: static airline pages (airlines/<id>.html and airlines/index.html).

No network. Pages are built in a temp dir from the committed data files; sitemap.xml in the repo is never written.
Nothing here reads a git-ignored file.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import build_airline_pages as bal  # noqa: E402
from tools import build_airport_pages as bap  # noqa: E402

SITE = "https://www.airtraveldesklive.com"
DASHBOARD = "https://www.transportation.gov/airconsumer/airline-cancellation-delay-dashboard"
DATE = "2026-11-14"
BANNED = ("must cover", "you are entitled", "you're entitled", "guaranteed", "you will receive")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.anchors: list[dict[str, str]] = []
        self.scripts: list[dict[str, str]] = []
        self.imgs: list[dict[str, str]] = []
        self.h1: list[str] = []
        self._in_h1 = False
        self.jsonld: list[str] = []
        self._in_ld = False
        self.text: list[str] = []
        self.chips: list[str] = []
        self._in_chip = False
        self.rows = 0
        self.in_main = False
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "a":
            self.anchors.append(a)
            if "chip" in a.get("class", "").split():
                self._in_chip = True
        elif tag == "script":
            self.scripts.append(a)
            if a.get("type") == "application/ld+json":
                self._in_ld = True
                self.jsonld.append("")
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "h1":
            self._in_h1 = True
            self.h1.append("")
        elif tag == "tr":
            self.rows += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "script":
            self._in_ld = False
        elif tag == "a":
            self._in_chip = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.h1[-1] += data
        if self._in_ld:
            self.jsonld[-1] += data
        elif self._in_chip:
            self.chips.append(data.strip())
        self.text.append(data)


def parse(html_text: str) -> _Page:
    p = _Page()
    p.feed(html_text)
    return p


def visible_text(html_text: str) -> str:
    return re.sub(r"\s+", " ", " ".join(parse(html_text).text))


class _Base(unittest.TestCase):
    out: Path
    tmp: tempfile.TemporaryDirectory
    dot: dict
    extra: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.out = base / "airlines"
        cls.sitemap = base / "sitemap.xml"
        shutil.copy(ROOT / "sitemap.xml", cls.sitemap)
        cls.dot = json.loads((ROOT / "data" / "dot-commitments.json").read_text(encoding="utf-8"))
        cls.extra = json.loads((ROOT / "data" / "airline-pages.json").read_text(encoding="utf-8"))
        cls.written = bal.build_pages(
            data_dir=ROOT / "data", out_dir=cls.out, sitemap_path=cls.sitemap, build_date=DATE
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def page(self, name: str) -> str:
        return (self.out / f"{name}.html").read_text(encoding="utf-8")


class TestBuild(_Base):
    def test_ten_airline_pages_and_index(self) -> None:
        ids = [a["id"] for a in self.dot["airlines"]]
        self.assertEqual(len(ids), 10)
        names = sorted(p.name for p in self.out.glob("*.html"))
        self.assertEqual(names, sorted([f"{i}.html" for i in ids] + ["index.html"]))
        self.assertEqual(len(self.written), 11)

    def test_build_wrote_the_temp_sitemap_only(self) -> None:
        self.assertIn("airlines:begin", self.sitemap.read_text(encoding="utf-8"))

    def test_source_data_is_committed_not_ignored(self) -> None:
        for rel in ("data/dot-commitments.json", "data/airline-pages.json"):
            self.assertTrue((ROOT / rel).is_file(), rel)
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        self.assertNotIn("data/airline-pages.json", ignore)
        self.assertNotIn("data/dot-commitments.json", ignore)


class TestEachPage(_Base):
    def test_every_page_head_and_source(self) -> None:
        updated = self.dot["source_last_updated"]
        read = self.extra["dot_reread"]["date"]
        self.assertEqual(updated, "2025-09-11")
        titles: set[str] = set()
        descriptions: set[str] = set()
        for a in self.dot["airlines"]:
            html_text = self.page(a["id"])
            p = parse(html_text)
            name = a["name"]
            self.assertEqual(p.title.strip(), f"{name}: what you may be owed for a delay or cancellation")
            self.assertEqual([h.strip() for h in p.h1], [f"{name} delay and cancellation commitments"])
            desc = [m["content"] for m in p.metas if m.get("name") == "description"]
            self.assertEqual(len(desc), 1)
            self.assertTrue(desc[0].strip())
            titles.add(p.title)
            descriptions.add(desc[0])
            canon = [l["href"] for l in p.links if l.get("rel") == "canonical"]
            self.assertEqual(canon, [f"{SITE}/airlines/{a['id']}"])
            og = {m["property"]: m["content"] for m in p.metas if m.get("property")}
            self.assertEqual(og["og:url"], canon[0])
            self.assertEqual(og["og:title"], p.title)
            self.assertEqual(og["og:image"], f"{SITE}/og.png")
            # source line with both dates, and the dashboard link
            text = visible_text(html_text)
            self.assertIn(
                f"Source: U.S. DOT Airline Cancellation and Delay Dashboard, last updated {updated}, read {read}.", text
            )
            self.assertEqual(read, DATE)
            self.assertIn(DASHBOARD, [x.get("href") for x in p.anchors])
        self.assertEqual(len(titles), 10)
        self.assertEqual(len(descriptions), 10)

    def test_wording_rules(self) -> None:
        for a in self.dot["airlines"]:
            html_text = self.page(a["id"])
            low = visible_text(html_text).lower()
            self.assertIn("has committed to", low, a["id"])
            self.assertIn("possibly owed", low, a["id"])
            self.assertIn("not legal advice", low, a["id"])
            for bad in BANNED:
                self.assertNotIn(bad, low, f"{a['id']}: {bad}")
            self.assertNotIn("(unchecked)", low)
            self.assertNotIn("traveller", low)

    def test_only_airline_caused_and_refund_note(self) -> None:
        for a in self.dot["airlines"]:
            text = visible_text(self.page(a["id"]))
            self.assertIn("only delays and cancellations the airline causes", text)
            self.assertIn("maintenance or crew problems", text)
            self.assertIn("weather or air traffic control", text)
            self.assertIn(bal.REFUND_SENTENCE, text)
            self.assertIn("14 CFR 260.6", text)
            self.assertIn("Refunds for cancelled flights are a different rule", text)

    def test_refund_sentence_matches_the_guide(self) -> None:
        js = (ROOT / "stuck.js").read_text(encoding="utf-8")
        self.assertIn(f'var REFUND_QUOTE = "{bal.REFUND_SENTENCE}";', js)
        self.assertIn(f'var PLAIN_READING = "{bal.PLAIN_READING}";', js)

    def test_json_ld_breadcrumb_parses(self) -> None:
        for a in self.dot["airlines"]:
            p = parse(self.page(a["id"]))
            self.assertEqual(len(p.jsonld), 1)
            ld = json.loads(p.jsonld[0])
            self.assertEqual(ld["@type"], "BreadcrumbList")
            items = ld["itemListElement"]
            self.assertEqual([i["position"] for i in items], [1, 2, 3])
            self.assertEqual(items[1]["item"], f"{SITE}/airlines/")
            self.assertEqual(items[2]["item"], f"{SITE}/airlines/{a['id']}")
            self.assertEqual(items[2]["name"], a["name"])

    def test_no_external_script_image_or_stylesheet_and_no_ads(self) -> None:
        for name in [a["id"] for a in self.dot["airlines"]] + ["index"]:
            html_text = self.page(name)
            p = parse(html_text)
            self.assertEqual([s for s in p.scripts if s.get("type") != "application/ld+json" and s.get("src") not in ("/count.js", "../theme.js", "theme.js", "../watch.js", "watch.js") and s.get("src") is not None], [], name)      # AN38: theme.js (and its inline head snippet) are the only extra scripts
            for s in p.scripts:
                self.assertIn(s.get("src"), (None, "/count.js", "../theme.js", "theme.js", "../watch.js", "watch.js"))
            for img in p.imgs:
                self.assertFalse(re.match(r"https?:", img.get("src", "")), name)
                self.assertEqual(img.get("src"), "../brand/logo.svg")   # only the site's own logo
            for l in p.links:
                if l.get("rel") in ("stylesheet", "icon"):
                    self.assertFalse(re.match(r"https?:", l.get("href", "")), name)
            self.assertNotIn("adsbygoogle", html_text)
            self.assertNotIn("<iframe", html_text)
            self.assertNotIn("assets/illustrations", html_text)   # no old art on these pages

    def test_four_pill_nav_and_footer(self) -> None:
        for name in [a["id"] for a in self.dot["airlines"]] + ["index"]:
            html_text = self.page(name)
            p = parse(html_text)
            self.assertEqual(p.chips, ["Live board", "Airports", "Airlines", "Stuck?", "Help", "About"], name)  # AN34 nav
            hrefs = [a.get("href") for a in p.anchors]
            for want in ("/", "/airports/", "/about", "/privacy",
                         "/sources", "mailto:hello@airtraveldesklive.com", "/airlines/", "/stuck"):
                self.assertIn(want, hrefs, f"{name}: {want}")
            self.assertIn("Contact:", visible_text(html_text))
            self.assertIn("Data and sources", visible_text(html_text))
            self.assertIn("Airline commitments", visible_text(html_text))
            self.assertTrue(re.search(r'<footer class="site-footer">', html_text))

    def test_mobile_head_and_lang(self) -> None:
        html_text = self.page("alaska")
        self.assertIn('<html lang="en">', html_text)
        self.assertIn('name="viewport"', html_text)


class TestTables(_Base):
    def test_listed_airlines_show_eight_rows_matching_the_data(self) -> None:
        for a in self.dot["airlines"]:
            if not a["commitments"]:
                continue
            html_text = self.page(a["id"])
            rows = re.findall(r"<tr><th scope=\"row\">(.*?)</th><td>(.*?)</td><td>(.*?)</td></tr>", html_text)
            self.assertEqual(len(rows), 8, a["id"])
            by_label = {self.dot["commitment_labels"][k]: v for k, v in a["commitments"].items()}
            for label, canc, delay in rows:
                label = label.replace("&#x27;", "'")
                want = "Yes" if by_label[label] else "No"
                self.assertIn(f">{want}<", canc)
                self.assertIn(f">{want}<", delay)

    def test_cancellation_and_delay_columns_are_equal_and_said_once(self) -> None:
        self.assertTrue(self.dot["delay_table_equals_cancellation_table"])
        for a in self.dot["airlines"]:
            if not a["commitments"]:
                continue
            text = visible_text(self.page(a["id"]))
            self.assertEqual(text.count("show the same answers"), 1, a["id"])

    def test_specific_airlines_read_right(self) -> None:
        frontier = visible_text(self.page("frontier"))
        self.assertIn("has committed to 2 of the 8 items", frontier)
        self.assertIn("It has not committed to rebooking on a partner or other airline at no additional cost, a hotel for an overnight delay or cancellation, ground transport", frontier)
        alaska = visible_text(self.page("alaska"))
        self.assertIn("has committed to 7 of the 8 items", alaska)
        self.assertIn("It has not committed to cash compensation", alaska)

    def test_spirit_is_not_listed(self) -> None:
        html_text = self.page("spirit")
        self.assertNotIn("commit-table", html_text)
        text = visible_text(html_text)
        self.assertIn("is not listed on the DOT dashboard", text)
        self.assertIn("we cannot say what Spirit Airlines has committed to", text)
        self.assertNotIn("Yes", re.findall(r"badge--(?:yes|no)\">(\w+)", html_text))


class TestPlanLinks(_Base):
    def test_plan_link_status_file_covers_every_airline(self) -> None:
        status = self.extra["plan_links"]["airlines"]
        self.assertEqual(sorted(status), sorted(a["id"] for a in self.dot["airlines"]))
        for v in status.values():
            self.assertIn(v["status"], ("ok", "blocked", "dead"))

    def test_plan_link_only_when_not_dead(self) -> None:
        status = self.extra["plan_links"]["airlines"]
        for a in self.dot["airlines"]:
            hrefs = [x.get("href") for x in parse(self.page(a["id"])).anchors]
            if status[a["id"]]["status"] == "dead":
                self.assertNotIn(a["plan_link"], hrefs, a["id"])
                self.assertIn("did not open", visible_text(self.page(a["id"])))
            else:
                self.assertIn(a["plan_link"], hrefs, a["id"])
        self.assertEqual(status["spirit"]["status"], "dead")

    def test_plan_link_is_labelled_as_the_airlines_own_page(self) -> None:
        text = visible_text(self.page("delta"))
        self.assertIn("Delta Air Lines customer service plan (the airline's own page", text)

    def test_unchecked_or_dead_link_is_dropped_in_a_fixture_build(self) -> None:
        extra = copy.deepcopy(self.extra)
        extra["plan_links"]["airlines"]["delta"]["status"] = "dead"
        del extra["plan_links"]["airlines"]["alaska"]
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "data"
            data.mkdir()
            shutil.copy(ROOT / "data" / "dot-commitments.json", data / "dot-commitments.json")
            (data / "airline-pages.json").write_text(json.dumps(extra), encoding="utf-8")
            out = Path(d) / "out"
            bal.build_pages(data_dir=data, out_dir=out, build_date=DATE)
            for aid in ("delta", "alaska"):
                a = next(x for x in self.dot["airlines"] if x["id"] == aid)
                page = (out / f"{aid}.html").read_text(encoding="utf-8")
                self.assertNotIn(a["plan_link"], page, aid)
                self.assertIn(DASHBOARD, page)
                # the DOT facts stay
                self.assertIn("has committed to", page)

    def test_blocked_links_are_linked(self) -> None:
        status = self.extra["plan_links"]["airlines"]
        for aid in ("allegiant", "american", "united"):
            self.assertEqual(status[aid]["status"], "blocked")


class TestIndex(_Base):
    def test_index_lists_all_ten_with_one_line_each(self) -> None:
        html_text = self.page("index")
        p = parse(html_text)
        hrefs = [a.get("href") for a in p.anchors]
        for a in self.dot["airlines"]:
            self.assertIn(f"/airlines/{a['id']}", hrefs)
        self.assertEqual(html_text.count('class="airport-index-card"'), 10)
        text = visible_text(html_text)
        self.assertIn("Has committed to 7 of 8 items on the DOT dashboard.", text)
        self.assertIn("Not listed on the DOT dashboard.", text)
        self.assertIn("not legal advice", text.lower())
        self.assertIn("14 CFR 260.6", text)
        self.assertEqual([h.strip() for h in p.h1], ["Airline delay and cancellation commitments"])
        ld = json.loads(p.jsonld[0])
        self.assertEqual(len(ld["itemListElement"]), 2)

    def test_index_title_and_description_differ_from_the_pages(self) -> None:
        p = parse(self.page("index"))
        self.assertNotIn(p.title, [parse(self.page(a["id"])).title for a in self.dot["airlines"]])


class TestSitemap(_Base):
    def test_block_has_eleven_entries(self) -> None:
        text = self.sitemap.read_text(encoding="utf-8")
        m = re.search(r"<!-- airlines:begin -->(.*?)<!-- airlines:end -->", text, re.S)
        self.assertIsNotNone(m)
        locs = re.findall(r"<loc>([^<]+)</loc>", m.group(1))
        self.assertEqual(len(locs), 11)
        self.assertEqual(locs[0], f"{SITE}/airlines/")
        for a in self.dot["airlines"]:
            self.assertIn(f"{SITE}/airlines/{a['id']}", locs)
        self.assertEqual(len(re.findall(r"<lastmod>2026-11-14</lastmod>", m.group(1))), 11)

    def test_rebuild_replaces_the_block_and_keeps_the_rest(self) -> None:
        before = self.sitemap.read_text(encoding="utf-8")
        bal.update_sitemap(self.sitemap, [a["id"] for a in self.dot["airlines"]], DATE)
        after = self.sitemap.read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertEqual(after.count("airlines:begin"), 1)
        # other entries are still there
        self.assertIn(f"{SITE}/stuck", after)
        self.assertIn(f"{SITE}/airports/", after)
        self.assertIn("<!-- airports:begin -->", after)

    def test_sitemap_from_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sm = Path(d) / "sitemap.xml"
            bal.update_sitemap(sm, ["a", "b"], DATE)
            t = sm.read_text(encoding="utf-8")
            self.assertEqual(t.count("<url>"), 3)
            self.assertTrue(t.rstrip().endswith("</urlset>"))

    def test_main_with_scratch_sitemap_leaves_repo_sitemap_alone(self) -> None:
        repo_before = (ROOT / "sitemap.xml").read_bytes()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "airlines"
            sm = Path(d) / "sm.xml"
            sm.write_text('<?xml version="1.0"?>\n<urlset></urlset>\n', encoding="utf-8")
            rc = bal.main(["--out", str(out), "--sitemap", str(sm), "--date", DATE])
            self.assertEqual(rc, 0)
            self.assertEqual(len(list(out.glob("*.html"))), 11)
            self.assertEqual(sm.read_text(encoding="utf-8").count("<url>"), 11)
        self.assertEqual((ROOT / "sitemap.xml").read_bytes(), repo_before)


class TestWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.yml = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")

    def test_workflow_builds_copies_and_guards_airlines(self) -> None:
        self.assertIn("python tools/build_airline_pages.py", self.yml)
        self.assertLess(self.yml.index("build_airport_pages.py"), self.yml.index("build_airline_pages.py"))
        self.assertIn("cp airlines/*.html _site/airlines/", self.yml)
        self.assertIn("_site/airlines/index.html", self.yml)
        self.assertIn("Expected $expected_airlines airline pages in _site/airlines", self.yml)
        # the airport guard stays
        self.assertIn('"$airport_count" -ne 100', self.yml)
        # the guard runs after the copy step and before the upload
        self.assertLess(self.yml.index("cp airlines/*.html"), self.yml.index("_site/airlines/index.html is missing"))
        self.assertLess(self.yml.index("_site/airlines/index.html is missing"), self.yml.index("Upload Pages artifact"))

    def test_generated_folder_is_ignored_like_airports(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn("airlines/", ignore)
        self.assertIn("/airports/", ignore)  # anchored: assets/art/airports/ is committed

    def test_service_worker_has_no_airline_page_list(self) -> None:
        sw = (ROOT / "sw.js").read_text(encoding="utf-8")
        self.assertNotIn("airlines/", sw)

    def test_airport_footer_links_the_airline_index(self) -> None:
        footer = bap._render_footer()
        self.assertIn('<a class="tap" href="/airlines/">Airline commitments</a>', footer)
        self.assertIn('href="/airports/">Airports</a>', footer)
        header = bap._render_header()
        self.assertIn('href="/airports/" aria-current="page">Airports</a>', header)

    def test_stuck_page_links_every_airline_without_javascript(self) -> None:
        html_text = (ROOT / "stuck.html").read_text(encoding="utf-8")
        data = json.loads((ROOT / "data" / "dot-commitments.json").read_text(encoding="utf-8"))
        for a in data["airlines"]:
            self.assertIn(f'href="/airlines/{a["id"]}"', html_text)
        self.assertIn('href="/airlines/"', html_text)
        # the list is outside the script-built wizard and outside <noscript>
        ul = html_text.index('class="airline-links-list"')
        self.assertGreater(ul, html_text.index("</noscript>"))

    def test_stuck_result_links_the_selected_airline(self) -> None:
        js = (ROOT / "stuck.js").read_text(encoding="utf-8")
        self.assertIn('pageUrl: "/airlines/" + airline.id', js)
        self.assertIn('"See what " + airline.name + " has committed to"', js)
        self.assertIn("if (cm.pageUrl)", js)
        # the "other airline" model has no page link
        other = js[js.index('kind: "other"'):js.index('kind: "unlisted"')]
        self.assertNotIn("pageUrl", other)

    def test_about_and_sources_link_the_airline_pages(self) -> None:
        for rel in ("about.html", "sources.html"):
            self.assertIn('href="/airlines/"', (ROOT / rel).read_text(encoding="utf-8"), rel)
        src = (ROOT / "sources.html").read_text(encoding="utf-8")
        row = re.search(r'<tr data-src="dot-dashboard">.*?</tr>', src, re.S).group(0)
        self.assertIn('href="/airlines/"', row)


if __name__ == "__main__":
    unittest.main()
