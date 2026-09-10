import importlib.util
from pathlib import Path
from unittest import TestCase

spec=importlib.util.spec_from_file_location('quality_audit',Path(__file__).resolve().parents[1]/'scripts/audit_directory_quality.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class QualityAuditTests(TestCase):
    def test_inventory_is_neutral_and_does_not_publish_private_fields(self):
        record={'id':'sample','holder':'Person','company':'Company','issuer':'NFI','source':'https://www.nficertified.org/public/','verification_status':'verified_from_official_source','verified_at':'2026-01-01','recheck_due_at':'2099-01-01','submitter_email_private':'private@example.test','notes_internal':'Private notes'}
        report=audit.audit([record],[{'id':'c','company':'Company'}])
        self.assertEqual(report['stored_current_verified_credentials_by_issuer'],{'NFI':1})
        self.assertEqual(report['company_records_without_documented_service_areas'],1)
        self.assertEqual(report['findings'][0]['review_reasons'],['EXPIRATION_NOT_DOCUMENTED'])
        self.assertNotIn('private@example.test',str(report));self.assertNotIn('Private notes',str(report))
        self.assertNotIn('display_status',record)

    def test_duplicate_ids_and_invalid_source_are_review_tasks(self):
        rows=[{'id':'duplicate','source':'javascript:bad'}]*2
        report=audit.audit(rows,[])
        for finding in report['findings']:
            self.assertIn('MISSING_OR_DUPLICATE_RECORD_ID',finding['review_reasons'])
            self.assertIn('OFFICIAL_SOURCE_REVIEW_NEEDED',finding['review_reasons'])
        self.assertEqual(report['professionals_with_stored_current_verified_credentials'],0)
