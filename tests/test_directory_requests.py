import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('directory_requests', Path(__file__).resolve().parents[1] / 'api/directory.py')
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


class DirectoryRequestTests(unittest.TestCase):
    def test_company_professionals_preserve_review_facts_without_private_evidence(self):
        source={'id':'example','holder':'Test Person','company':'Test Company','city':'Austin','state':'TX','zip':'78701','identity_status':'VERIFIED','company_affiliation_status':'VERIFIED','expiration_date':'2099-01-01','credential_number':'123','review_note':'private review note','submitter_email_private':'private@example.test'}
        with patch.object(directory,'static_records',return_value=[source]):
            result=directory.company_professionals({'company':'Test Company','state':'TX'})[0]
        self.assertEqual(result['identity_status'],'VERIFIED')
        self.assertEqual(result['company_affiliation_status'],'VERIFIED')
        self.assertEqual(result['expiration_date'],'2099-01-01')
        self.assertNotIn('review_note',result)
        self.assertNotIn('submitter_email_private',result)

    def test_issuer_punctuation_aliases_keep_real_credential_matches(self):
        for issuer in ('FIRE', 'F.I.R.E.', 'fire'):
            rows=directory.search_static_companies(q='Pete Pohlman',issuer=issuer)
            self.assertTrue(rows,issuer)
            self.assertEqual(rows[0]['reviewed_professionals'][0]['holder'],'Pete Pohlman')
        self.assertEqual(directory.credential_issuer_id('NCSG / CCP'),'ncsg')
        self.assertFalse(directory.credential_matches_filters({'issuer':'NFI','credential':'Gas Specialist'},'CSIA'))

    def test_page_credential_values_match_actual_records(self):
        from html.parser import HTMLParser
        class Options(HTMLParser):
            values=[]
            def handle_starttag(self,tag,attrs):
                if tag=='option' and 'value' in dict(attrs):self.values.append(dict(attrs)['value'])
        parser=Options()
        parser.feed((Path(__file__).resolve().parents[1]/'find-a-pro.html').read_text())
        for credential in ('Certified Chimney Sweep','F.I.R.E. Certified Inspector / Technician'):
            self.assertIn(credential,parser.values)
            self.assertTrue(directory.search_static_companies(credential_type=credential))

    def request(self, query):
        handler = object.__new__(directory.handler)
        handler.path = '/api/directory?' + query
        handler.headers = {}
        handler.sendj = Mock()
        handler.do_GET()
        return handler.sendj.call_args.args

    def test_invalid_zip_and_radius_are_rejected_before_search(self):
        with patch.object(directory, 'search_companies_db') as companies, patch.object(directory, 'search_db') as people:
            for view in ('companies', 'professionals'):
                for value in ('zip=78701oops', 'zip=787010', 'radius=abc', 'radius=0', 'radius=1000'):
                    with self.subTest(view=view, value=value):
                        code, _ = self.request('view=' + view + '&q=Austin&' + value)
                        self.assertEqual(code, 400)
            companies.assert_not_called()
            people.assert_not_called()

    def test_zip_resolution_preserves_verified_professional_priority(self):
        near = {'id':'near', 'company':'Near Company', 'website':'https://near.example', 'distance':1, 'match_rank':4, 'reviewed_professionals':[]}
        verified = {'id':'verified', 'company':'Verified Company', 'website':'https://verified.example', 'distance':20, 'match_rank':5, 'reviewed_professionals':[{'holder':'Named Person', 'display_status':'CREDENTIAL VERIFIED'}]}
        with patch.object(directory, 'search_companies_db', side_effect=[([near, verified], False), ([], False)]), patch.object(directory, 'resolve_us_zip', return_value={'city':'Austin','state':'TX'}):
            code, data = self.request('view=companies&zip=78701&radius=25')
        self.assertEqual(code, 200)
        self.assertEqual([r['id'] for r in data['results']], ['verified', 'near'])
