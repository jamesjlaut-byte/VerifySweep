import importlib.util
import json
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("directory", ROOT / "api/directory.py")
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


class DirectorySourceBatchTests(TestCase):
    def test_new_records_are_neutral_and_source_backed(self):
        records = json.loads((ROOT / "data/directory-companies.json").read_text())["records"]
        wanted = {
            "business-traditional-sweep-portsmouth-ri",
            "business-granite-flue-rapid-city-sd",
        }
        found = {row["id"]: row for row in records if row.get("id") in wanted}
        self.assertEqual(set(found), wanted)
        for row in found.values():
            self.assertEqual(row["public_status"], "unverified")
            self.assertEqual(row["source_type"], "official_business_website")
            self.assertTrue(row["source_url"].startswith("https://"))
            self.assertTrue(row["service_locations"])

    def test_rhode_island_and_south_dakota_city_queries_return_matching_records(self):
        for query, expected_id, state in (
            ("Portsmouth, RI", "business-traditional-sweep-portsmouth-ri", "RI"),
            ("Newport, RI", "business-traditional-sweep-portsmouth-ri", "RI"),
            ("Rapid City, SD", "business-granite-flue-rapid-city-sd", "SD"),
            ("Sturgis, SD", "business-granite-flue-rapid-city-sd", "SD"),
        ):
            rows = directory.search_static_companies(q=query)
            self.assertIn(expected_id, {row["id"] for row in rows}, query)
            for row in rows:
                self.assertTrue(
                    directory.normalize_state(row.get("state")) == state
                    or any(directory.normalize_state(a.get("state")) == state for a in row.get("service_locations", [])),
                    (query, row.get("company")),
                )

