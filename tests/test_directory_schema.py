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
        new_braunfels = DIRECTORY.search_static_companies(city='New Braunfels',state='TX')
        self.assertEqual({row['company'] for row in new_braunfels}, {
            'Hill Country Air Duct And Chimney Sweeps LLC',
            'Wolfman Chimney & Fireplace',
        })
        self.assertEqual(len(DIRECTORY.search_static_companies(zipcode='78070')), 1)
        self.assertEqual(DIRECTORY.search_static_companies(zipcode='00000'), [])

    def test_independent_company_records_make_austin_searchable(self):
        rows = DIRECTORY.search_static_companies(q='Austin, TX')
        self.assertGreaterEqual(len(rows), 7)
        self.assertTrue(all(row['state'] == 'TX' for row in rows))
        self.assertTrue(any(row['company'].startswith('Hill Country') for row in rows))
        self.assertTrue(all(row['display_status'] == 'UNVERIFIED' for row in rows))
        self.assertTrue(all(row.get('source_url') for row in rows))

    def test_company_discovery_does_not_create_professional_credentials(self):
        company = DIRECTORY.search_static_companies(q='Absolute Chimney')[0]
        self.assertEqual(DIRECTORY.company_professionals(company), [])

    def test_company_professionals_remain_named_individual_records(self):
        company = DIRECTORY.search_static_companies(q='Wolfman')[0]
        rows = DIRECTORY.company_professionals(company)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.get('holder') for row in rows))
        self.assertTrue(all(row['display_status'] == 'VERIFIED FROM OFFICIAL SOURCE' for row in rows))
        self.assertEqual(company['display_status'], 'UNVERIFIED')

    def test_hill_country_matches_published_service_areas(self):
        rows = DIRECTORY.search_static_companies(city='Austin', state='TX')
        hill_country = next(row for row in rows if row['company'].startswith('Hill Country'))
        self.assertEqual(hill_country['city'], 'Spring Branch')
        self.assertEqual(hill_country['matched_service_area'], 'Austin')
        self.assertIn('San Antonio', hill_country['service_areas'])
        self.assertEqual(hill_country['display_status'], 'UNVERIFIED')

    def test_black_velvet_service_area_and_named_credential_stay_separate(self):
        rows = DIRECTORY.search_static_companies(city='Fort Worth', state='TX')
        black_velvet = next(row for row in rows if row['company'] == 'Black Velvet Chimney')
        self.assertEqual(black_velvet['matched_service_area'], 'Fort Worth')
        self.assertIn('more than 40 years', black_velvet['history_note'])
        professionals = DIRECTORY.company_professionals(black_velvet)
        self.assertEqual([person['holder'] for person in professionals], ['Pete Pohlman'])
        self.assertEqual(professionals[0]['display_status'], 'VERIFIED FROM OFFICIAL SOURCE')
        self.assertEqual(black_velvet['display_status'], 'UNVERIFIED')

    def test_free_text_location_search_includes_service_areas(self):
        rows = DIRECTORY.search_static_companies(q='Cedar Park TX')
        self.assertTrue(any(row['company'].startswith('Hill Country') for row in rows))

    def test_wolfman_matches_published_austin_service_area(self):
        rows = DIRECTORY.search_static_companies(city='Austin', state='TX')
        wolfman = next(row for row in rows if row['company'] == 'Wolfman Chimney & Fireplace')
        self.assertEqual(wolfman['city'], 'New Braunfels')
        self.assertEqual(wolfman['matched_service_area'], 'Austin')
        self.assertIn('Bastrop', wolfman['service_areas'])
        self.assertEqual(len(DIRECTORY.company_professionals(wolfman)), 2)

    def test_top_hat_and_ables_are_searchable_across_published_areas(self):
        hutto = DIRECTORY.search_static_companies(city='Hutto', state='TX')
        self.assertTrue(any(row['company'] == 'Top Hat Chimney Sweeps' for row in hutto))
        temple = DIRECTORY.search_static_companies(city='Temple', state='TX')
        self.assertTrue(any(row['company'] == 'Ables Top Hat Home Services' for row in temple))
        austin = {row['company'] for row in DIRECTORY.search_static_companies(city='Austin', state='TX')}
        self.assertIn('Top Hat Chimney Sweeps', austin)
        self.assertIn('Ables Top Hat Home Services', austin)


if __name__ == '__main__':
    unittest.main()
