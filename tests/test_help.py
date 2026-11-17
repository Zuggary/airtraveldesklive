"""Static help contracts; no network or real flight data."""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit
from tools import build_airline_pages as airlines
from tools import build_airport_pages as airports
from tools import prerender_home

ROOT = Path(__file__).resolve().parents[1]
SLUGS = ('ground-stop', 'ground-delay', 'weather-disruption', 'cancellation')

class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.h1 = 0; self.links = []; self.canonical = []; self.scripts = []
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'h1': self.h1 += 1
        if tag == 'a': self.links.append(a.get('href', ''))
        if tag == 'link' and a.get('rel') == 'canonical': self.canonical.append(a['href'])
        if tag == 'script' and a.get('src'): self.scripts.append(a['src'])

class Help(unittest.TestCase):
    def test_pages_copy_sources_and_links(self):
        for name in ('index',) + SLUGS:
            path = ROOT / 'help' / (name + '.html')
            with self.subTest(page=name):
                self.assertTrue(path.is_file())
                text = path.read_text(); page = Page(text)
                self.assertEqual(page.h1, 1)
                suffix = 'help/' if name == 'index' else 'help/' + name + '.html'
                self.assertEqual(page.canonical, ['https://www.airtraveldesklive.com/' + suffix])
                self.assertNotRegex(text.lower(), r'guarantee|will end|must pay|must cover|\b\d+\s*(?:hours?|minutes?)\b')
                self.assertIn('never means clear', text)
                self.assertIn('/stuck.html', page.links)
                self.assertIn('/airlines/', page.links)
                self.assertNotIn('/count.js', page.scripts)
                if name != 'index':
                    self.assertTrue(any('faa.gov/' in link for link in page.links))
                    for phrase in ('arrivals', 'departures', 'single flight', 'rebooking before paying', 'Keep receipts', 'What is not known'):
                        self.assertIn(phrase.lower(), text.lower())
                for link in page.links:
                    url = urlsplit(link)
                    if url.scheme or url.netloc or not url.path: continue
                    if url.path.startswith(('/airports', '/airlines')): continue  # generated at deploy, gitignored
                    target = ROOT / url.path.lstrip('/') if url.path.startswith('/') else path.parent / url.path
                    candidates = [target, target / 'index.html', target.with_suffix('.html')]
                    self.assertTrue(any(p.is_file() for p in candidates), link)
        cancellation = (ROOT/'help/cancellation.html').read_text()
        self.assertIn(airlines.REFUND_SENTENCE, cancellation)
        self.assertIn('Statutory refund rule', cancellation)
        self.assertIn('Voluntary airline commitments', cancellation)
        weather = (ROOT/'help/weather-disruption.html').read_text()
        self.assertIn('https://www.weather.gov/', weather)
        self.assertIn('https://aviationweather.gov/data/metar/', weather)

    def test_polished_help_layout_and_action(self):
        for name in ('index',) + SLUGS:
            with self.subTest(page=name):
                text = (ROOT / 'help' / (name + '.html')).read_text()
                self.assertRegex(text, r'</h1><p>[^<]+</p>\s*<p class="help-flight-check"><a class="tap" href="/airlines/">Check your flight with your airline</a></p>')
                self.assertIn('class="prose-card help-prose"', text)
                self.assertRegex(text, r'<h2>Sources</h2>\s*<ul class="help-sources">\s*<li><a href="https://')
                self.assertNotIn('only the airline can confirm', text.lower())
                self.assertNotIn('this airport', text.lower())
        stop = (ROOT / 'help/ground-stop.html').read_text()
        self.assertIn('A ground stop holds affected inbound flights at their departure airports.', stop)
        self.assertIn('Your airline has the details for your own flight.', stop)
        self.assertIn('the airport under the ground stop', stop)
        css = (ROOT / 'style.css').read_text()
        self.assertIn('.help-prose > p, .help-prose > ul { max-width: 68ch; }', css)
        self.assertIn('.site-footer p.container { margin-inline: auto; }', css)

    def test_offline_sitemap_and_rendered_links(self):
        block = airports.render_sitemap_block(['ZZZ'], '2026-11-17')
        sw = (ROOT/'sw.js').read_text()
        for suffix in ('',) + tuple(s + '.html' for s in SLUGS):
            self.assertIn('/help/' + suffix, block)
            self.assertIn('./help/' + suffix, sw)
        now = datetime(2026, 11, 17, tzinfo=timezone.utc)
        for kind, slug in [('ground_stop', 'ground-stop'), ('ground_delay', 'ground-delay')]:
            rendered = prerender_home.render_events({'events': [{'source': 'FAA', 'kind': kind, 'airport': 'ZZZ', 'fields': {}}]}, {'ZZZ': {'name': 'Example Airport', 'short': 'Example'}}, now.isoformat(), now)
            self.assertIn('/help/' + slug + '.html', rendered)
        for path in [ROOT/'stuck.html' , ROOT/'index.html', ROOT/'airports/SFO.html']:
            if not path.exists(): continue  # airports/ is generated at deploy (gitignored)
            text = path.read_text()
            for slug in SLUGS: self.assertIn('/help/' + slug + '.html', text)
