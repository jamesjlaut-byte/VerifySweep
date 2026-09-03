import importlib.util
import pathlib
import unittest
from unittest.mock import patch


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
            'directory_credential_types',
            'directory_credentials',
            'directory_affiliations',
            'directory_sources',
            'directory_verification_records',
            'directory_evidence',
            'directory_profile_claim_requests',
            'directory_legacy_migration_map',
            'directory_company_sources',
            'directory_claims',
            'directory_verification_events',
            'directory_service_areas',
            'directory_audit_log',
        ):
            self.assertIn(f'CREATE TABLE IF NOT EXISTS {table}', sql)

        self.assertNotIn('DROP TABLE', sql.upper())
        self.assertNotIn('TRUNCATE', sql.upper())

    def test_phase_one_models_keep_person_company_credential_and_affiliation_separate(self):
        sql='\n'.join(DIRECTORY.NORMALIZED_DIRECTORY_SCHEMA)
        for field in ('first_name','middle_name','last_name','display_name','profile_photo_url','phone_public','email_public','last_reviewed_at'):
            self.assertIn(field,sql)
        for field in ('legal_business_name','business_information_status','claim_status'):
            self.assertIn(field,sql)
        for field in ('professional_id','company_id','relationship_type','verification_method','verification_source_url','is_current'):
            self.assertIn(field,sql)
        self.assertIn("status IN ('verified','self_reported','pending','unable_to_verify','disputed','former')",sql)
        self.assertIn('directory_affiliations_identity_idx',sql)

    def test_credential_foundation_supports_types_expiration_and_granular_status(self):
        sql='\n'.join(DIRECTORY.NORMALIZED_DIRECTORY_SCHEMA)
        self.assertIn('UNIQUE (issuer,name)',sql)
        self.assertIn('credential_type_id',sql)
        self.assertIn('credential_number',sql)
        self.assertIn('issued_date',sql)
        self.assertIn('expiration_date',sql)
        for status in ('verified','self_reported','pending_verification','expired','reverification_required','unable_to_verify','disputed','archived'):
            self.assertIn(status,sql)

    def test_verification_evidence_and_migration_foundations_preserve_provenance(self):
        sql='\n'.join(DIRECTORY.NORMALIZED_DIRECTORY_SCHEMA)
        for field in ('subject_type','claim_type','claim_value','source_type','source_name','source_url','verified_by','expires_at','review_due_at','public_explanation','internal_notes'):
            self.assertIn(field,sql)
        self.assertIn("visibility IN ('private','public')",sql)
        self.assertIn("migration_status IN ('pending','migrated','ambiguous','skipped','error')",sql)
        self.assertIn("legacy_table TEXT NOT NULL DEFAULT 'pro_directory'",sql)

    def test_private_directory_fields_are_removed_from_public_projection(self):
        value={'display_name':'Example Person','notes_internal':'private','email_private':'private@example.test','credentials':[{'credential':'Example','admin_notes':'private'}]}
        public=DIRECTORY.public_directory_record(value)
        self.assertEqual(public,{'display_name':'Example Person','credentials':[{'credential':'Example'}]})

    def test_credential_expiration_and_reverification_are_not_permanent_verified_states(self):
        base={'verification_status':'verified_from_official_source','verified_at':'2026-01-01T00:00:00Z','source_available':True}
        self.assertEqual(DIRECTORY.static_status({**base,'expiration_date':'2000-01-01T00:00:00Z'})[0],'EXPIRED')
        self.assertEqual(DIRECTORY.static_status({**base,'recheck_due_at':'2000-01-01T00:00:00Z'})[0],'REVERIFICATION REQUIRED')
        self.assertEqual(DIRECTORY.static_status({**base,'self_reported':True})[0],'SELF-REPORTED')
        self.assertEqual(DIRECTORY.static_status({**base,'source_available':False})[0],'UNABLE TO VERIFY')

    def test_admin_authorization_fails_closed(self):
        with patch.dict(DIRECTORY.os.environ,{},clear=True):
            self.assertFalse(DIRECTORY.admin_authorized({'Authorization':'Bearer anything'}))
        with patch.dict(DIRECTORY.os.environ,{'DIRECTORY_ADMIN_TOKEN':'secret'},clear=True):
            self.assertFalse(DIRECTORY.admin_authorized({'Authorization':'Bearer wrong'}))
            self.assertTrue(DIRECTORY.admin_authorized({'Authorization':'Bearer secret'}))

    def test_report_review_requires_admin_and_writes_audit_history(self):
        source=(ROOT/'api'/'directory.py').read_text()
        self.assertIn("view=='admin_reports'",source)
        self.assertIn("clean(p.get('action'),40)=='review_report'",source)
        self.assertIn("'review_directory_report'",source)
        self.assertIn('Administrative authorization required.',source)
        self.assertIn('directory_reports ADD COLUMN IF NOT EXISTS review_note',source)

    def test_profile_claim_requests_stay_pending_and_private(self):
        sql='\n'.join(DIRECTORY.NORMALIZED_DIRECTORY_SCHEMA)
        source=(ROOT/'api'/'directory.py').read_text()
        self.assertIn('CREATE TABLE IF NOT EXISTS directory_profile_claim_requests',sql)
        self.assertIn("review_status TEXT NOT NULL DEFAULT 'pending'",sql)
        self.assertIn('claimant_email_private',sql)
        self.assertIn("clean(p.get('action'),40)=='claim_profile'",source)
        self.assertIn("view=='admin_claims'",source)
        self.assertIn('directory_target_exists',source)
        self.assertIn('Claiming a profile does not verify identity, affiliation, credentials, or the company.',source)

    def test_reverification_queue_is_private_and_covers_expiration_source_and_due_dates(self):
        source=(ROOT/'api'/'directory.py').read_text()
        self.assertIn("view=='admin_reverification'",source)
        self.assertIn('list_reverification_queue_db()',source)
        self.assertIn("cr.expiration_date<CURRENT_DATE",source)
        self.assertIn("cr.recheck_due_at<=now()",source)
        self.assertIn("cr.source_available=FALSE",source)

    def test_verified_company_filter_excludes_stale_or_unavailable_normalized_credentials(self):
        source=(ROOT/'api'/'directory.py').read_text()
        self.assertIn("cr.expiration_date IS NULL OR cr.expiration_date>=CURRENT_DATE",source)
        self.assertIn("cr.recheck_due_at IS NULL OR cr.recheck_due_at>now()",source)
        self.assertIn("cr.verified_at IS NOT NULL AND cr.source_available=TRUE",source)

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
        self.assertTrue({
            'Capitol Chimney + Fireplace Services',
            "Harky's Chimney & Home Services",
            'Hill Country Air Duct And Chimney Sweeps LLC',
            'Wolfman Chimney & Fireplace',
        }.issubset({row['company'] for row in new_braunfels}))
        spring_branch = DIRECTORY.search_static_companies(zipcode='78070')
        self.assertTrue(any(row['company'].startswith('Hill Country') for row in spring_branch))
        self.assertTrue(all(row.get('distance') is None or row['distance'] <= 25 for row in spring_branch))
        self.assertEqual(DIRECTORY.search_static_companies(zipcode='00000'), [])

    def test_independent_company_records_make_austin_searchable(self):
        rows = DIRECTORY.search_static_companies(q='Austin, TX')
        self.assertGreaterEqual(len(rows), 7)
        self.assertTrue(all(row['state'] == 'TX' for row in rows))
        self.assertTrue(any(row['company'].startswith('Hill Country') for row in rows))
        self.assertTrue(all(row['display_status'] in {'UNVERIFIED', 'BUSINESS IDENTITY VERIFIED'} for row in rows))
        self.assertTrue(all(row.get('source_url') or row.get('sources') for row in rows))

    def test_company_discovery_does_not_create_professional_credentials(self):
        company = DIRECTORY.search_static_companies(q='Absolute Chimney')[0]
        self.assertEqual(DIRECTORY.company_professionals(company), [])

    def test_company_professionals_remain_named_individual_records(self):
        company = DIRECTORY.search_static_companies(q='Wolfman')[0]
        rows = DIRECTORY.company_professionals(company)
        self.assertEqual({row['holder'] for row in rows}, {'Bill Reynolds', 'Jason Trevino', 'Jack Wachsmann'})
        self.assertTrue(all(row.get('holder') for row in rows))
        self.assertTrue(all(row['display_status'] == 'CREDENTIAL VERIFIED' for row in rows))
        self.assertEqual(company['display_status'], 'UNVERIFIED')

    def test_hill_country_matches_published_service_areas(self):
        rows = DIRECTORY.search_static_companies(city='Austin', state='TX')
        hill_country = next(row for row in rows if row['company'].startswith('Hill Country'))
        self.assertEqual(hill_country['city'], 'Spring Branch')
        self.assertEqual(hill_country['matched_service_area'], 'Austin')
        self.assertIn('San Antonio', hill_country['service_areas'])
        self.assertEqual(hill_country['display_status'], 'UNVERIFIED')
        self.assertEqual(hill_country['public_status'], 'unverified')
        self.assertFalse(hill_country.get('verification_scope'))

    def test_company_zip_search_honors_radius_and_reports_distance(self):
        ten_miles = DIRECTORY.search_static_companies(zipcode='78701', radius=10)
        fifty_miles = DIRECTORY.search_static_companies(zipcode='78701', radius=50)
        self.assertLess(len(ten_miles), len(fifty_miles))
        self.assertNotIn('Wolfman Chimney & Fireplace', {row['company'] for row in ten_miles})
        wolfman = next(row for row in fifty_miles if row['company'] == 'Wolfman Chimney & Fireplace')
        self.assertLessEqual(wolfman['distance'], 50)
        self.assertTrue(all(row['distance'] <= 50 for row in fifty_miles if row.get('distance') is not None))
        tiers = {}
        for row in fifty_miles:
            if row.get('distance') is None:
                continue
            tier = (row.get('verified_affiliation_count', 0), row.get('verified_professional_count', 0), row.get('match_rank'))
            tiers.setdefault(tier, []).append(row['distance'])
        self.assertTrue(all(values == sorted(values) for values in tiers.values()))

    def test_black_velvet_service_area_and_named_credential_stay_separate(self):
        rows = DIRECTORY.search_static_companies(city='Fort Worth', state='TX')
        black_velvet = next(row for row in rows if row['company'] == 'Black Velvet Chimney')
        self.assertEqual(black_velvet['matched_service_area'], 'Fort Worth')
        self.assertIn('more than 40 years', black_velvet['history_note'])
        professionals = DIRECTORY.company_professionals(black_velvet)
        self.assertEqual([person['holder'] for person in professionals], ['Pete Pohlman'])
        self.assertEqual(professionals[0]['display_status'], 'CREDENTIAL VERIFIED')
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
        self.assertEqual(
            {row['holder'] for row in DIRECTORY.company_professionals(wolfman)},
            {'Bill Reynolds', 'Jason Trevino', 'Jack Wachsmann'},
        )

    def test_top_hat_and_ables_are_searchable_across_published_areas(self):
        hutto = DIRECTORY.search_static_companies(city='Hutto', state='TX')
        self.assertTrue(any(row['company'] == 'Top Hat Chimney Sweeps' for row in hutto))
        temple = DIRECTORY.search_static_companies(city='Temple', state='TX')
        self.assertTrue(any(row['company'] == 'Ables Top Hat Home Services' for row in temple))
        austin = {row['company'] for row in DIRECTORY.search_static_companies(city='Austin', state='TX')}
        self.assertIn('Top Hat Chimney Sweeps', austin)
        self.assertIn('Ables Top Hat Home Services', austin)

    def test_existing_austin_records_gain_sourced_service_coverage(self):
        cedar_park = {row['company'] for row in DIRECTORY.search_static_companies(city='Cedar Park', state='TX')}
        self.assertIn('Absolute Chimney', cedar_park)
        self.assertIn("Harky's Chimney & Home Services", cedar_park)
        cibolo = {row['company'] for row in DIRECTORY.search_static_companies(city='Cibolo', state='TX')}
        self.assertIn('Capitol Chimney + Fireplace Services', cibolo)
        temple = {row['company'] for row in DIRECTORY.search_static_companies(city='Temple', state='TX')}
        self.assertIn('Santa Chimney Sweep', temple)

    def test_vague_surrounding_area_claim_does_not_create_guessed_cities(self):
        hammond = DIRECTORY.search_static_companies(q='Hammond Fireplace')
        self.assertEqual(hammond[0]['service_areas'], [])

    def test_multi_state_service_locations_filter_by_their_own_state(self):
        denver = DIRECTORY.search_static_companies(city='Denver', state='CO')
        self.assertTrue({"Anthony's Chimney Sweep", 'Masters Services'}.issubset({row['company'] for row in denver}))
        self.assertTrue(all(row.get('matched_service_state','CO') == 'CO' for row in denver))
        self.assertEqual(DIRECTORY.search_static_companies(city='Denver', state='TX'), [])
        lake_charles = DIRECTORY.search_static_companies(city='Lake Charles', state='LA')
        self.assertEqual([row['company'] for row in lake_charles], ['Lords Chimney'])

    def test_new_regional_companies_are_searchable_by_published_city(self):
        houston = {row['company'] for row in DIRECTORY.search_static_companies(city='Houston', state='TX')}
        self.assertIn('Lords Chimney', houston)
        longview = {row['company'] for row in DIRECTORY.search_static_companies(city='Longview', state='TX')}
        self.assertIn("Jason's Chimney Sweep", longview)
        boerne = {row['company'] for row in DIRECTORY.search_static_companies(city='Boerne', state='TX')}
        self.assertIn('Clean as a Whistle Chimney Sweep', boerne)

    def test_panhandle_and_waco_companies_are_searchable(self):
        canyon = {row['company'] for row in DIRECTORY.search_static_companies(city='Canyon', state='TX')}
        self.assertIn('West Texas Chimney & Venting Solutions', canyon)
        waco = {row['company'] for row in DIRECTORY.search_static_companies(city='Waco', state='TX')}
        self.assertIn('Blue Collar Chimney', waco)
        self.assertIn('Ables Top Hat Home Services', waco)

    def test_el_paso_company_owned_service_record_is_searchable_and_unverified(self):
        rows = DIRECTORY.search_static_companies(city='El Paso', state='TX')
        moy = next(row for row in rows if row['company'] == 'Moy Construction & Remodeling')
        self.assertEqual(moy['matched_service_area'], 'El Paso')
        self.assertEqual(moy['matched_service_state'], 'TX')
        self.assertEqual(moy['public_status'], 'unverified')
        self.assertEqual(moy['display_status'], 'UNVERIFIED')

    def test_new_major_market_records_are_searchable_and_unverified(self):
        markets = [
            ('New York', 'NY', 'Chimney Experts LLC'),
            ('Philadelphia', 'PA', 'Chimney Cricket, Inc.'),
            ('Indianapolis', 'IN', 'Clean Sweep 317'),
            ('Nashville', 'TN', 'TN Chimney Sweep Inspection & Repair of Nashville LLC'),
        ]
        for city, state, company in markets:
            rows = DIRECTORY.search_static_companies(city=city, state=state)
            record = next(row for row in rows if row['company'] == company)
            self.assertEqual(record['matched_service_area'], city)
            self.assertEqual(record['matched_service_state'], state)
            self.assertEqual(record['public_status'], 'unverified')
            self.assertEqual(record['display_status'], 'UNVERIFIED')

    def test_harkys_florida_locations_do_not_cross_match_texas(self):
        tampa = DIRECTORY.search_static_companies(city='Tampa', state='FL')
        self.assertIn("Harky's Chimney & Home Services",[row['company'] for row in tampa])
        self.assertEqual(next(row for row in tampa if row['company']=="Harky's Chimney & Home Services")['matched_service_state'], 'FL')
        self.assertEqual(DIRECTORY.search_static_companies(city='Tampa', state='TX'), [])

    def test_expanded_ables_published_service_areas_are_searchable(self):
        cameron = {row['company'] for row in DIRECTORY.search_static_companies(city='Cameron', state='TX')}
        self.assertIn('Ables Top Hat Home Services', cameron)

    def test_arizona_and_new_mexico_directory_expansion(self):
        phoenix = {row['company'] for row in DIRECTORY.search_static_companies(city='Phoenix', state='AZ')}
        self.assertIn('Arizona Chimney & Air Ducts', phoenix)
        albuquerque = {row['company'] for row in DIRECTORY.search_static_companies(city='Albuquerque', state='NM')}
        self.assertTrue({
            "Casey's Top Hat Chimney Sweeps",
            "Shawn's Chimney Sweep & Stove Company",
            'CBS Chimney Sweepers',
        }.issubset(albuquerque))
        taos = {row['company'] for row in DIRECTORY.search_static_companies(city='Taos', state='NM')}
        self.assertIn("Shawn's Chimney Sweep & Stove Company", taos)
        truth_or_consequences = DIRECTORY.search_static_companies(city='Truth or Consequences', state='NM')
        self.assertEqual([row['company'] for row in truth_or_consequences], ["Shawn's Chimney Sweep & Stove Company"])

    def test_new_state_records_do_not_cross_match_texas(self):
        self.assertEqual(DIRECTORY.search_static_companies(city='Phoenix', state='TX'), [])
        self.assertEqual(DIRECTORY.search_static_companies(city='Albuquerque', state='TX'), [])

    def test_colorado_and_missouri_directory_expansion(self):
        colorado_springs = {row['company'] for row in DIRECTORY.search_static_companies(city='Colorado Springs', state='CO')}
        self.assertIn("Anthony's Chimney Sweep", colorado_springs)
        st_louis = {row['company'] for row in DIRECTORY.search_static_companies(city='St. Louis', state='MO')}
        self.assertTrue({'Clean Sweep Chimney Service', 'English Sweep, Inc.', 'Friendly Fire LLC'}.issubset(st_louis))

    def test_illinois_service_locations_match_their_own_state(self):
        waterloo = DIRECTORY.search_static_companies(city='Waterloo', state='IL')
        self.assertEqual([row['company'] for row in waterloo], ['English Sweep, Inc.'])
        belleville = DIRECTORY.search_static_companies(city='Belleville', state='IL')
        self.assertEqual([row['company'] for row in belleville], ['Friendly Fire LLC'])
        self.assertEqual(DIRECTORY.search_static_companies(city='Belleville', state='MO'), [])


if __name__ == '__main__':
    unittest.main()
