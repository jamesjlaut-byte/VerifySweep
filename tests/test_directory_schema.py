import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('directory_api', ROOT / 'api' / 'directory.py')
DIRECTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIRECTORY)


class RecordingCursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement, params=None):
        self.statements.append((' '.join(statement.split()), params))


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True


class DirectorySchemaTests(unittest.TestCase):
    def test_normalized_schema_is_created_without_removing_legacy_table(self):
        connection = RecordingConnection()
        DIRECTORY.ensure(connection)
        sql = '\n'.join(statement for statement, _ in connection.cursor_instance.statements)

        self.assertTrue(connection.committed)
        self.assertIn('CREATE TABLE IF NOT EXISTS pro_directory', sql)
        for table in (
            'directory_companies',
            'directory_professionals',
            'directory_credentials',
            'directory_company_sources',
            'directory_claims',
            'directory_verification_events',
            'directory_service_areas',
            'directory_audit_log',
        ):
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', sql)

    def test_status_constraints_keep_claim_and_verification_separate(self):
        sql = '\n'.join(DIRECTORY.NORMALIZED_DIRECTORY_SCHEMA)
        self.assertIn("claim_status IN ('unclaimed','claim_pending','claimed')", sql)
        self.assertIn("public_status IN ('unverified','verification_in_progress','verified'", sql)
        self.assertIn("verification_status IN ('verification_needed','verification_in_progress','verified_from_official_source'", sql)
        self.assertNotIn("claim_status IN ('verified'", sql)

    def test_review_and_audit_events_are_append_only(self):
        sql = '\n'.join(DIRECTORY.NORMALIZED_DIRECTORY_SCHEMA)
        self.assertIn('directory_verification_events_immutable', sql)
        self.assertIn('directory_audit_log_immutable', sql)
        self.assertIn('BEFORE UPDATE OR DELETE', sql)

    def test_company_status_labels_are_neutral(self):
        self.assertEqual(DIRECTORY.company_status_label('unverified'), 'UNVERIFIED')
        self.assertEqual(DIRECTORY.company_status_label('verification_in_progress'), 'VERIFICATION IN PROGRESS')
        self.assertEqual(DIRECTORY.company_status_label('information_updated'), 'INFORMATION UPDATED / VERIFICATION NEEDED')
        self.assertNotIn('fraud', ' '.join(DIRECTORY.COMPANY_STATUS_LABELS.values()).lower())

    def test_only_publishable_company_states_are_searchable(self):
        self.assertIn('unverified', DIRECTORY.PUBLIC_COMPANY_STATUSES)
        self.assertIn('verified', DIRECTORY.PUBLIC_COMPANY_STATUSES)
        self.assertNotIn('removed', DIRECTORY.PUBLIC_COMPANY_STATUSES)
        self.assertNotIn('not_eligible', DIRECTORY.PUBLIC_COMPANY_STATUSES)

    def test_static_company_projection_does_not_inherit_credential_verification(self):
        rows = DIRECTORY.search_static_companies(q='Wolfman')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['company'], 'Wolfman Chimney & Fireplace')
        self.assertEqual(rows[0]['public_status'], 'unverified')
        self.assertEqual(rows[0]['display_status'], 'UNVERIFIED')
        self.assertEqual(rows[0]['claim_status'], 'unclaimed')
        for private_or_individual_field in ('holder', 'credential', 'source', 'address_line1'):
            self.assertNotIn(private_or_individual_field, rows[0])

    def test_static_company_projection_supports_location_search(self):
        self.assertEqual(len(DIRECTORY.search_static_companies(city='New Braunfels',state='TX')), 1)
        self.assertEqual(len(DIRECTORY.search_static_companies(zipcode='78070')), 1)
        self.assertEqual(DIRECTORY.search_static_companies(zipcode='00000'), [])


if __name__ == '__main__':
    unittest.main()
