import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('claim_directory', ROOT / 'api/directory.py')
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


class ClaimReceiptTests(unittest.TestCase):
    def request(self, failure=None):
        payload = {'action':'claim_profile', 'target_type':'professional', 'target_id':'18867',
                   'claimant_name':'Test Claimant', 'claimant_email':'test@example.com',
                   'details':'Test connection to this profile.'}
        body = json.dumps(payload).encode()
        handler = object.__new__(directory.handler)
        handler.headers = {'Content-Length':str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.sendj = Mock()
        with patch.object(directory, 'directory_target_exists', return_value=True), \
             patch.object(directory, 'submit_profile_claim_db', return_value=123, side_effect=failure), \
             patch('builtins.print'):
            handler.do_POST()
        return handler.sendj.call_args.args

    def test_saved_claim_returns_reference_and_honest_email_status(self):
        code, data = self.request()
        self.assertEqual(code, 201)
        self.assertEqual(data['claim_reference'], 'VS-CLAIM-123')
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['email_notification'], 'not_enabled')
        self.assertNotIn('claimant_email', data)

    def test_storage_failure_does_not_return_receipt(self):
        code, data = self.request(RuntimeError('Directory database is not configured.'))
        self.assertEqual(code, 503)
        self.assertNotIn('claim_reference', data)


if __name__ == '__main__':
    unittest.main()
