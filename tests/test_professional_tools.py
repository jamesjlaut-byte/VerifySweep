from html.parser import HTMLParser
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = {
    'google-listing-evidence-builder.html': ('listingForm', 'listingOutput'),
    'credential-claim-checker.html': ('credentialForm', 'credentialOutput'),
    'review-pattern-analyzer.html': ('reviewForm', 'reviewOutput'),
    'competitor-comparison.html': ('comparisonForm', 'comparisonBody'),
}


class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get('id'):
            self.ids.add(values['id'])
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])


class ProfessionalToolTests(unittest.TestCase):
    def test_requested_tools_are_live_dashboard_destinations(self):
        dashboard = (ROOT / 'pro-dashboard.html').read_text(encoding='utf-8')
        parser = IdParser()
        parser.feed(dashboard)
        for filename in TOOLS:
            self.assertIn('/' + filename, parser.links)
        for label in (
            'Google Listing Evidence Builder',
            'Credential Claim Checker',
            'Review Pattern Analyzer',
            'Competitor Comparison',
        ):
            location = dashboard.index(label)
            nearby = dashboard[max(0, location - 120):location + 500]
            self.assertNotIn('COMING SOON', nearby, label)

    def test_tool_pages_have_required_workspaces_and_shared_assets(self):
        for filename, required_ids in TOOLS.items():
            path = ROOT / filename
            self.assertTrue(path.is_file(), filename)
            page = path.read_text(encoding='utf-8')
            parser = IdParser()
            parser.feed(page)
            for required_id in required_ids:
                self.assertIn(required_id, parser.ids, f'{filename}: {required_id}')
            self.assertIn('/assets/pro-tool-workspaces.css', page)
            self.assertIn('/assets/pro-tool-workspaces.js', page)
            self.assertIn('chimneyai.verifysweep.com/pro', page)


if __name__ == '__main__':
    unittest.main()
