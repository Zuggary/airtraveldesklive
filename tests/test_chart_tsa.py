import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
SITE = "https://www.airtraveldesklive.com"


def run_tool(name, *args):
    return subprocess.check_output([sys.executable, "-B", str(ROOT / "tools" / name), *args],
                                   cwd=ROOT, text=True)


def rounded_change(current, prior):
    return (Decimal(current - prior) * 100 / prior).quantize(Decimal("0.1"))


class PageParser(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.tags = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ChartTsaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROOT / "data" / "tsa-history.json"
        cls.history = json.loads(cls.source.read_text())
        cls.counts = cls.history["days"]
        cls.latest = date.fromisoformat(cls.history["latest_date"])
        cls.first = cls.latest - timedelta(days=59)
        cls.last = date(cls.latest.year, 12, 1)
        cls.record = date.fromisoformat(cls.history["record_date"])
        cls.aligned = cls.record + timedelta(days=364)
        cls.thanksgiving = [date(cls.latest.year, 11, day) for day in range(22, 29)
                            if date(cls.latest.year, 11, day).weekday() == 3][0]
        cls.latest_count = cls.counts[str(cls.latest)]
        cls.day_change = rounded_change(cls.latest_count, cls.value(cls.latest, 364))
        cls.week_change = rounded_change(
            sum(cls.value(cls.latest - timedelta(days=i), 0) for i in range(7)),
            sum(cls.value(cls.latest - timedelta(days=i), 364) for i in range(7)),
        )
        cls.title = (f"Air travel is running {cls.week_change:+.1f}% "
                     f"{'below' if cls.week_change < 0 else 'above'} last year as the Thanksgiving rush starts")
        directory = tempfile.TemporaryDirectory(dir=ROOT)
        cls.addClassCleanup(directory.cleanup)
        cls.output = Path(directory.name) / "out"
        cls.pages = Path(directory.name) / "charts"
        run_tool("build_chart_tsa.py", "--data", str(cls.source), "--out-dir", str(cls.output))
        run_tool("build_charts.py", "--data", str(cls.source.parent), "--out", str(cls.pages))

    @classmethod
    def value(cls, day, offset):
        return cls.counts[str(day - timedelta(days=offset))]

    def test_labels_match_history(self):
        peak = min((self.first + timedelta(days=i) for i in range(60)),
                   key=lambda day: (-self.value(day, 0), day))
        expected = {
            "latest_date": str(self.latest), "latest_count": self.latest_count,
            "yoy_pct_latest_day": float(self.day_change), "yoy_pct_7_day": f"{self.week_change:+.1f}",
            "peak_day": str(peak), "peak_count": self.value(peak, 0),
            "record_date": str(self.record), "record_count": self.history["record_count"],
            "aligned_record_date": str(self.aligned), "thanksgiving_date": str(self.thanksgiving),
        }
        self.assertEqual(set(p.name for p in self.output.iterdir()),
                         {"chart-tsa-wide.svg", "chart-tsa-narrow.svg", "chart-tsa-labels.json"})
        self.assertEqual(json.loads((self.output / "chart-tsa-labels.json").read_text()), expected)

    def test_svg_text_and_coordinates(self):
        for layout, width in (("wide", 1000), ("narrow", 420)):
            with self.subTest(layout=layout):
                raw = (self.output / f"chart-tsa-{layout}.svg").read_text()
                svg = ET.fromstring(raw)
                self.assertEqual(svg.attrib["viewBox"], f"0 0 {width} 560")
                self.assertEqual(svg.attrib["role"], "img")
                title, desc = (svg.find(NS + tag) for tag in ("title", "desc"))
                self.assertEqual(svg.attrib["aria-labelledby"].split(), [title.attrib["id"], desc.attrib["id"]])
                self.assertEqual(title.text, self.title)
                text = "\n".join(node.text for node in svg.iter(NS + "text"))
                latest = f"{self.latest:%a %b} {self.latest.day}: {self.latest_count / 1e6:.2f}M"
                if layout == "wide":  # the phone layout leaves these to the summary cards above the chart (still in the SVG desc)
                    self.assertIn(latest, text)
                change = f"{self.day_change:+.1f}% vs same weekday last year"
                if layout == "wide":
                    self.assertIn(change, text)
                average = f"7-day avg {self.week_change:+.1f}%"
                if layout == "wide":
                    self.assertIn(average, text)
                record = (f"Record: {self.history['record_count'] / 1e6:.2f}M on "
                          f"{self.record:%a %b} {self.record.day}, {self.record.year}")
                self.assertIn(record, text)
                self.assertIn(f"Thanksgiving · {self.thanksgiving:%a %b} {self.thanksgiving.day}", text)
                for label in (self.title, latest, change, average, record):
                    self.assertIn(label, desc.text)
                self.assertNotRegex(raw, r"https?://|<script")
                xticks = svg.findall(f".//{NS}text[@class='x-tick']")
                yticks = svg.findall(f".//{NS}text[@class='y-tick']")
                x0, x1 = (float(node.attrib["x"]) for node in (xticks[0], xticks[-1]))
                y0, y1 = (float(node.attrib["y"]) for node in (yticks[0], yticks[-1]))
                v0, v1 = (float(node.text[:-1]) * 1e6 for node in (yticks[0], yticks[-1]))
                x_scale = (x1 - x0) / (self.last - self.first).days
                y_scale = (y1 - y0) / (v1 - v0)
                for node in xticks:
                    day = self.first + timedelta(days=round((float(node.attrib["x"]) - x0) / x_scale))
                    self.assertEqual(node.text, f"{day:%b} {day.day}")
                for node in yticks:
                    value = float(node.text[:-1]) * 1e6
                    self.assertAlmostEqual(float(node.attrib["y"]), y0 + (value - v0) * y_scale, delta=.02)
                for name, offset, last, window in (
                    ("current", 0, self.latest, 1), ("prior", 364, self.last, 1),
                    ("current-average", 0, self.latest, 7), ("prior-average", 364, self.last, 7),
                ):
                    path = svg.find(f".//{NS}path[@class='series-{name}']")
                    pairs = re.findall(r"[ML] ([\d.]+) ([\d.]+)", path.attrib["d"])
                    self.assertEqual(len(pairs), (last - self.first).days + 1)
                    self.assertEqual("stroke-dasharray" in path.attrib, bool(offset))
                    for index, (column, row) in enumerate(pairs):
                        day = self.first + timedelta(days=index)
                        avg = sum(self.value(day - timedelta(days=i), offset) for i in range(window)) / window
                        self.assertAlmostEqual(float(column), x0 + index * x_scale, delta=.5)
                        self.assertAlmostEqual(float(row), y0 + (avg - v0) * y_scale, delta=.5)
                box = svg.find(f".//{NS}rect")
                self.assertAlmostEqual(float(box.attrib["x"]),
                                       x0 + (self.thanksgiving - timedelta(days=4) - self.first).days * x_scale,
                                       delta=.5)
                self.assertAlmostEqual(float(box.attrib["width"]), 7 * x_scale, delta=.5)
                for day, count in ((self.aligned, self.history["record_count"]),
                                   (self.latest, self.latest_count)):
                    self.assertTrue(any(
                        abs(float(dot.attrib["cx"]) - (x0 + (day - self.first).days * x_scale)) <= .5
                        and abs(float(dot.attrib["cy"]) - (y0 + (count - v0) * y_scale)) <= .5
                        for dot in svg.iter(NS + "circle")
                    ))

    def test_page_text_and_table_match_history(self):
        page = (self.pages / "tsa/index.html").read_text()
        self.assertIn(f"<h1>{self.title}</h1>", page)
        self.assertIn(f"<strong>{self.latest_count:,}</strong>{self.day_change:+.1f}% vs last year", page)
        self.assertIn(f"<strong>{self.week_change:+.1f}%</strong>", page)
        self.assertIn(f"<strong>{self.history['record_count'] / 1e6:.2f}M</strong>"
                      f"{self.record:%a %b} {self.record.day}, {self.record.year}", page)
        self.assertIn("Source: TSA checkpoint travel numbers (public daily table), "
                      "tsa.gov/travel/passenger-volumes. Last year is the same weekday, "
                      f"364 days earlier. Updated {self.latest}.", page)
        rows = re.findall(r'<tr><th scope="row"><time datetime="([^"]+)">([^<]+)</time></th>'
                          r"<td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>", page)
        self.assertEqual(len(rows), 14)
        for offset, row in enumerate(rows):
            day = self.latest - timedelta(days=offset)
            current, prior = (self.value(day, shift) for shift in (0, 364))
            self.assertEqual(row, (str(day), f"{day:%a %b} {day.day}", f"{current:,}",
                                   f"{prior:,}", f"{rounded_change(current, prior):+.1f}%"))
        for layout in ("wide", "narrow"):
            self.assertIn((self.output / f"chart-tsa-{layout}.svg").read_text(), page)

    def test_page_metadata_and_no_external_requests(self):
        reference = (ROOT / "shows.html").read_text()
        for relative, url in (("index.html", SITE + "/charts"),
                              ("tsa/index.html", SITE + "/charts/tsa")):
            with self.subTest(relative=relative):
                path = self.pages / relative
                self.assertLessEqual(path.stat().st_size, 150_000)
                page = path.read_text()
                tags = PageParser(page).tags
                canonical = [attrs["href"] for tag, attrs in tags
                             if tag == "link" and attrs.get("rel") == "canonical"]
                self.assertEqual(canonical, [url])
                og = {attrs["property"]: attrs["content"] for tag, attrs in tags
                      if tag == "meta" and "property" in attrs}
                self.assertEqual(og["og:url"], url)
                self.assertIn(self.title, og["og:description"])
                ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', page)[1]
                crumbs = json.loads(ld)
                self.assertEqual(crumbs["@type"], "BreadcrumbList")
                self.assertEqual(crumbs["itemListElement"][-1]["item"], url)
                without_metadata = re.sub(r'<(?:meta|link) [^>]*(?:og:|rel="canonical")[^>]*>', "", page)
                self.assertNotRegex(without_metadata.replace(ld, ""), r"https?://")
                scripts = re.findall(r"^.*<script src=.*$", page, re.M)
                up = "../" if relative == "index.html" else "../../"
                self.assertEqual(scripts, [f"  <script src=\"{up}theme.js\" defer></script>",
                                           f"  <script src=\"{up}watch.js\" defer></script>"])
                for script in scripts:  # same scripts as the reference page, with root-relative paths fixed for the folder depth
                    self.assertIn(script.replace(up, ""), reference)
                for tag, attrs in tags:
                    assets = ("src", "srcset") + (("href",) if tag == "link" and
                                                  attrs.get("rel") != "canonical" else ())
                    for asset in assets:
                        self.assertNotRegex(attrs.get(asset, ""), r"(?i)(?:https?:)?//")
        self.assertIn('href="tsa/"', (self.pages / "index.html").read_text())
        self.assertIn("@media (max-width: 640px)", (self.pages / "chart.css").read_text())

    def test_sitemap(self):
        self.assertEqual(run_tool("build_charts.py", "--sitemap-lines").splitlines(),
                         [f"<url><loc>{SITE}/charts</loc></url>", f"<url><loc>{SITE}/charts/tsa</loc></url>"])


if __name__ == "__main__":
    unittest.main()
