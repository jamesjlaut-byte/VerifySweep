import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock,Mock,patch

spec=importlib.util.spec_from_file_location('review_paging',Path(__file__).resolve().parents[1]/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)

class ReviewPagingTests(unittest.TestCase):
    def test_reverification_pages_distinguish_overlapping_source_ids(self):
        rows=[{'source_record':'legacy','credential_id':str(n)} for n in range(1,251)]+[{'source_record':'normalized','credential_id':'1'}]
        page=directory.reverification_page(rows)
        self.assertEqual(page['count'],250)
        self.assertEqual(page['next_cursor'],'legacy:250')
        self.assertEqual(directory.reverification_cursor(page['next_cursor']),('legacy',250))
        self.assertIsNone(directory.reverification_page(rows[250:])['next_cursor'])
        self.assertIsNone(directory.reverification_page([])['next_cursor'])

    def test_reverification_cursor_validation_auth_and_forwarding(self):
        for cursor,authorized,expected in [('legacy:5',True,200),('normalized:5',True,200),('0',True,200),('legacy:0',True,400),('other:1',True,400),('legacy:9223372036854775808',True,400),('bad',False,403)]:
            h=object.__new__(directory.handler);h.path='/api/directory?view=admin_reverification&after='+cursor;h.headers={};h.sendj=Mock()
            with patch.object(directory,'admin_authorized',return_value=authorized),patch.object(directory,'list_reverification_queue_db',return_value=[]) as query:h.do_GET()
            self.assertEqual(h.sendj.call_args.args[0],expected)
            if expected==200:query.assert_called_once_with(cursor)
            else:query.assert_not_called()

    def test_reverification_sql_uses_composite_key_not_offset(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
            directory.list_reverification_queue_db('normalized:42')
        sql,params=cur.execute.call_args.args
        self.assertIn('WHERE (source_record,credential_id::bigint)>(%s,%s)',sql)
        self.assertIn('ORDER BY source_record,credential_id::bigint',sql)
        self.assertIn('LIMIT 251',sql);self.assertNotIn('OFFSET',sql)
        self.assertEqual(params,('normalized',42))

    def test_page_lookahead_does_not_drop_next_record(self):
        rows=[{'id':n} for n in range(1,202)]
        page=directory.review_page(rows,'claims','pending',200)
        self.assertEqual(page['count'],200);self.assertEqual(page['next_cursor'],'200')
        self.assertEqual(page['claims'][-1]['id'],200)
        self.assertIsNone(directory.review_page(rows[:200],'claims','pending',200)['next_cursor'])
        self.assertIsNone(directory.review_page([],'claims','pending',200)['next_cursor'])

    def test_cursor_rejected_before_query_and_requires_auth(self):
        for authorized, cursor, expected in [(True,'-1',400),(True,'abc',400),(True,'9223372036854775808',400),(False,'abc',403)]:
            h=object.__new__(directory.handler);h.path='/api/directory?view=admin_claims&after='+cursor;h.headers={};h.sendj=Mock()
            with patch.object(directory,'admin_authorized',return_value=authorized),patch.object(directory,'list_profile_claims_db') as query:h.do_GET()
            self.assertEqual(h.sendj.call_args.args[0],expected);query.assert_not_called()

    def test_cursor_is_forwarded_to_queue_query(self):
        h=object.__new__(directory.handler);h.path='/api/directory?view=admin_claims&after=200';h.headers={};h.sendj=Mock()
        with patch.object(directory,'admin_authorized',return_value=True),patch.object(directory,'list_profile_claims_db',return_value=[{'id':201}]) as query:h.do_GET()
        query.assert_called_once_with('pending',200)
        self.assertEqual(h.sendj.call_args.args[1]['claims'],[{'id':201}])

    def test_queue_sql_uses_stable_id_cursor_and_parameterized_values(self):
        for method in [directory.list_profile_claims_db,directory.list_reports_db,directory.list_pending_submissions_db]:
            conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchall.return_value=[]
            with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):method('pending',42)
            sql,params=cur.execute.call_args.args
            self.assertIn('id>%s ORDER BY id ASC',sql);self.assertEqual(params,('pending',42))
