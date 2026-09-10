import importlib.util
from pathlib import Path
from unittest import TestCase

spec=importlib.util.spec_from_file_location('source_batch',Path(__file__).resolve().parents[1]/'api/directory.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

BATCH={
 'national-ea836cbfb1c63d':('UT',['Springville','Provo','Orem','Spanish Fork','Mapleton','Payson','Salem','American Fork','Lehi','Pleasant Grove','Salt Lake City','Sandy','Draper','Riverton','South Jordan','West Jordan','Heber City','Park City','Nephi','Ephraim']),
 'national-a7e009adc742a1':('MS',['Jackson','Clinton','Madison','Pearl','Brandon','Ridgeland','Byram','Canton','Flowood','Richland','Florence','Raymond','Vicksburg','Brookhaven','Yazoo City']),
 'national-1ab4c7df939d1b':('ND',['Fargo']),
 'national-a7d33580c81514':('WY',['Cody']),
 'business-village-chimney-freedom-wy':('WY',['Freedom']),
 'business-aurora-chimney-alaska':('AK',['Wasilla','Anchorage'])
}

class SourceBatchTests(TestCase):
 def test_source_backed_city_searches_find_each_record_once(self):
  for identifier,(state,cities) in BATCH.items():
   for city in cities:
    matches=[r for r in d.search_static_companies(city=city,state=state) if identifier==r['id'] or identifier in r.get('record_aliases',[])]
    self.assertEqual(len(matches),1,(identifier,city))
    self.assertEqual(matches[0]['public_status'],'unverified')
    self.assertEqual(matches[0]['verified_professional_count'],0)
    self.assertTrue(matches[0]['source_url'].startswith('https://'))

 def test_documented_cross_state_service_not_statewide_assumption(self):
  for city in ['Moorhead','Detroit Lakes']:
   self.assertTrue(any(r['id']=='national-1ab4c7df939d1b' for r in d.search_static_companies(city=city,state='MN')))
   self.assertFalse(any(r['id']=='national-1ab4c7df939d1b' for r in d.search_static_companies(city=city,state='ND')))
  self.assertFalse(any(r['id']=='business-aurora-chimney-alaska' for r in d.search_static_companies(city='Soldotna',state='AK')))
  self.assertFalse(any(r['id']=='national-ea836cbfb1c63d' for r in d.search_static_companies(state='WY')))

 def test_stable_profile_ids_resolve_without_credential_promotion(self):
  for identifier in BATCH:
   record,_=d.detail_company(identifier)
   self.assertIsNotNone(record,identifier)
   self.assertEqual(record['public_status'],'unverified')
   self.assertEqual(record['verified_professional_count'],0)
