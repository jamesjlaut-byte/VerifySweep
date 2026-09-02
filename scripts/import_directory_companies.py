#!/usr/bin/env python3
"""Validate and normalize lawful/authorized company records before database import."""
import argparse,csv,json,re
from pathlib import Path
from urllib.parse import urlparse

FIELDS=('company','website','phone','address_line1','address_line2','city','state','postal_code','country_code','source_type','source_url','source_record_id','captured_at','source_note')

def clean(value,limit=1000):return re.sub(r'\s+',' ',str(value or '')).strip()[:limit]
def domain(value):
    try:return (urlparse(value).hostname or '').lower().removeprefix('www.')
    except:return''
def phone(value):return re.sub(r'\D','',clean(value,80))[-10:]
def name(value):return re.sub(r'[^a-z0-9]+',' ',clean(value,200).lower()).strip()
def normalize(raw):
    row={key:clean(raw.get(key)) for key in FIELDS};row['state']=row['state'].upper()[:2];row['postal_code']=re.sub(r'\D','',row['postal_code'])[:5];row['country_code']=(row['country_code'] or 'US').upper()[:2]
    if not row['company']:raise ValueError('company is required')
    if not row['source_url'] or urlparse(row['source_url']).scheme not in ('http','https'):raise ValueError(f"{row['company']}: valid source_url is required")
    if not row['source_type']:raise ValueError(f"{row['company']}: source_type is required")
    if not row['captured_at']:raise ValueError(f"{row['company']}: captured_at is required")
    row.update(normalized_name=name(row['company']),normalized_domain=domain(row['website']),normalized_phone=phone(row['phone']),public_status='unverified',claim_status='unclaimed')
    return row
def identity(row):
    if row['normalized_domain']:return ('domain',row['normalized_domain'])
    if row['normalized_phone']:return ('phone',row['normalized_phone'])
    return ('name_zip',row['normalized_name'],row['postal_code'])
def prepare(records):
    accepted=[];duplicates=[];seen={}
    for index,raw in enumerate(records,1):
        row=normalize(raw);key=identity(row)
        if key in seen:duplicates.append({'row':index,'matches_row':seen[key],'identity':key,'company':row['company']});continue
        seen[key]=index;accepted.append(row)
    return accepted,duplicates
def load(path):
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as source:return list(csv.DictReader(source))
    payload=json.loads(path.read_text(encoding='utf-8'));return payload.get('records',[]) if isinstance(payload,dict) else payload
def main():
    parser=argparse.ArgumentParser(description='Prepare authorized company records for VerifySweep review.')
    parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();accepted,duplicates=prepare(load(args.source));report={'publication_status':'unverified','records':accepted,'possible_exact_duplicates':duplicates,'accepted_count':len(accepted),'duplicate_count':len(duplicates),'note':'Prepared records require review. Importing or claiming a company does not make it verified.'}
    text=json.dumps(report,indent=2);args.output.write_text(text+'\n',encoding='utf-8') if args.output else print(text)
if __name__=='__main__':main()
