import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('review_integrity',ROOT/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)

class ReviewIntegrityTests(unittest.TestCase):
    def connection(self,row):
        connection=MagicMock();cursor=connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value=(*row,'123') if row else row
        return connection,cursor

    def test_triage_cannot_demote_verified_records(self):
        for row in [('verified','verification_needed'),('pending','verified_from_official_source')]:
            with self.subTest(row=row):
                conn,cur=self.connection(row)
                with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
                    with self.assertRaisesRegex(ValueError,'separate credential correction'):
                        directory.review_credential_submission_db(1,'rejected','Reviewer','Test note','123')
                self.assertEqual(cur.execute.call_count,1)
                conn.commit.assert_not_called();conn.close.assert_called_once()

    def test_triage_preserves_actual_verification_state_in_response_and_audit(self):
        conn,cur=self.connection(('pending','verification_in_progress'))
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
            result=directory.review_credential_submission_db(1,'needs_evidence','Reviewer','Request more evidence','123')
        self.assertEqual(result['verification_status'],'verification_in_progress')
        params=cur.execute.call_args.args[1]
        before,after=json.loads(params[2]),json.loads(params[3])
        self.assertEqual(before['verification_status'],after['verification_status'])
        self.assertEqual(after['status'],'needs_evidence');conn.commit.assert_called_once()

    def test_legacy_reverification_sql_checks_expiration(self):
        conn,cur=self.connection(None);cur.fetchall.return_value=[]
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
            directory.list_reverification_queue_db()
        sql=cur.execute.call_args.args[0].split('UNION ALL')[1]
        self.assertIn('expiration_date<CURRENT_DATE',sql)
        self.assertIn("THEN 'EXPIRED'",sql)
        self.assertNotIn('NULL::date',sql)
