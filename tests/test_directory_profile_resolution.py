import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock,patch

spec=importlib.util.spec_from_file_location('profile_resolution',Path(__file__).resolve().parents[1]/'api/directory.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class ProfileResolutionTests(TestCase):
    def test_numeric_company_profile_is_queried_directly(self):
        with patch.object(d,'search_companies_db',return_value=([{'id':9999,'company':'Last Company'}],True)) as search,patch.object(d,'company_professionals',return_value=[]):
            result,connected=d.detail_company('9999')
        search.assert_called_once_with(company_id=9999)
        self.assertEqual(result['id'],9999);self.assertTrue(connected)

    def test_out_of_range_and_invalid_ids_do_not_query(self):
        with patch.object(d,'search_companies_db') as query:
            for value in ['9223372036854775808','../../other','x?y']:
                self.assertEqual(d.detail_company(value),(None,False))
        query.assert_not_called()

    def test_static_aliases_remain_addressable_without_database_search_cap(self):
        sources=[{'id':'first','company':'Example','website':'https://example.test','state':'TX'}, {'id':'second','company':'Example','website':'https://example.test','state':'TX'}]
        with patch.object(d,'static_company_records',return_value=sources),patch.object(d,'national_company_records',return_value=[]),patch.object(d,'static_records',return_value=[]),patch.object(d,'search_companies_db') as query:
            result,_=d.detail_company('second')
        query.assert_not_called();self.assertEqual(result['id'],'first');self.assertIn('second',result['record_aliases'])

    def test_company_id_query_keeps_public_status_guard_and_parameters(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
        with patch.object(d,'dbconn',return_value=conn),patch.object(d,'ensure'),patch.object(d,'search_static_companies',return_value=[]):
            result,_=d.search_companies_db(company_id=9999)
        sql,params=cur.execute.call_args.args
        self.assertIn('c.public_status=ANY(%s)',sql);self.assertIn('c.id=%s',sql);self.assertEqual(params[-1],9999);self.assertEqual(result,[])

    def test_numeric_profile_enriches_service_evidence_without_overwriting_status(self):
        static={'id':'static-example','company':'Example','website':'https://example.test','service_area_labels':['Austin, TX'],'source_url':'https://example.test/areas','public_status':'verified'}
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[(9999,'Example','https://example.test','', 'Spring Branch','TX','78070','unverified','unclaimed',None,None)]
        with patch.object(d,'dbconn',return_value=conn),patch.object(d,'ensure'),patch.object(d,'search_static_companies',return_value=[static]),patch.object(d,'reviewed_professionals_for_company',return_value=[]):
            rows,_=d.search_companies_db(company_id=9999)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['service_area_labels'],['Austin, TX']);self.assertEqual(rows[0]['public_status'],'unverified')

    def test_ambiguous_company_name_does_not_create_a_direct_link(self):
        with patch.object(d,'search_static_companies',return_value=[{'id':'a','company':'Same Company'},{'id':'b','company':'Same Company'}]):
            self.assertIsNone(d.listed_company_record_id({'company':'Same Company','state':'TX'}))

    def test_clear_company_match_links_without_changing_affiliation(self):
        person={'holder':'Test','company':'Example','state':'TX','company_affiliation_status':'UNKNOWN'}
        with patch.object(d,'search_static_companies',return_value=[{'id':'example','company':'Example'}]):
            self.assertEqual(d.listed_company_record_id(person),'example')
        self.assertEqual(person['company_affiliation_status'],'UNKNOWN')
