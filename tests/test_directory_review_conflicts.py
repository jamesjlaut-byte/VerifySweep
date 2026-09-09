import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock,Mock,patch

spec=importlib.util.spec_from_file_location('review_conflicts',Path(__file__).resolve().parents[1]/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)

class ReviewConflictTests(unittest.TestCase):
    def test_all_review_types_reject_stale_or_missing_versions_without_writes(self):
        cases=[(directory.review_profile_claim_db,('pending','company','example','124')),
               (directory.review_report_db,('pending','124')),
               (directory.review_credential_submission_db,('pending','verification_needed','124'))]
        for method,row in cases:
            for expected,error in [('123',directory.ReviewConflict),(None,ValueError)]:
                with self.subTest(method=method.__name__,expected=expected):
                    conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchone.return_value=row
                    with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
                        with self.assertRaises(error):method(1,'reviewing','Reviewer','Review note',expected)
                    self.assertEqual(cur.execute.call_count,1)
                    self.assertIn('FOR UPDATE',cur.execute.call_args.args[0]);conn.commit.assert_not_called();conn.close.assert_called_once()

    def test_current_version_allows_review_and_audit_commit(self):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;cur.fetchone.return_value=('pending','124')
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
            result=directory.review_report_db(1,'reviewing','Reviewer','Review note','124')
        self.assertEqual(result['review_status'],'reviewing');self.assertEqual(cur.execute.call_count,3);conn.commit.assert_called_once()

    def test_http_conflict_returns_409(self):
        payload={'action':'review_report','report_id':1,'status':'reviewing','review_note':'Review note','review_version':'123'}
        body=json.dumps(payload).encode();h=object.__new__(directory.handler);h.headers={'Content-Length':str(len(body))};h.rfile=io.BytesIO(body);h.sendj=Mock()
        with patch.object(directory,'admin_authorized',return_value=True),patch.object(directory,'review_report_db',side_effect=directory.ReviewConflict('Refresh first')) as review:h.do_POST()
        self.assertEqual(h.sendj.call_args.args[0],409);self.assertEqual(h.sendj.call_args.args[1]['code'],'review_conflict')
        self.assertEqual(review.call_args.args[-1],'123')

    def test_no_version_bypass(self):
        for value in ['',None,{},'123x',123]:
            with self.assertRaises(ValueError):directory.require_review_version(value,'123')
