import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('review_directory',ROOT/'api/directory.py')
directory=importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)

class ReviewAccessTests(unittest.TestCase):
    def test_queues_reject_unauthorized_read_before_database_access(self):
        for view,method in [('admin_claims','list_profile_claims_db'),('admin_reports','list_reports_db'),('admin_submissions','list_pending_submissions_db'),('admin_reverification','list_reverification_queue_db')]:
            with self.subTest(view=view):
                h=object.__new__(directory.handler);h.path='/api/directory?view='+view;h.headers={};h.sendj=Mock()
                with patch.object(directory,'admin_authorized',return_value=False),patch.object(directory,method) as read:
                    h.do_GET()
                self.assertEqual(h.sendj.call_args.args[0],403);read.assert_not_called()

    def test_review_actions_reject_unauthorized_writes(self):
        for action in ['review_report','review_profile_claim','review_credential_submission']:
            h=object.__new__(directory.handler);body=json.dumps({'action':action}).encode();h.headers={'Content-Length':str(len(body))};h.rfile=io.BytesIO(body);h.sendj=Mock()
            with patch.object(directory,'admin_authorized',return_value=False):h.do_POST()
            self.assertEqual(h.sendj.call_args.args[0],403)

    def test_admin_page_has_no_indexing_or_credential_persistence(self):
        html=(ROOT/'directory-review.html').read_text();js=(ROOT/'assets/directory-review.js').read_text()
        self.assertIn('noindex,nofollow',html);self.assertIn("connect-src 'self'",html)
        for unsafe in ['localStorage','sessionStorage','innerHTML','verify_credential_submission']:
            self.assertNotIn(unsafe,js)
        self.assertIn("redirect:'error'",js)
        self.assertNotIn('directory-review.html',(ROOT/'sitemap.xml').read_text())
