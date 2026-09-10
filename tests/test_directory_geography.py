import importlib.util
import re
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('geography',ROOT/'api/directory.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class DirectoryGeographyTests(TestCase):
    def test_all_50_states_and_dc_names_codes_and_city_queries(self):
        self.assertEqual(len(d.US_STATES),51)
        for code,name in d.US_STATES.items():
            for query in (code,code.lower(),name,name.upper(),'  '+name.replace(' ','   ')+'  '):
                with self.subTest(query=query):self.assertEqual(d.normalize_location_query(query),('', '',code))
            for query in ('Example City, '+name,'Example City '+code,'Example City,'+code):
                self.assertEqual(d.normalize_location_query(query),('', 'Example City',code))
            self.assertEqual(d.normalize_location_query(state=name),('','',code))

    def test_company_person_queries_and_conflicting_filters(self):
        for q in ('Hill Country Sweeps','James Laut','New Jersey Chimney Service','Lords Chimney'):
            self.assertEqual(d.normalize_location_query(q),(q,'',''))
        for args in (dict(q='New Jersey',state='TX'),dict(state='not a state'),dict(q='Newark NJ',city='Austin')):
            with self.assertRaises(ValueError):d.normalize_location_query(**args)

    def test_browser_and_server_state_names_stay_in_sync(self):
        js=(ROOT/'assets/directory-search.js').read_text()
        names=re.search(r"Object.fromEntries\(\('([^']+)'\)",js).group(1)
        self.assertEqual(dict(pair.split(':') for pair in names.split('|')),d.US_STATES)

    def test_each_state_excludes_other_states_even_when_text_and_trust_match(self):
        for code,name in d.US_STATES.items():
            other='TX' if code!='TX' else 'NJ'
            records=[{'id':'local','company':'Local Company','state':code,'city':'Example'},
                     {'id':'wrong','company':name+' Highly Ranked Sweep','state':other,'city':'Other','service_areas':['New Caney','Jersey Village']},
                     {'id':'serves','company':'Cross Border Service','state':other,'service_locations':[{'city':'Example','state':name,'evidence_status':'active'}]}]
            with patch.object(d,'static_company_records',return_value=records),patch.object(d,'national_company_records',return_value=[]),patch.object(d,'static_records',return_value=[]):
                for query in (name,code):
                    rows=d.search_static_companies(q=query)
                    self.assertEqual({r['id'] for r in rows},{'local','serves'},query)

    def test_city_and_state_must_match_same_location_not_different_rows(self):
        records=[{'id':'wrong','company':'Example','city':'Springfield','state':'TX','service_locations':[{'city':'Newark','state':'NJ'}]},
                 {'id':'right','company':'Right','city':'Springfield','state':'NJ'}]
        with patch.object(d,'static_company_records',return_value=records),patch.object(d,'national_company_records',return_value=[]),patch.object(d,'static_records',return_value=[]):
            self.assertEqual([r['id'] for r in d.search_static_companies(q='Springfield, New Jersey')],['right'])

    def test_real_data_new_jersey_does_not_match_texas_new_and_jersey_village(self):
        rows=d.search_static_companies(q='New Jersey')
        self.assertTrue(rows)
        self.assertFalse(any(r['company']=='Lords Chimney' for r in rows))
        for row in rows:
            self.assertTrue(d.normalize_state(row.get('state'))=='NJ' or any(d.normalize_state(a.get('state'))=='NJ' for a in row.get('service_locations',[])))
        self.assertEqual({r['id'] for r in rows},{r['id'] for r in d.search_static_companies(state='NJ')})

    def test_real_data_every_state_has_only_geographic_matches(self):
        for code,name in d.US_STATES.items():
            for row in d.search_static_companies(q=name):
                self.assertTrue(d.normalize_state(row.get('state'))==code or any(d.normalize_state(a.get('state'))==code for a in row.get('service_locations',[])),(name,row['company']))

    def test_database_query_uses_state_constraint_not_text_search(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
        with patch.object(d,'dbconn',return_value=conn),patch.object(d,'ensure'),patch.object(d,'search_static_companies',return_value=[]):
            d.search_companies_db(q='New Jersey')
        sql,params=cur.execute.call_args.args
        self.assertIn('UPPER(TRIM(c.state))=ANY(%s)',sql)
        self.assertIn('UPPER(TRIM(sa.state))=ANY(%s)',sql)
        self.assertIn("sa.evidence_status='active'",sql)
        self.assertNotIn('c.canonical_name ILIKE',sql)
        self.assertEqual(params[-2:],[['NJ','NEW JERSEY'],['NJ','NEW JERSEY']])

    def test_city_state_database_predicate_is_paired(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
        with patch.object(d,'dbconn',return_value=conn),patch.object(d,'ensure'),patch.object(d,'search_static_companies',return_value=[]):
            d.search_companies_db(q='Springfield, NJ')
        sql,params=cur.execute.call_args.args
        self.assertIn('LOWER(TRIM(sa.city))=LOWER(%s) AND UPPER(TRIM(sa.state))=ANY(%s)',sql)
        self.assertEqual(params[-4:],['Springfield',['NJ','NEW JERSEY'],'Springfield',['NJ','NEW JERSEY']])

    def test_missing_location_does_not_fall_back_to_nationwide(self):
        with patch.object(d,'dbconn',return_value=None):
            self.assertEqual(d.search_companies_db(city='No Such City',state='NJ')[0],[])

    def test_verified_professional_trust_outweighs_unverified_relevance(self):
        verified = {
            'company': 'Verified Sweep', 'match_rank': 5, 'distance': 40,
            'reviewed_professionals': [{
                'holder': 'Alex', 'display_status': 'CREDENTIAL VERIFIED',
                'identity_status': 'VERIFIED', 'company_affiliation_status': 'VERIFIED',
            }],
        }
        unverified = {
            'company': 'Exact Unverified Sweep', 'match_rank': 0, 'distance': 2,
            'reviewed_professionals': [],
        }
        self.assertLess(d.company_trust_key(verified), d.company_trust_key(unverified))

    def test_legacy_professional_search_keeps_state_when_database_unavailable(self):
        person={'holder':'Test','company':'New Jersey Named Company','verification_status':'verified_from_official_source','verified_at':'2026-01-01','recheck_due_at':'2099-01-01'}
        with patch.object(d,'dbconn',return_value=None),patch.object(d,'static_records',return_value=[{**person,'id':'nj','state':'NJ'},{**person,'id':'tx','state':'TX'}]):
            self.assertEqual([r['id'] for r in d.search_db('',q='New Jersey')[0]],['nj'])
