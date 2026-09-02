from html.parser import HTMLParser
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED = [
    '/professional.html',
    '/pro-dashboard.html',
    '/investigations.html',
    '/website-audit.html',
    '/appliance-manual-library.html',
    '/pro-education.html',
    'https://chimneyai.verifysweep.com/pro',
    '/pro-blog.html',
]


class SectionBarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_bar = False
        self.bar_tag = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in ('div', 'nav') and 'sectionbar' in values.get('class', '').split():
            self.in_bar = True
            self.bar_tag = tag
        elif self.in_bar and tag == 'a':
            self.links.append(values.get('href'))

    def handle_endtag(self, tag):
        if self.in_bar and tag == self.bar_tag:
            self.in_bar = False


class MenuParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_menu = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = values.get('class', '').split()
        if tag == 'nav' and 'menu' in classes:
            self.in_menu = True
        elif self.in_menu and tag == 'a':
            self.links.append(values.get('href'))

    def handle_endtag(self, tag):
        if self.in_menu and tag == 'nav':
            self.in_menu = False


class ProfessionalNavigationTests(unittest.TestCase):
    def test_every_professional_section_bar_uses_the_same_destinations(self):
        pages = []
        for path in ROOT.glob('*.html'):
            text = path.read_text(encoding='utf-8')
            if 'class="sectionbar"' not in text or 'Professional navigation' not in text:
                continue
            parser = SectionBarParser()
            parser.feed(text)
            pages.append(path.name)
            self.assertEqual(parser.links, EXPECTED, path.name)
            self.assertNotIn('/start-investigation.html', parser.links, path.name)
        self.assertEqual(len(pages), 47)

    def test_internal_professional_destinations_exist(self):
        for href in EXPECTED:
            if href.startswith('/'):
                self.assertTrue((ROOT / href.removeprefix('/')).is_file(), href)

    def test_professional_mobile_menus_include_core_tools(self):
        required = EXPECTED + ['/homeowners.html']
        pages = []
        for path in ROOT.glob('*.html'):
            text = path.read_text(encoding='utf-8')
            if 'class="sectionbar"' not in text or 'Professional navigation' not in text:
                continue
            parser = MenuParser()
            parser.feed(text)
            if not parser.links:
                continue
            pages.append(path.name)
            for href in required:
                self.assertIn(href, parser.links, f'{path.name}: {href}')
            self.assertNotIn('/ai-fraudwatch.html', parser.links, path.name)
        self.assertEqual(len(pages), 26)


if __name__ == '__main__':
    unittest.main()
