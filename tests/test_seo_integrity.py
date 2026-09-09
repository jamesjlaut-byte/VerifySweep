"""Keep the public sitemap aligned with indexable canonical root pages."""
import json
import re
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Metadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.canonicals = []
        self.descriptions = []
        self.noindex = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('name') == 'description':
            self.descriptions.append(attrs.get('content', '').strip())
        if tag == 'meta' and attrs.get('name') in ('robots', 'googlebot'):
            self.noindex |= 'noindex' in attrs.get('content', '').lower()


class SeoIntegrityTests(unittest.TestCase):
    def test_homepage_identifies_site_without_unsupported_trust_claims(self):
        html = (ROOT / 'index.html').read_text()
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        records = [json.loads(block) for block in blocks]
        websites = [record for record in records if record.get('@type') == 'WebSite']
        self.assertEqual(len(websites), 1)
        self.assertEqual(websites[0]['name'], 'VerifySweep')
        self.assertEqual(websites[0]['url'], 'https://www.verifysweep.com/')
        self.assertNotIn('aggregateRating', websites[0])
        self.assertNotIn('review', websites[0])

    def test_sitemap_contains_only_unique_indexable_canonical_pages(self):
        tree = ET.parse(ROOT / 'sitemap.xml')
        urls = [node.text for node in tree.findall('.//{*}loc')]
        self.assertEqual(len(urls), len(set(urls)))
        redirects = json.loads((ROOT / 'vercel.json').read_text())['redirects']
        for url in urls:
            with self.subTest(url=url):
                parsed = urlsplit(url)
                self.assertEqual(parsed.scheme, 'https')
                self.assertEqual(parsed.netloc, 'www.verifysweep.com')
                self.assertFalse(parsed.query or parsed.fragment)
                self.assertFalse(any(re.fullmatch(r['source'], parsed.path) for r in redirects))
                path = ROOT / (parsed.path.lstrip('/') or 'index.html')
                self.assertTrue(path.is_file())
                metadata = Metadata(path.read_text())
                self.assertEqual(metadata.canonicals, [url])
                self.assertEqual(len(metadata.descriptions), 1)
                self.assertTrue(metadata.descriptions[0])
                self.assertFalse(metadata.noindex)

    def test_search_landing_page_titles_are_distinct_and_descriptive(self):
        titles = []
        for name in ('index.html', 'homeowners.html', 'professional.html',
                     'appliance-manual-library.html'):
            title = re.search(r'<title>(.*?)</title>', (ROOT / name).read_text()).group(1)
            self.assertIn('VerifySweep', title)
            self.assertGreater(len(title.split()), 4)
            titles.append(title)
        self.assertEqual(len(titles), len(set(titles)))
