import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock,Mock,patch

spec=importlib.util.spec_from_file_location('review_paging',Path(__file__).resolve().parents[1]/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)

class ReviewPagingTests(unittest.TestCase):
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
