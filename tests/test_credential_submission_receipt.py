import importlib.util,io,json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
spec=importlib.util.spec_from_file_location('credential_receipt',Path(__file__).resolve().parents[1]/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)

class CredentialSubmissionTests(unittest.TestCase):
    def request(self,changes=None,failure=None):
        payload={'company':'Test Company','professional_name':'Test Person','credential':'Test credential','issuer':'Other','credential_source':'https://example.com/evidence','postal_code':'78701','submitter_email':'test@example.com'}
        payload.update(changes or {});body=json.dumps(payload).encode();h=object.__new__(directory.handler);h.headers={'Content-Length':str(len(body))};h.rfile=io.BytesIO(body);h.sendj=Mock()
        with patch.object(directory,'submit_db',return_value=42,side_effect=failure) as save:h.do_POST()
        return h.sendj.call_args.args,save.call_count

    def test_invalid_dates_and_zip_rejected_without_storage(self):
        for changes in [{'postal_code':'787011'},{'expiration_date':'2026-02-30'},{'expiration_date':'2026-09-09extra'},{'expiration_date':'2025-02-29'}]:
            with self.subTest(changes=changes):
                (code,_),calls=self.request(changes);self.assertEqual((code,calls),(400,0))

    def test_real_leap_date_and_blank_date_are_accepted_for_review_only(self):
        for value in ['2028-02-29','']:
            (code,data),calls=self.request({'expiration_date':value});self.assertEqual((code,calls),(201,1));self.assertEqual(data['status'],'pending');self.assertEqual(data['submission_reference'],'VS-CREDENTIAL-42');self.assertEqual(data['email_notification'],'not_enabled')

    def test_storage_failure_never_returns_receipt(self):
        (code,data),_=self.request(failure=RuntimeError('Database unavailable'))
        self.assertEqual(code,503);self.assertNotIn('submission_reference',data)
