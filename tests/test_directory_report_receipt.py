import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('report_directory', Path(__file__).resolve().parents[1] / 'api/directory.py')
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


class ReportReceiptTests(unittest.TestCase):
    def request(self, changes=None, exists=True, failure=None):
        payload = {'action': 'report_problem', 'target_type': 'company', 'target_id': 'example',
                   'reason': 'wrong_phone', 'details': 'Please review the listed phone number.'}
        if changes is not None:
            if isinstance(changes, dict): payload.update(changes)
            else: payload = changes
        body = json.dumps(payload).encode()
        handler = object.__new__(directory.handler)
        handler.headers = {'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.sendj = Mock()
        with patch.object(directory, 'directory_target_exists', return_value=exists), patch.object(directory, 'report_problem_db', return_value=42, side_effect=failure) as save:
            handler.do_POST()
        return handler.sendj.call_args.args, save.call_count

    def test_receipt_requires_saved_report(self):
        (code, data), count = self.request()
        self.assertEqual(code, 201)
        self.assertEqual(count, 1)
        self.assertEqual(data['report_reference'], 'VS-REPORT-42')
        self.assertEqual(data['email_notification'], 'not_enabled')
        self.assertNotIn('reporter_email', data)

    def test_missing_record_is_not_saved(self):
        (code, _), count = self.request(exists=False)
        self.assertEqual((code, count), (400, 0))

    def test_invalid_email_is_not_saved(self):
        (code, _), count = self.request({'reporter_email': 'not-an-email'})
        self.assertEqual((code, count), (400, 0))

    def test_storage_failure_is_not_success(self):
        (code, data), _ = self.request(failure=RuntimeError('Directory database is not configured.'))
        self.assertEqual(code, 503)
        self.assertNotIn('report_reference', data)

    def test_non_object_json_is_bad_request(self):
        (code, _), count = self.request(changes=[])
        self.assertEqual((code, count), (400, 0))
