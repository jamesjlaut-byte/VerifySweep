import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('directory_api',ROOT/'api'/'directory.py')
directory=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(directory)


class UnifiedDirectoryTests(unittest.TestCase):
    def test_national_seed_is_canonical_and_neutral(self):
        data=json.loads((ROOT/'data'/'national-directory.json').read_text())
        self.assertEqual(data['source_record_count'],356)
        self.assertEqual(data['canonical_record_count'],348)
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


if __name__=='__main__':unittest.main()
