import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('directory_api',ROOT/'api'/'directory.py')
directory=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(directory)


class UnifiedDirectoryTests(unittest.TestCase):
    def test_national_seed_is_canonical_and_neutral(self):
        data=json.loads((ROOT/'data'/'national-directory.json').read_text())
        self.assertEqual(data['source_record_count'],356)
        self.assertEqual(data['canonical_record_count'],347)
        domains=[x['normalized_domain'] for x in data['records'] if x.get('normalized_domain')]
        self.assertEqual(len(domains),len(set(domains)))
        self.assertTrue(all(x['public_status']=='unverified' for x in data['records']))
        self.assertTrue(all(c['classification']=='UNVERIFIED CLAIM' for x in data['records'] for c in x['company_claims']))
        self.assertTrue(all(p['status']=='VERIFICATION NEEDED' for x in data['records'] for p in x['professional_candidates']))

    def test_austin_service_area_search(self):
        rows=directory.search_static_companies(city='Austin',state='TX')
        hill=next(x for x in rows if x['company'].startswith('Hill Country'))
        self.assertEqual(hill['match_reason'],'Published service area match')
        self.assertIn('Austin, TX',hill['service_area_labels'])

    def test_named_professional_research_search_is_not_verified(self):
        seed=directory.national_company_records()
        record=next(x for x in seed if x.get('professional_candidates'))
        query=record['professional_candidates'][0]['name_or_note']
        rows=directory.search_static_companies(q=query)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['match_reason'],'Named professional research match')
        self.assertFalse(rows[0].get('professionals'))

    def test_same_name_different_hq_is_not_merged(self):
        rows=[x for x in directory.national_company_records() if x['company'].lower().startswith('the chimney doctor')]
        identities={(x['hq_city'],x['hq_state']) for x in rows}
        self.assertIn(('Metamora','IL'),identities)
        self.assertIn(('Jackson','MS'),identities)

    def test_research_confirmed_cross_state_record_is_merged(self):
        rows=[x for x in directory.national_company_records() if x['company']=='The Original Chimney Sweep, Inc.']
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0]['states_discovered']),{'MA','RI'})

    def test_zip_resolver_uses_fixed_host_and_sanitized_zip(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return b'{"places":[{"place name":"Austin","state abbreviation":"TX"}]}'
        directory.resolve_us_zip.cache_clear()
        with patch.object(directory,'urlopen',return_value=Response()) as opened:
            self.assertEqual(directory.resolve_us_zip('78701'),{'city':'Austin','state':'TX'})
            self.assertEqual(opened.call_args.args[0].full_url,'https://api.zippopotam.us/us/78701')
        self.assertIsNone(directory.resolve_us_zip('http://127.0.0.1'))

    def test_every_state_and_dc_has_public_search_coverage(self):
        states='AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split()
        self.assertEqual([], [state for state in states if not directory.search_static_companies(state=state)])

    def test_exact_company_match_ranks_first(self):
        rows=directory.search_static_companies(q='Hill Country Air Duct And Chimney Sweeps LLC')
        self.assertTrue(rows)
        self.assertEqual(rows[0]['company'],'Hill Country Air Duct And Chimney Sweeps LLC')
        self.assertEqual(rows[0]['match_reason'],'Exact company match')

    def test_city_location_ranks_before_service_area(self):
        rows=directory.search_static_companies(city='Austin',state='TX')
        ranks=[row['match_rank'] for row in rows]
        self.assertEqual(ranks,sorted(ranks))
        self.assertEqual(rows[0]['match_reason'],'City match')

    def test_reviewed_professional_name_search_uses_reviewed_records(self):
        rows=directory.search_static_companies(q='Pete Pohlman')
        self.assertEqual(rows[0]['company'],'Black Velvet Chimney')
        self.assertEqual(rows[0]['match_reason'],'Reviewed professional match')
        self.assertEqual(rows[0]['reviewed_professional_names'],['Pete Pohlman'])
        self.assertEqual(rows[0]['verified_professional_count'],1)

    def test_reviewed_individual_filter_does_not_promote_company_claims(self):
        rows=directory.search_static_companies(verified_only=True)
        self.assertEqual({row['company'] for row in rows},{
            'Black Velvet Chimney','Duct Time','Hill Country Air Duct And Chimney Sweeps LLC','Wolfman Chimney & Fireplace'
        })
        self.assertTrue(all(row['verified_professional_count']>0 for row in rows))
        claims_only=directory.search_static_companies(q='1st Choice Chimney Commercial LLC')
        self.assertEqual(claims_only[0]['verified_professional_count'],0)


if __name__=='__main__':unittest.main()
