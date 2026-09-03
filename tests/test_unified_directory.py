import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('directory_api',ROOT/'api'/'directory.py')
directory=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(directory)


class UnifiedDirectoryTests(unittest.TestCase):
    def test_directory_uses_current_nfi_public_search_entry(self):
        page=(ROOT/'find-a-pro.html').read_text()
        self.assertIn('https://www.nficertified.org/public/',page)
        self.assertNotIn('https://www.nficertified.org/public/find-an-nfi-pro/',page)

    def test_national_seed_is_canonical_and_neutral(self):
        data=json.loads((ROOT/'data'/'national-directory.json').read_text())
        self.assertEqual(data['source_record_count'],356)
        self.assertEqual(data['canonical_record_count'],347)
        domains=[x['normalized_domain'] for x in data['records'] if x.get('normalized_domain')]
        self.assertEqual(len(domains),len(set(domains)))
        self.assertTrue(all(x['public_status']=='unverified' for x in data['records']))
        self.assertTrue(all(c['classification']=='UNVERIFIED CLAIM' for x in data['records'] for c in x['company_claims']))
        self.assertTrue(all(p['status']=='VERIFICATION NEEDED' for x in data['records'] for p in x['professional_candidates']))

    def test_austin_service_area_search(self):
        rows=directory.search_static_companies(city='Austin',state='TX')
        hill=next(x for x in rows if x['company'].startswith('Hill Country'))
        self.assertEqual(hill['match_reason'],'Published service area match')
        self.assertIn('Austin, TX',hill['service_area_labels'])

    def test_named_professional_research_search_is_not_verified(self):
        seed=directory.national_company_records()
        record=next(x for x in seed if x.get('professional_candidates'))
        query=record['professional_candidates'][0]['name_or_note']
        rows=directory.search_static_companies(q=query)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['match_reason'],'Named professional research match')
        self.assertFalse(rows[0].get('professionals'))

    def test_same_name_different_hq_is_not_merged(self):
        rows=[x for x in directory.national_company_records() if x['company'].lower().startswith('the chimney doctor')]
        identities={(x['hq_city'],x['hq_state']) for x in rows}
        self.assertIn(('Metamora','IL'),identities)
        self.assertIn(('Jackson','MS'),identities)

    def test_research_confirmed_cross_state_record_is_merged(self):
        rows=[x for x in directory.national_company_records() if x['company']=='The Original Chimney Sweep, Inc.']
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0]['states_discovered']),{'MA','RI'})

    def test_zip_resolver_uses_fixed_host_and_sanitized_zip(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return b'{"places":[{"place name":"Austin","state abbreviation":"TX"}]}'
        directory.resolve_us_zip.cache_clear()
        with patch.object(directory,'urlopen',return_value=Response()) as opened:
            self.assertEqual(directory.resolve_us_zip('78701'),{'city':'Austin','state':'TX'})
            self.assertEqual(opened.call_args.args[0].full_url,'https://api.zippopotam.us/us/78701')
        self.assertIsNone(directory.resolve_us_zip('http://127.0.0.1'))

    def test_every_state_and_dc_has_public_search_coverage(self):
        states='AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split()
        self.assertEqual([], [state for state in states if not directory.search_static_companies(state=state)])

    def test_exact_company_match_ranks_first(self):
        rows=directory.search_static_companies(q='Hill Country Air Duct And Chimney Sweeps LLC')
        self.assertTrue(rows)
        self.assertEqual(rows[0]['company'],'Hill Country Air Duct And Chimney Sweeps LLC')
        self.assertEqual(rows[0]['match_reason'],'Exact company match')

    def test_city_location_ranks_before_service_area(self):
        rows=directory.search_static_companies(city='Austin',state='TX')
        self.assertEqual([row['match_rank'] for row in rows],sorted(row['match_rank'] for row in rows))

    def test_founder_affiliated_company_has_no_special_status_or_rank(self):
        rows=directory.search_static_companies(state='TX')
        hill=next(row for row in rows if row['company']=='Hill Country Air Duct And Chimney Sweeps LLC')
        self.assertEqual(hill['public_status'],'unverified')
        self.assertNotEqual(rows[0]['company'],'Hill Country Air Duct And Chimney Sweeps LLC')

    def test_reviewed_professional_name_search_uses_reviewed_records(self):
        rows=directory.search_static_companies(q='Pete Pohlman')
        self.assertEqual(rows[0]['company'],'Black Velvet Chimney')
        self.assertEqual(rows[0]['match_reason'],'Reviewed professional match')
        self.assertEqual(rows[0]['reviewed_professional_names'],['Pete Pohlman'])
        self.assertEqual(rows[0]['verified_professional_count'],1)

    def test_reviewed_individual_filter_does_not_promote_company_claims(self):
        rows=directory.search_static_companies(verified_only=True)
        self.assertTrue({
            'Black Velvet Chimney','Duct Time','Hill Country Air Duct And Chimney Sweeps LLC','Wolfman Chimney & Fireplace'
        }.issubset({row['company'] for row in rows}))
        self.assertTrue(all(row['verified_professional_count']>0 for row in rows))
        claims_only=directory.search_static_companies(q='1st Choice Chimney Commercial LLC')
        self.assertEqual(claims_only[0]['verified_professional_count'],0)

    def test_ncsg_records_are_named_current_source_credentials(self):
        records=directory.static_records()
        ncsg=[row for row in records if row.get('issuer')=='NCSG']
        self.assertGreaterEqual(len(ncsg),41)
        self.assertTrue(all(row['holder'] and row['company'] for row in ncsg))
        allowed={
            'Accredited Certified Chimney Professional',
            'Accredited Certified Chimney Journeyman',
            'Master Chimney Professional',
            'Honorary Master Chimney Professional',
        }
        self.assertTrue(all(row['credential'] in allowed for row in ncsg))
        self.assertTrue(all(row['verification_status']=='verified_from_official_source' for row in ncsg))
        self.assertTrue(all(row['source']=='https://ncsg.org/find-a-sweep/find-a-certified-sweep' for row in ncsg))

    def test_csia_records_are_named_and_link_to_individual_official_profiles(self):
        records=directory.static_records()
        csia=[row for row in records if row.get('issuer')=='CSIA']
        self.assertGreaterEqual(len(csia),81)
        self.assertTrue(all(row['holder'] and row['company'] for row in csia))
        self.assertTrue(all(row['credential']=='Certified Chimney Sweep' for row in csia))
        self.assertTrue(all(row['verification_status']=='verified_from_official_source' for row in csia))
        self.assertTrue(all(row['source'].startswith('https://web.csia.org/CSIA-Certified/') for row in csia))
        self.assertTrue(all('/Texas' not in row['source'] for row in csia))
        self.assertTrue({'Layton Mitten','Sahar Mazoz','Lee Roff','Jack Wachsmann','Santiago Ramirez Jr.'}.issubset({row['holder'] for row in csia}))

    def test_csia_expansion_covers_named_california_and_florida_professionals(self):
        california=directory.search_static_companies(state='CA',issuer='CSIA',verified_only=True)
        florida=directory.search_static_companies(state='FL',issuer='CSIA',verified_only=True)
        ca_names={name for row in california for name in row['reviewed_professional_names']}
        fl_names={name for row in florida for name in row['reviewed_professional_names']}
        self.assertTrue({'Kyle Pocock','Tyler Kezas','Richard Pocock','Robert Ornelas','Michaele Dempsey'}.issubset(ca_names))
        self.assertTrue({'James Simmons','Joshua Brosius','Michael Wood','Jenea Clarke','Michael Rayner','David Wayne Godwin','Robert Lavallee'}.issubset(fl_names))

    def test_csia_expansion_covers_named_new_york_and_pennsylvania_professionals(self):
        new_york=directory.search_static_companies(state='NY',issuer='CSIA',verified_only=True)
        pennsylvania=directory.search_static_companies(state='PA',issuer='CSIA',verified_only=True)
        ny_names={name for row in new_york for name in row['reviewed_professional_names']}
        pa_names={name for row in pennsylvania for name in row['reviewed_professional_names']}
        self.assertTrue({'Alfred Papile','Maurice Ware','Claudio Zhinin','John Pilger','Marlon Juarbe'}.issubset(ny_names))
        self.assertTrue({'Joe Soriano','Mark Kerwood','Tyler Bollinger','Isabella Weidman','Andy Homan'}.issubset(pa_names))

    def test_additional_pennsylvania_csia_professionals_are_grouped_by_company(self):
        rows=directory.search_static_companies(q='Chim Chimney Sweeps',state='PA',issuer='CSIA',verified_only=True)
        self.assertEqual(len(rows),1)
        self.assertTrue(
            {
                'Tyler Bollinger','Isabella Weidman','Steven Wallower','Joe Corcoran','Ben Bowen-Aretz',
                'Jonathan Cross','Robert Green','Robert Pettit II','Benjamin Cross','Ted Demopoulos',
            }.issubset(
                set(rows[0]['reviewed_professional_names'])
            )
        )

        curley=directory.search_static_companies(q="Lou Curley's Chimney Service",state='PA',issuer='CSIA',verified_only=True)
        self.assertEqual(len(curley),1)
        self.assertTrue({'Joe Soriano','Steven A Boppell','Dave Curley','Lou Curley'}.issubset(set(curley[0]['reviewed_professional_names'])))

    def test_ohio_csia_professionals_are_named_and_grouped(self):
        ohio=directory.search_static_companies(state='OH',issuer='CSIA',verified_only=True)
        names={name for row in ohio for name in row['reviewed_professional_names']}
        self.assertTrue({'David Zilberman','Dennis Jacob','Kevin Daniel','Ken Hoelscher','Dylan Dunivan','Cody Carter','Jake Barton'}.issubset(names))
        abbey=next(row for row in ohio if row['company']=='Abbey Road Chimney Services LLC')
        self.assertEqual(set(abbey['reviewed_professional_names']),{'Kevin Daniel','Ken Hoelscher','Dylan Dunivan'})
        pro_sweep=next(row for row in ohio if row['company']=='Pro Sweep Chimney Service')
        self.assertEqual(set(pro_sweep['reviewed_professional_names']),{'Dennis Jacob','Cody Carter'})

    def test_illinois_csia_professionals_are_named_and_state_scoped(self):
        illinois=directory.search_static_companies(state='IL',issuer='CSIA',verified_only=True)
        names={name for row in illinois for name in row['reviewed_professional_names']}
        self.assertTrue({'Aeden Roger','Mike Strickland','Bill Fox','David Palm','James Duda','Daniel Colon','Danny Edmonds','Pankaj Patel','Ken Kopka','Todd Dosemagen'}.issubset(names))
        vertical=next(row for row in illinois if row['company']=='Vertical Chimney Care')
        self.assertEqual(set(vertical['reviewed_professional_names']),{'James Duda','Danny Edmonds'})
        doctor=directory.search_static_companies(q='Todd Dosemagen',state='IL',issuer='CSIA',verified_only=True)
        self.assertEqual([(row['company'],row['state']) for row in doctor],[('The Chimney Doctor','IL')])
        leonard=next(row for row in illinois if row['company']=='Leonard & Sons Building Service Inc.')
        self.assertEqual(set(leonard['reviewed_professional_names']),{'Malik Cox','Evan Vining','Caleb Martinez'})
        authority=next(row for row in illinois if row['company']=='Fireplace and Chimney Authority, Inc.')
        self.assertEqual(set(authority['reviewed_professional_names']),{'Mike Strickland','Daniel Colon','Rocky Insixiengmay'})

    def test_michigan_csia_professionals_are_named_and_grouped(self):
        michigan=directory.search_static_companies(state='MI',issuer='CSIA',verified_only=True)
        names={name for row in michigan for name in row['reviewed_professional_names']}
        self.assertTrue({'Nathan Adair','Richard Lane','Tim Reiher','Chase Czymbor','William Castle','Tyler Bogard','Charles Weber'}.issubset(names))
        alpha=next(row for row in michigan if row['company']=='Alpha & Omega Services LLC')
        self.assertEqual(set(alpha['reviewed_professional_names']),{'Nathan Adair','Chase Czymbor','William Castle','Tyler Bogard'})

    def test_reviewed_professional_links_to_same_state_canonical_company(self):
        rows,_=directory.search_companies_db(q='Matthew Mirabal',verified_only=True)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['company'], "Bailey's Chimney, LLC")
        self.assertEqual(rows[0]['reviewed_professional_names'], ['Matthew Mirabal'])
        self.assertEqual(rows[0]['reviewed_professionals'][0]['credential'], 'Accredited Certified Chimney Professional')
        self.assertEqual(rows[0]['reviewed_professionals'][0]['issuer'], 'NCSG')
        self.assertEqual(rows[0]['reviewed_professionals'][0]['display_status'], 'CREDENTIAL VERIFIED')
        self.assertEqual(rows[0]['reviewed_professionals'][0]['identity_status'], 'UNKNOWN')
        self.assertEqual(rows[0]['reviewed_professionals'][0]['company_affiliation_status'], 'UNKNOWN')
        detail,_=directory.detail_company(rows[0]['id'])
        self.assertEqual([person['holder'] for person in detail['professionals']], ['Matthew Mirabal'])

    def test_multiple_credentials_remain_separate_for_one_individual(self):
        rows,_=directory.search_companies_db(q='Paul Robison',verified_only=True)
        self.assertEqual(len(rows),1)
        credentials=[person['credential'] for person in rows[0]['reviewed_professionals'] if person['holder']=='Paul Robison']
        self.assertEqual(credentials,['Accredited Certified Chimney Journeyman','Master Chimney Professional'])

    def test_professional_detail_groups_credentials_for_one_named_person(self):
        detail=directory.detail_static('ncsg-paul-robison-journeyman')
        self.assertEqual(detail['holder'],'Paul Robison')
        self.assertEqual(
            {credential['credential'] for credential in detail['credentials']},
            {'Accredited Certified Chimney Journeyman','Master Chimney Professional'}
        )
        longest=directory.detail_static('ncsg-scott-imgarten-honorary-master')
        self.assertEqual(longest['holder'],'Scott Imgarten')

    def test_search_and_profile_pages_link_to_named_professionals(self):
        search=(ROOT/'find-a-pro.html').read_text()
        profile=(ROOT/'professional-profile.html').read_text()
        company=(ROOT/'company-profile.html').read_text()
        self.assertIn("'View Professional'",search)
        self.assertIn("/professional-profile.html?id=",search)
        self.assertIn('Only professionals with verified credentials',search)
        self.assertIn('No professional with an independently verified credential',search)
        self.assertIn('PROFESSIONALS WITH REVIEWED CREDENTIALS',search)
        self.assertIn('Verify the person—not just the company',search)
        self.assertIn('COMPANY DISCOVERY RECORDS',search)
        self.assertIn("person.credentials[0].id",search)
        self.assertIn("^[A-Za-z0-9_-]{1,80}$",profile)
        self.assertIn("'VERIFY WITH ISSUER'",profile)
        self.assertIn("'VERIFICATION DETAILS'",profile)
        self.assertIn('Credential holder:',profile)
        self.assertIn('Expiration:',profile)
        self.assertIn('Review due:',profile)
        self.assertIn("'REPORT A PROBLEM'",profile)
        self.assertIn('mailto:info@verifysweep.com',profile)
        self.assertIn("'View Professional'",company)
        self.assertIn("'REPORT A PROBLEM'",company)

    def test_professional_detail_does_not_infer_identity_or_affiliation(self):
        detail=directory.detail_static('ncsg-paul-robison-journeyman')
        self.assertEqual(detail['display_status'],'CREDENTIAL VERIFIED')
        self.assertEqual(detail['identity_status'],'UNKNOWN')
        self.assertEqual(detail['company_affiliation_status'],'UNKNOWN')

    def test_known_company_alias_attaches_named_credentials_to_service_area_record(self):
        rows=directory.search_static_companies(q='Lee Roff',verified_only=True)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['company'],'Lords Chimney')
        self.assertIn('Houston, TX',rows[0]['service_area_labels'])
        self.assertEqual({person['issuer'] for person in rows[0]['reviewed_professionals']},{'CSIA','NCSG'})

    def test_company_search_filters_by_issuer_and_exact_credential_type(self):
        masters=directory.search_static_companies(issuer='NCSG',credential_type='Master Chimney Professional')
        self.assertTrue({'Top Hat Chimney, LLC','Master Sweep and Repair'}.issubset({row['company'] for row in masters}))
        self.assertTrue(all(person['issuer']=='NCSG' and person['credential']=='Master Chimney Professional' for row in masters for person in row['reviewed_professionals']))
        self.assertEqual(directory.search_static_companies(q='Paul Robison',issuer='CSIA'),[])


if __name__=='__main__':unittest.main()
