"""Read-only local directory quality inventory; no network, imports, or publication.

Run: python3 -B scripts/audit_directory_quality.py
Counts describe stored evidence, not a new independent verification.
"""
import collections
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('directory_quality_api',ROOT/'api/directory.py')
directory=importlib.util.module_from_spec(spec);spec.loader.exec_module(directory)

def audit(credentials,companies):
    states=collections.Counter();issuers=collections.Counter();people=set();findings=[]
    ids=collections.Counter(str(r.get('id') or '') for r in credentials)
    for record in credentials:
        status,_=directory.static_status(record);states[status]+=1
        if status=='CREDENTIAL VERIFIED':
            issuers[str(record.get('issuer') or 'Unspecified')]+=1
            people.add(tuple(str(record.get(k) or '').strip().casefold() for k in ('holder','company','state')))
        reasons=[]
        if not record.get('id') or ids[str(record['id'])]>1:reasons.append('MISSING_OR_DUPLICATE_RECORD_ID')
        if not record.get('holder'):reasons.append('HOLDER_NOT_RECORDED')
        if not record.get('company'):reasons.append('LISTED_COMPANY_NOT_RECORDED')
        if not directory.valid_http_url(record.get('source') or '') or not directory.official_issuer_source(record.get('issuer'),record.get('source') or ''):reasons.append('OFFICIAL_SOURCE_REVIEW_NEEDED')
        if not record.get('expiration_date'):reasons.append('EXPIRATION_NOT_DOCUMENTED')
        if not record.get('recheck_due_at'):reasons.append('NEXT_REVIEW_NOT_DOCUMENTED')
        if status!='CREDENTIAL VERIFIED':reasons.append('CURRENT_VERIFICATION_REVIEW_NEEDED')
        if reasons:findings.append({'record_id':str(record.get('id') or ''),'review_reasons':reasons})
    return {
      'scope':'Local published metadata only; excludes live database queues and does not recheck sources.',
      'credential_records':len(credentials),'professionals_with_stored_current_verified_credentials':len(people),
      'credential_display_states':dict(states),'stored_current_verified_credentials_by_issuer':dict(issuers),
      'company_source_records':len(companies),
      'company_records_without_documented_service_areas':sum(not directory.service_locations_for(c,str(c.get('state') or c.get('hq_state') or '')) for c in companies),
      'findings':findings,
      'notice':'Missing information is a review task, not evidence that a person is uncertified or a company is illegitimate. No records were changed.'
    }

if __name__=='__main__':
    print(json.dumps(audit(directory.static_records(),[*directory.static_company_records(),*directory.national_company_records()]),indent=2))
