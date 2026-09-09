import importlib.util
from datetime import datetime,timezone,timedelta,date
from pathlib import Path
import unittest
from unittest.mock import MagicMock,patch

spec=importlib.util.spec_from_file_location('public_freshness',Path(__file__).resolve().parents[1]/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)
KEYS=['id','company','holder','credential','credential_type','issuer','source','city','state','zip','website','phone','verification_status','verified_at','last_checked_at','recheck_due_at','source_available','source_note','identity_status','company_affiliation_status','distance','credential_number','expiration_date']

class PublicFreshnessTests(unittest.TestCase):
    def record(self,**changes):
        record=dict(id=1,company='Test Company',holder='Test Person',credential='Sweep',credential_type='Sweep',issuer='CSIA',source='https://web.csia.org/CSIA-Certified',verification_status='verified_from_official_source',verified_at='2026-01-01',recheck_due_at='2099-01-01',source_available=True,credential_number='TEST-123',expiration_date=date(2000,1,1))
        record.update(changes);return record

    def connection(self,record):
        conn=MagicMock();cur=conn.cursor.return_value.__enter__.return_value;row=tuple(record.get(k) for k in KEYS)
        cur.fetchone.return_value=row;cur.fetchall.return_value=[row];return conn,cur

    def test_expired_db_record_not_revived_by_static_fallback(self):
        record=self.record();conn,_=self.connection(record)
        fallback={**record,'expiration_date':'2099-01-01','display_status':'CREDENTIAL VERIFIED'}
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'),patch.object(directory,'search_static',return_value=([fallback],False)):
            rows,_=directory.search_db('')
        self.assertEqual(rows,[])

    def test_profile_includes_expiration_number_and_expired_status(self):
        conn,cur=self.connection(self.record())
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'):
            profile=directory.detail_db(1)
        self.assertEqual(profile['display_status'],'EXPIRED')
        self.assertEqual(profile['credentials'][0]['expiration_date'],date(2000,1,1))
        self.assertEqual(profile['credentials'][0]['credential_number'],'TEST-123')
        self.assertIn('credential_number,expiration_date',cur.execute.call_args.args[0])

    def test_shared_directory_url_does_not_hide_another_person(self):
        record=self.record(expiration_date='2099-01-01');conn,_=self.connection(record)
        other={**record,'holder':'Another Person','id':2}
        with patch.object(directory,'dbconn',return_value=conn),patch.object(directory,'ensure'),patch.object(directory,'search_static',return_value=([record,other],False)):
            rows,_=directory.search_db('')
        self.assertEqual({r['holder'] for r in rows},{'Test Person','Another Person'})
        self.assertEqual(len(rows),2)

    def test_date_only_expiration_remains_current_through_utc_date(self):
        today=datetime.now(timezone.utc).date()
        for value in [today,today.isoformat()]:
            self.assertEqual(directory.static_status(self.record(expiration_date=value))[0],'CREDENTIAL VERIFIED')
        self.assertEqual(directory.static_status(self.record(expiration_date=today-timedelta(days=1)))[0],'EXPIRED')
