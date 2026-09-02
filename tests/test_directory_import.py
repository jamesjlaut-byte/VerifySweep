import importlib.util,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('directory_import',ROOT/'scripts'/'import_directory_companies.py')
IMPORTER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(IMPORTER)

class DirectoryImportTests(unittest.TestCase):
    def record(self,**changes):
        row={'company':'Example Chimney LLC','website':'https://www.example.com/','phone':'(555) 123-4567','city':'Austin','state':'tx','postal_code':'78701','source_type':'authorized_public_record','source_url':'https://source.example/record/1','captured_at':'2026-09-02T00:00:00Z'};row.update(changes);return row
    def test_normalized_record_is_never_auto_verified(self):
        row=IMPORTER.normalize(self.record())
        self.assertEqual(row['public_status'],'unverified');self.assertEqual(row['claim_status'],'unclaimed')
        self.assertEqual(row['normalized_domain'],'example.com');self.assertEqual(row['normalized_phone'],'5551234567');self.assertEqual(row['state'],'TX')
    def test_exact_domain_duplicates_are_reported_not_merged(self):
        rows,duplicates=IMPORTER.prepare([self.record(),self.record(company='Example Chimney of Austin',source_record_id='2')])
        self.assertEqual(len(rows),1);self.assertEqual(len(duplicates),1);self.assertEqual(duplicates[0]['identity'],('domain','example.com'))
    def test_source_provenance_is_required(self):
        with self.assertRaises(ValueError):IMPORTER.normalize(self.record(source_url=''))

if __name__=='__main__':unittest.main()
