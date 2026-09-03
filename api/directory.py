import json, math, os, re
from functools import lru_cache
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

DB=os.environ.get('DATABASE_URL','')
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_RECORDS=os.path.join(ROOT,'data','certified-professionals.json')
STATIC_COMPANIES=os.path.join(ROOT,'data','directory-companies.json')
NATIONAL_COMPANIES=os.path.join(ROOT,'data','national-directory.json')
ZIP_CENTROIDS=os.path.join(ROOT,'data','us-zcta-centroids.tsv')
PUBLISHED_STATUS='verified'
ALLOWED_RADII={10,25,50,75,100}
PUBLIC_COMPANY_STATUSES=('unverified','verification_in_progress','verified','information_updated')
COMPANY_STATUS_LABELS={
  'unverified':'UNVERIFIED',
  'verification_in_progress':'VERIFICATION IN PROGRESS',
  'verified':'VERIFIED',
  'information_updated':'INFORMATION UPDATED / VERIFICATION NEEDED'
}
OFFICIAL_SOURCES={
  'csia':'https://web.csia.org/CSIA-Certified',
  'nfi':'https://www.nficertified.org/search-instructor/'
}
ZIP_LOOKUP_BASE='https://api.zippopotam.us/us/'
NORMALIZED_DIRECTORY_SCHEMA=(
  '''CREATE TABLE IF NOT EXISTS directory_companies (
    id BIGSERIAL PRIMARY KEY, canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
    website TEXT, normalized_domain TEXT, phone TEXT, normalized_phone TEXT,
    address_line1 TEXT, address_line2 TEXT, city TEXT, state TEXT, postal_code TEXT, country_code TEXT NOT NULL DEFAULT 'US',
    public_status TEXT NOT NULL DEFAULT 'unverified' CHECK (public_status IN ('unverified','verification_in_progress','verified','information_updated','not_eligible','removed')),
    claim_status TEXT NOT NULL DEFAULT 'unclaimed' CHECK (claim_status IN ('unclaimed','claim_pending','claimed')),
    last_reviewed_at TIMESTAMPTZ, verification_due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_professionals (
    id BIGSERIAL PRIMARY KEY, company_id BIGINT REFERENCES directory_companies(id) ON DELETE SET NULL,
    professional_name TEXT NOT NULL, role_title TEXT, public_state TEXT NOT NULL DEFAULT 'pending' CHECK (public_state IN ('pending','active','inactive','removed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_credentials (
    id BIGSERIAL PRIMARY KEY, professional_id BIGINT NOT NULL REFERENCES directory_professionals(id) ON DELETE CASCADE,
    issuer TEXT NOT NULL, credential_type TEXT NOT NULL, credential_number TEXT,
    official_source_url TEXT, verification_status TEXT NOT NULL DEFAULT 'verification_needed' CHECK (verification_status IN ('verification_needed','verification_in_progress','verified_from_official_source','official_source_available','not_currently_confirmed','verification_update_needed')),
    verified_at TIMESTAMPTZ, last_checked_at TIMESTAMPTZ, recheck_due_at TIMESTAMPTZ,
    source_available BOOLEAN NOT NULL DEFAULT TRUE, source_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_company_sources (
    id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES directory_companies(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL, source_url TEXT NOT NULL, source_record_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL, imported_at TIMESTAMPTZ NOT NULL DEFAULT now(), source_note TEXT
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_claims (
    id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES directory_companies(id) ON DELETE CASCADE,
    claimant_user_id TEXT, claimant_name TEXT, claimant_email TEXT, evidence_reference TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','needs_evidence','approved','rejected','withdrawn')),
    reviewed_by TEXT, reviewed_at TIMESTAMPTZ, review_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_verification_events (
    id BIGSERIAL PRIMARY KEY, company_id BIGINT REFERENCES directory_companies(id) ON DELETE SET NULL,
    professional_id BIGINT REFERENCES directory_professionals(id) ON DELETE SET NULL,
    credential_id BIGINT REFERENCES directory_credentials(id) ON DELETE SET NULL,
    reviewer_id TEXT NOT NULL, action TEXT NOT NULL, reason_code TEXT, evidence_reference TEXT,
    old_value JSONB, new_value JSONB, verification_standard_version TEXT, recheck_due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_service_areas (
    id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES directory_companies(id) ON DELETE CASCADE,
    postal_code TEXT, city TEXT, state TEXT, radius_miles INTEGER CHECK (radius_miles IS NULL OR radius_miles BETWEEN 1 AND 500),
    source_reference TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (postal_code IS NOT NULL OR city IS NOT NULL)
  )''',
  "ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS area_type TEXT NOT NULL DEFAULT 'city'",
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS county TEXT',
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS source_url TEXT',
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS evidence_text TEXT',
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS evidence_type TEXT',
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ',
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ',
  "ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS evidence_status TEXT NOT NULL DEFAULT 'review_needed'",
  'ALTER TABLE directory_service_areas ADD COLUMN IF NOT EXISTS content_hash TEXT',
  '''CREATE TABLE IF NOT EXISTS directory_company_claims (
    id BIGSERIAL PRIMARY KEY, company_id BIGINT NOT NULL REFERENCES directory_companies(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL, classification TEXT NOT NULL DEFAULT 'UNVERIFIED CLAIM',
    source_url TEXT, evidence_note TEXT, last_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE TABLE IF NOT EXISTS directory_audit_log (
    id BIGSERIAL PRIMARY KEY, actor_id TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
    old_value JSONB, new_value JSONB, reason TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  )''',
  '''CREATE OR REPLACE FUNCTION verifysweep_prevent_event_mutation() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'VerifySweep audit and verification events are append-only'; END;
  $$ LANGUAGE plpgsql''',
  '''DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='directory_verification_events_immutable') THEN
      CREATE TRIGGER directory_verification_events_immutable BEFORE UPDATE OR DELETE ON directory_verification_events
      FOR EACH ROW EXECUTE FUNCTION verifysweep_prevent_event_mutation();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='directory_audit_log_immutable') THEN
      CREATE TRIGGER directory_audit_log_immutable BEFORE UPDATE OR DELETE ON directory_audit_log
      FOR EACH ROW EXECUTE FUNCTION verifysweep_prevent_event_mutation();
    END IF;
  END $$''',
  'CREATE INDEX IF NOT EXISTS directory_companies_name_idx ON directory_companies (normalized_name)',
  'CREATE INDEX IF NOT EXISTS directory_companies_domain_idx ON directory_companies (normalized_domain)',
  'CREATE INDEX IF NOT EXISTS directory_companies_phone_idx ON directory_companies (normalized_phone)',
  'CREATE INDEX IF NOT EXISTS directory_companies_geo_idx ON directory_companies (postal_code,state,city)',
  'CREATE INDEX IF NOT EXISTS directory_companies_public_status_idx ON directory_companies (public_status)',
  'CREATE INDEX IF NOT EXISTS directory_professionals_company_idx ON directory_professionals (company_id)',
  'CREATE INDEX IF NOT EXISTS directory_credentials_professional_idx ON directory_credentials (professional_id)',
  'CREATE INDEX IF NOT EXISTS directory_sources_company_idx ON directory_company_sources (company_id)',
  'CREATE INDEX IF NOT EXISTS directory_claims_queue_idx ON directory_claims (review_status,created_at)',
  'CREATE INDEX IF NOT EXISTS directory_verification_queue_idx ON directory_verification_events (created_at)',
  'CREATE INDEX IF NOT EXISTS directory_service_area_zip_idx ON directory_service_areas (postal_code)',
  'CREATE INDEX IF NOT EXISTS directory_audit_target_idx ON directory_audit_log (target_type,target_id,created_at)'
)

def clean(v,n=500): return re.sub(r'\s+',' ',str(v or '')).strip()[:n]
def valid_zip(z): return bool(re.fullmatch(r'\d{5}',z or ''))
def valid_http_url(v):
    try:return urlparse(v).scheme in ('http','https') and bool(urlparse(v).hostname)
    except:return False

@lru_cache(maxsize=512)
def resolve_us_zip(zipcode):
    """Resolve a valid US ZIP through one fixed public endpoint; never follows user hosts."""
    if not valid_zip(zipcode):return None
    try:
        request=Request(ZIP_LOOKUP_BASE+zipcode,headers={'Accept':'application/json','User-Agent':'VerifySweep-Directory/1.0'})
        with urlopen(request,timeout=3) as response:
            if response.status!=200:return None
            payload=json.loads(response.read(32768).decode('utf-8'))
        places=payload.get('places') or []
        if not places:return None
        city=clean(places[0].get('place name'),120);state=clean(places[0].get('state abbreviation'),2).upper()
        return {'city':city,'state':state} if city and re.fullmatch(r'[A-Z]{2}',state) else None
    except Exception:return None

def dbconn():
    if not DB:return None
    import psycopg
    return psycopg.connect(DB,connect_timeout=5)

@lru_cache(maxsize=1)
def static_records():
    try:
        with open(STATIC_RECORDS,encoding='utf-8') as source:
            payload=json.load(source)
        return payload.get('records',[]) if isinstance(payload,dict) else []
    except (OSError,ValueError):return []

@lru_cache(maxsize=1)
def static_company_records():
    try:
        with open(STATIC_COMPANIES,encoding='utf-8') as source:
            payload=json.load(source)
        return payload.get('records',[]) if isinstance(payload,dict) else []
    except (OSError,ValueError):return []

@lru_cache(maxsize=1)
def national_company_records():
    try:
        with open(NATIONAL_COMPANIES,encoding='utf-8') as source:
            payload=json.load(source)
        return payload.get('records',[]) if isinstance(payload,dict) else []
    except (OSError,ValueError):return []

@lru_cache(maxsize=1)
def zip_centroids():
    points={}
    try:
        with open(ZIP_CENTROIDS,encoding='utf-8') as source:
            for line in source:
                parts=line.rstrip().split('\t')
                if len(parts)==3 and valid_zip(parts[0]):points[parts[0]]=(float(parts[1]),float(parts[2]))
    except (OSError,ValueError):return {}
    return points

def miles(a,b):
    lat1,lon1,lat2,lon2=map(math.radians,(a[0],a[1],b[0],b[1]))
    dlat=lat2-lat1;dlon=lon2-lon1
    arc=2*math.asin(math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2))
    return 3958.7613*arc

def static_status(item):
    if not item.get('source_available',True):return ('OFFICIAL SOURCE AVAILABLE','Official source temporarily unavailable. Credential could not be rechecked at this time.')
    due=clean(item.get('recheck_due_at'),40)
    try:is_stale=bool(due) and datetime.fromisoformat(due.replace('Z','+00:00')) < datetime.now(timezone.utc)
    except ValueError:is_stale=True
    if is_stale:return ('VERIFICATION UPDATE NEEDED','The prior verification is stale and should be checked again at the official source.')
    if item.get('verification_status')=='verified_from_official_source' and item.get('verified_at'):
        return ('VERIFIED FROM OFFICIAL SOURCE','The individual credential was checked against the linked official source.')
    return ('VERIFICATION NEEDED','This record requires an updated official-source verification.')

def search_static(zipcode,q='',radius=25):
    points=zip_centroids();origin=points.get(zipcode);rows=[];needle=clean(q,120).lower()
    for source in static_records():
        item=dict(source)
        if needle and needle not in ' '.join(clean(item.get(k),200).lower() for k in ('holder','company','city','state')).lower():continue
        distance=None;target=points.get(clean(item.get('zip'),5))
        if origin and target:
            distance=miles(origin,target)
            if distance>radius:continue
        elif zipcode and zipcode!=clean(item.get('zip'),5) and zipcode not in (item.get('service_zips') or []):continue
        item['distance']=round(distance,1) if distance is not None else None
        item['display_status'],item['status_note']=static_status(item);rows.append(item)
    rows.sort(key=lambda r:(r.get('holder',''),r.get('company',''),r.get('credential','')))
    return rows,bool(origin)

def detail_static(identifier):
    for source in static_records():
        if str(source.get('id'))==str(identifier):
            item=dict(source);item['distance']=None;item['display_status'],item['status_note']=static_status(item);return item
    return None

def ensure(conn):
    with conn.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS pro_directory (
          id BIGSERIAL PRIMARY KEY, company TEXT NOT NULL, professional_name TEXT NOT NULL,
          credential TEXT NOT NULL, issuer TEXT NOT NULL, credential_source TEXT NOT NULL,
          city TEXT, state TEXT, postal_code TEXT, service_zips TEXT[] DEFAULT '{}',
          website TEXT, phone TEXT, status TEXT NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )''')
        migrations=[
          "ADD COLUMN IF NOT EXISTS credential_type TEXT",
          "ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'verification_needed'",
          "ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ",
          "ADD COLUMN IF NOT EXISTS source_last_checked_at TIMESTAMPTZ",
          "ADD COLUMN IF NOT EXISTS recheck_due_at TIMESTAMPTZ",
          "ADD COLUMN IF NOT EXISTS source_available BOOLEAN NOT NULL DEFAULT TRUE",
          "ADD COLUMN IF NOT EXISTS source_note TEXT",
          "ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION",
          "ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION"
        ]
        for migration in migrations:cur.execute('ALTER TABLE pro_directory '+migration)
        cur.execute('''CREATE TABLE IF NOT EXISTS zip_centroids (
          postal_code TEXT PRIMARY KEY, latitude DOUBLE PRECISION NOT NULL,
          longitude DOUBLE PRECISION NOT NULL, source TEXT NOT NULL, imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )''')
        cur.execute('CREATE INDEX IF NOT EXISTS pro_directory_zip_idx ON pro_directory (postal_code)')
        cur.execute('CREATE INDEX IF NOT EXISTS pro_directory_status_idx ON pro_directory (status)')
        for statement in NORMALIZED_DIRECTORY_SCHEMA:cur.execute(statement)
    conn.commit()

def status_for(row):
    configured=clean(row.get('verification_status'),60).lower()
    if not row.get('source_available',True):
        return ('OFFICIAL SOURCE AVAILABLE','Official source temporarily unavailable. Credential could not be rechecked at this time.')
    due=row.get('recheck_due_at')
    if due and due < datetime.now(timezone.utc):
        return ('VERIFICATION UPDATE NEEDED','The prior verification is stale and should be checked again at the official source.')
    if configured=='verified_from_official_source' and row.get('verified_at'):
        return ('VERIFIED FROM OFFICIAL SOURCE','The individual credential was checked against the linked official source.')
    if configured=='not_currently_confirmed':
        return ('NOT CURRENTLY CONFIRMED','VerifySweep does not currently have enough official-source evidence to confirm this credential.')
    if configured=='official_source_available':
        return ('OFFICIAL SOURCE AVAILABLE','Use the linked official source to check the individual credential.')
    return ('VERIFICATION NEEDED','This record requires an updated official-source verification.')

def rowdict(keys,row):return dict(zip(keys,row))

def company_status_label(status):return COMPANY_STATUS_LABELS.get(clean(status,60).lower(),'UNVERIFIED')

def company_key(item):
    domain=clean(item.get('normalized_domain'),240).lower()
    if not domain:
        try:domain=(urlparse(clean(item.get('website'),1000)).hostname or '').lower().removeprefix('www.')
        except ValueError:domain=''
    if domain:return ('domain',domain)
    phone=re.sub(r'\D','',clean(item.get('phone'),80))
    if phone:return ('phone',phone[-10:])
    return ('identity',clean(item.get('company'),200).lower(),clean(item.get('city') or item.get('hq_city'),120).lower(),clean(item.get('state') or item.get('hq_state'),40).lower())

def service_areas_for(item):
    values=item.get('service_areas') or []
    if not isinstance(values,list):return []
    return [clean(value,120) for value in values if clean(value,120)]

def service_counties_for(item):
    values=item.get('service_counties') or []
    if not isinstance(values,list):return []
    return [clean(value,120) for value in values if clean(value,120)]

def service_locations_for(item,fallback_state=''):
    rows=[];seen=set()
    for value in item.get('service_locations') or []:
        if not isinstance(value,dict):continue
        if clean(value.get('evidence_status'),40).lower() not in ('','active'):continue
        city=clean(value.get('city'),120);state=clean(value.get('state'),40) or fallback_state
        if not city:continue
        key=(city.lower(),state.lower())
        if key not in seen:rows.append({'city':city,'state':state});seen.add(key)
    for city in service_areas_for(item):
        key=(city.lower(),fallback_state.lower())
        if key not in seen:rows.append({'city':city,'state':fallback_state});seen.add(key)
    return rows

def reviewed_people_for_company(company,city,state,zipcode):
    people=[]
    for person in static_records():
        if clean(person.get('company'),200).lower()!=company.lower():continue
        same_zip=bool(zipcode) and clean(person.get('zip'),5)==zipcode
        same_place=clean(person.get('city'),120).lower()==city.lower() and clean(person.get('state'),40).lower()==state.lower()
        if same_zip or same_place:
            people.append(clean(person.get('holder'),200))
    return sorted(set(value for value in people if value),key=str.lower)

def search_static_companies(zipcode='',q='',city='',state='',verified_only=False):
    groups={};needle=clean(q,120).lower();needle_tokens=[part for part in re.split(r'[^a-z0-9]+',needle) if part];city_needle=clean(city,120).lower();state_needle=clean(state,40).lower()
    company_sources=[*static_company_records(),*national_company_records()]
    known={(clean(x.get('company'),200).lower(),clean(x.get('zip') or x.get('postal_code'),5),clean(x.get('city') or x.get('hq_city'),120).lower(),clean(x.get('state') or x.get('hq_state'),40).lower()) for x in company_sources}
    for person in static_records():
        identity=(clean(person.get('company'),200).lower(),clean(person.get('zip'),5),clean(person.get('city'),120).lower(),clean(person.get('state'),40).lower())
        if identity not in known:company_sources.append(person);known.add(identity)
    for source in company_sources:
        company=clean(source.get('company'),200);company_city=clean(source.get('city') or source.get('hq_city'),120);company_state=clean(source.get('state') or source.get('hq_state'),40);company_zip=clean(source.get('zip') or source.get('postal_code'),5)
        if clean(source.get('id'),160).startswith('national-') and not (source.get('website') or source.get('sources')):continue
        reviewed_people=reviewed_people_for_company(company,company_city,company_state,company_zip)
        service_locations=service_locations_for(source,company_state);service_areas=[location['city'] for location in service_locations];service_counties=service_counties_for(source);service_area_names=' '.join([*(location['city']+' '+location['state'] for location in service_locations),*service_counties])
        candidate_names=' '.join(clean(p.get('name_or_note'),300) for p in source.get('professional_candidates') or [] if isinstance(p,dict))
        reviewed_names=' '.join(reviewed_people)
        searchable=' '.join((company,company_city,company_state,company_zip,clean(source.get('website'),1000),service_area_names,candidate_names,reviewed_names)).lower()
        if needle_tokens and not all(token in searchable for token in needle_tokens):continue
        if verified_only and not reviewed_people:continue
        if zipcode and zipcode!=company_zip and zipcode not in (source.get('service_zips') or []):continue
        location_matches_city=[location for location in service_locations if location['city'].lower()==city_needle]
        if city_needle and city_needle!=company_city.lower() and not location_matches_city:continue
        if state_needle:
            office_matches=(not city_needle or city_needle==company_city.lower()) and state_needle==company_state.lower()
            service_matches=any((not city_needle or location['city'].lower()==city_needle) and location['state'].lower()==state_needle for location in service_locations)
            if not office_matches and not service_matches:continue
        key=company_key(source)
        item=groups.setdefault(key,{
          'id':clean(source.get('id'),160) or 'reviewed-company-'+re.sub(r'[^a-z0-9]+','-',company.lower()).strip('-')+'-'+company_zip,
          'company':company,'website':clean(source.get('website'),1000),'phone':clean(source.get('phone'),80),
          'city':company_city,'state':company_state,'zip':company_zip,'public_status':'unverified','claim_status':'unclaimed',
          'last_reviewed_at':clean(source.get('last_checked_at') or source.get('captured_at'),40) or None,'verification_due_at':None,
          'source_type':clean(source.get('source_type'),80) or 'directory_research_record','source_url':clean(source.get('source_url') or source.get('source') or next((v.get('url') for v in source.get('sources') or [] if isinstance(v,dict) and v.get('url')),''),1000),
          'service_areas':service_areas,'service_locations':service_locations,'service_area_labels':[location['city']+', '+location['state'] if location['state'] else location['city'] for location in service_locations],
          'service_counties':service_counties,'service_area_source_url':clean(source.get('service_area_source_url'),1000),
          'history_note':clean(source.get('history_note'),500),'recognition_source_url':clean(source.get('recognition_source_url'),1000),
          'display_status':'UNVERIFIED',
          'company_claims':source.get('company_claims') or [],'professional_candidates':source.get('professional_candidates') or [],
          'sources':source.get('sources') or [],'reviewed_professional_names':reviewed_people,
          'verified_professional_count':len(reviewed_people)
        })
        checked=clean(source.get('last_checked_at') or source.get('captured_at'),40)
        if checked and (not item['last_reviewed_at'] or checked>item['last_reviewed_at']):item['last_reviewed_at']=checked
        if not item['website'] and source.get('website'):item['website']=clean(source.get('website'),1000)
        if not item['phone'] and source.get('phone'):item['phone']=clean(source.get('phone'),80)
        if not item['source_url'] and (source.get('source_url') or source.get('source')):item['source_url']=clean(source.get('source_url') or source.get('source'),1000)
        if service_areas:item['service_areas']=sorted(set([*item.get('service_areas',[]),*service_areas]),key=str.lower)
        if service_locations:
            combined={(location['city'].lower(),location['state'].lower()):location for location in [*item.get('service_locations',[]),*service_locations]}
            item['service_locations']=sorted(combined.values(),key=lambda location:(location['state'].lower(),location['city'].lower()))
            item['service_area_labels']=[location['city']+', '+location['state'] if location['state'] else location['city'] for location in item['service_locations']]
        if service_counties:item['service_counties']=sorted(set([*item.get('service_counties',[]),*service_counties]),key=str.lower)
        for field in ('service_area_source_url','history_note','recognition_source_url'):
            if not item.get(field) and source.get(field):item[field]=clean(source.get(field),1000 if field.endswith('_url') else 500)
        for field in ('company_claims','professional_candidates','sources'):
            incoming=source.get(field) or []
            if incoming:
                merged={json.dumps(value,sort_keys=True,default=str):value for value in [*(item.get(field) or []),*incoming]}
                item[field]=list(merged.values())
        if reviewed_people:
            item['reviewed_professional_names']=sorted(set([*(item.get('reviewed_professional_names') or []),*reviewed_people]),key=str.lower)
            item['verified_professional_count']=len(item['reviewed_professional_names'])
        matched=next((location for location in service_locations if location['city'].lower()==city_needle and (not state_needle or location['state'].lower()==state_needle)),None) if city_needle else None
        if matched:item['matched_service_area']=matched['city'];item['matched_service_state']=matched['state']
        exact_company=bool(needle) and needle==company.lower()
        starts_company=bool(needle) and company.lower().startswith(needle)
        if exact_company:rank,reason=0,'Exact company match'
        elif starts_company:rank,reason=1,'Company name match'
        elif needle and reviewed_names and all(token in reviewed_names.lower() for token in needle_tokens):rank,reason=2,'Reviewed professional match'
        elif needle and candidate_names and all(token in candidate_names.lower() for token in needle_tokens):rank,reason=3,'Named professional research match'
        elif city_needle and company_city.lower()==city_needle:rank,reason=4,'Business location match'
        elif matched:rank,reason=5,'Published service area match'
        elif state_needle and company_state.lower()==state_needle:rank,reason=6,'Business state match'
        elif needle:rank,reason=7,'Company or directory information match'
        else:rank,reason=8,'Directory match'
        if item.get('match_rank') is None or rank<item['match_rank']:
            item['match_rank']=rank;item['match_reason']=reason
    return sorted(groups.values(),key=lambda item:(item.get('match_rank',99),item['company'].lower()))

def company_professionals(company):
    rows=[]
    for source in static_records():
        same_name=clean(source.get('company'),200).lower()==clean(company.get('company'),200).lower()
        same_location=clean(source.get('zip'),5)==clean(company.get('zip'),5) or (clean(source.get('city'),120).lower()==clean(company.get('city'),120).lower() and clean(source.get('state'),40).lower()==clean(company.get('state'),40).lower())
        if not (same_name and same_location):continue
        item={k:source.get(k) for k in ('id','holder','credential','credential_type','issuer','source','verified_at','last_checked_at','recheck_due_at','source_available')}
        item['display_status'],item['status_note']=static_status(source);rows.append(item)
    return sorted(rows,key=lambda item:(clean(item.get('holder'),200),clean(item.get('credential'),200)))

def detail_company(identifier):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',identifier or ''):return None,False
    rows,connected=search_companies_db()
    company=next((item for item in rows if str(item.get('id'))==str(identifier)),None)
    if not company:return None,connected
    company=dict(company);company['professionals']=company_professionals(company)
    return company,connected

def search_companies_db(zipcode='',q='',city='',state='',verified_only=False):
    fallback=search_static_companies(zipcode,q,city,state,verified_only)
    conn=dbconn()
    if not conn:return fallback,False
    try:
        ensure(conn)
        where=['c.public_status=ANY(%s)'];params=[list(PUBLIC_COMPANY_STATUSES)]
        if q:
            where.append('''(c.canonical_name ILIKE %s OR COALESCE(c.normalized_domain,'') ILIKE %s OR COALESCE(c.city,'') ILIKE %s OR COALESCE(c.state,'') ILIKE %s OR COALESCE(c.postal_code,'') ILIKE %s OR EXISTS (
              SELECT 1 FROM directory_professionals p WHERE p.company_id=c.id AND p.professional_name ILIKE %s
            ))''')
            like=f'%{q}%';params.extend([like,like,like,like,like,like])
        if zipcode:
            where.append('''(c.postal_code=%s OR EXISTS (
              SELECT 1 FROM directory_service_areas sa WHERE sa.company_id=c.id AND sa.postal_code=%s
            ))''');params.extend([zipcode,zipcode])
        if city:
            where.append('''(c.city ILIKE %s OR EXISTS (
              SELECT 1 FROM directory_service_areas sa WHERE sa.company_id=c.id AND sa.city ILIKE %s
            ))''');params.extend([city,city])
        if state:where.append('UPPER(c.state)=UPPER(%s)');params.append(state)
        if verified_only:
            where.append('''EXISTS (SELECT 1 FROM directory_professionals p JOIN directory_credentials cr ON cr.professional_id=p.id
              WHERE p.company_id=c.id AND p.public_state='active' AND cr.verification_status='verified_from_official_source')''')
        with conn.cursor() as cur:
            cur.execute(f'''SELECT c.id,c.canonical_name,c.website,c.phone,c.city,c.state,c.postal_code,
              c.public_status,c.claim_status,c.last_reviewed_at,c.verification_due_at
              FROM directory_companies c WHERE {' AND '.join(where)}
              ORDER BY CASE c.public_status WHEN 'verified' THEN 0 WHEN 'verification_in_progress' THEN 1 ELSE 2 END,
              c.canonical_name LIMIT 100''',params)
            keys=['id','company','website','phone','city','state','zip','public_status','claim_status','last_reviewed_at','verification_due_at']
            rows=[]
            for raw in cur.fetchall():
                item=rowdict(keys,raw);item['display_status']=company_status_label(item.get('public_status'));rows.append(item)
            seen={company_key(item) for item in rows}
            rows.extend(item for item in fallback if company_key(item) not in seen)
            rows.sort(key=lambda item:(0 if item.get('public_status')=='verified' else 1,clean(item.get('company'),200).lower()))
            return rows,True
    finally:conn.close()

def search_db(zipcode,q='',radius=25):
    conn=dbconn()
    if not conn:return search_static(zipcode,q,radius)
    try:
        ensure(conn)
        with conn.cursor() as cur:
            origin=None
            if zipcode:
                cur.execute('SELECT latitude,longitude FROM zip_centroids WHERE postal_code=%s',(zipcode,));origin=cur.fetchone()
            params=[];where=['status=%s'];params.append(PUBLISHED_STATUS)
            if q:
                where.append('(company ILIKE %s OR professional_name ILIKE %s OR city ILIKE %s)');like=f'%{q}%';params.extend([like,like,like])
            distance_sql='NULL::double precision'
            if zipcode and origin:
                distance_sql='''CASE WHEN latitude IS NULL OR longitude IS NULL THEN NULL ELSE
                  3958.7613 * 2 * asin(sqrt(power(sin(radians(latitude-%s)/2),2) +
                  cos(radians(%s))*cos(radians(latitude))*power(sin(radians(longitude-%s)/2),2))) END'''
                params=[origin[0],origin[0],origin[1]]+params
                where.append('''(postal_code=%s OR %s=ANY(service_zips) OR (latitude IS NOT NULL AND longitude IS NOT NULL AND
                  3958.7613 * 2 * asin(sqrt(power(sin(radians(latitude-%s)/2),2) + cos(radians(%s))*cos(radians(latitude))*power(sin(radians(longitude-%s)/2),2))) <= %s))''')
                params.extend([zipcode,zipcode,origin[0],origin[0],origin[1],radius])
            elif zipcode:
                where.append('(postal_code=%s OR %s=ANY(service_zips))');params.extend([zipcode,zipcode])
            cur.execute(f'''SELECT id,company,professional_name,credential,COALESCE(credential_type,credential),issuer,
              credential_source,city,state,postal_code,website,phone,verification_status,verified_at,
              source_last_checked_at,recheck_due_at,source_available,source_note,{distance_sql} AS distance
              FROM pro_directory WHERE {' AND '.join(where)} ORDER BY professional_name,company,credential LIMIT 100''',params)
            keys=['id','company','holder','credential','credential_type','issuer','source','city','state','zip','website','phone','verification_status','verified_at','last_checked_at','recheck_due_at','source_available','source_note','distance']
            rows=[]
            for raw in cur.fetchall():
                item=rowdict(keys,raw);label,note=status_for(item);item['display_status']=label;item['status_note']=note
                if item['distance'] is not None:item['distance']=round(float(item['distance']),1)
                rows.append(item)
            fallback,fallback_geo=search_static(zipcode,q,radius)
            seen={(clean(r.get('issuer'),80).lower(),clean(r.get('source'),1000).lower()) for r in rows}
            rows.extend(r for r in fallback if (clean(r.get('issuer'),80).lower(),clean(r.get('source'),1000).lower()) not in seen)
            rows.sort(key=lambda r:(r.get('holder',''),r.get('company',''),r.get('credential','')))
            return rows,bool(origin) or fallback_geo
    finally:conn.close()

def detail_db(identifier):
    conn=dbconn()
    if not conn:return detail_static(identifier)
    try:
        ensure(conn)
        with conn.cursor() as cur:
            cur.execute('''SELECT id,company,professional_name,credential,COALESCE(credential_type,credential),issuer,
              credential_source,city,state,postal_code,website,phone,verification_status,verified_at,
              source_last_checked_at,recheck_due_at,source_available,source_note,NULL::double precision
              FROM pro_directory WHERE id=%s AND status=%s''',(identifier,PUBLISHED_STATUS));raw=cur.fetchone()
            if not raw:return detail_static(identifier)
            keys=['id','company','holder','credential','credential_type','issuer','source','city','state','zip','website','phone','verification_status','verified_at','last_checked_at','recheck_due_at','source_available','source_note','distance']
            item=rowdict(keys,raw);item['display_status'],item['status_note']=status_for(item);return item
    finally:conn.close()

def submit_db(p):
    conn=dbconn()
    if not conn:raise RuntimeError('Directory database is not configured.')
    try:
        ensure(conn);service=[clean(x,5) for x in (p.get('service_zips') or []) if valid_zip(clean(x,5))][:100]
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO pro_directory(company,professional_name,credential,credential_type,issuer,credential_source,
              city,state,postal_code,service_zips,website,phone,status,verification_status,source_available)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending','verification_needed',TRUE) RETURNING id''',(
              clean(p.get('company'),200),clean(p.get('professional_name'),200),clean(p.get('credential'),200),clean(p.get('credential_type') or p.get('credential'),200),
              clean(p.get('issuer'),100),clean(p.get('credential_source'),1000),clean(p.get('city'),120),clean(p.get('state'),40),clean(p.get('postal_code'),5),service,
              clean(p.get('website'),1000),clean(p.get('phone'),80)))
            rid=cur.fetchone()[0]
        conn.commit();return rid
    finally:conn.close()

class handler(BaseHTTPRequestHandler):
    def sendj(self,code,p):
        b=json.dumps(p,default=str).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_OPTIONS(self):self.send_response(204);self.send_header('Allow','GET, POST, OPTIONS');self.end_headers()
    def do_GET(self):
        try:
            qs=parse_qs(urlparse(self.path).query);view=clean((qs.get('view') or ['professionals'])[0],30).lower()
            if view=='companies':
                identifier=clean((qs.get('id') or [''])[0],160)
                if identifier:
                    result,connected=detail_company(identifier)
                    return self.sendj(200 if result else 404,{'result':result,'database_connected':connected,'public_business_fields_only':True} if result else {'error':'Company record not found.'})
                z=clean((qs.get('zip') or [''])[0],5);q=clean((qs.get('q') or [''])[0],120);city=clean((qs.get('city') or [''])[0],120);state=clean((qs.get('state') or [''])[0],40);verified_only=clean((qs.get('verified') or [''])[0],5) in ('1','true','yes')
                if z and not valid_zip(z):return self.sendj(400,{'error':'Enter a valid 5-digit ZIP code.'})
                if not any((z,q,city,state,verified_only)):return self.sendj(400,{'error':'Search by ZIP, city, state, business name, professional name, or reviewed credential record.'})
                results,connected=search_companies_db(z,q,city,state,verified_only)
                resolved=resolve_us_zip(z) if z and not (city or state) else None
                if resolved:
                    nearby,nearby_connected=search_companies_db('',q,resolved['city'],resolved['state'],verified_only)
                    existing={company_key(item) for item in results}
                    results.extend(item for item in nearby if company_key(item) not in existing)
                    results.sort(key=lambda item:(0 if item.get('matched_service_area') else 1,clean(item.get('company'),200).lower()))
                    connected=connected or nearby_connected
                return self.sendj(200,{'results':results,'count':len(results),'database_connected':connected,'public_business_fields_only':True,
                  'resolved_location':resolved,
                  'coverage_notice':'Directory coverage varies by location and is not comprehensive. Missing results do not establish that no qualified professional serves an area.',
                  'note':'UNVERIFIED means VerifySweep has not completed verification. It does not indicate fraud, misconduct, incompetence, or wrongdoing.'})
            if view!='professionals':return self.sendj(400,{'error':'Choose a supported directory view.'})
            identifier=clean((qs.get('id') or [''])[0],30)
            if identifier:
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identifier):return self.sendj(400,{'error':'Invalid professional record.'})
                result=detail_db(int(identifier) if identifier.isdigit() else identifier);return self.sendj(200 if result else 404,{'result':result} if result else {'error':'Professional record not found.'})
            z=clean((qs.get('zip') or [''])[0],5);q=clean((qs.get('q') or [''])[0],120)
            try:radius=int((qs.get('radius') or ['25'])[0])
            except:radius=25
            if z and not valid_zip(z):return self.sendj(400,{'error':'Enter a valid 5-digit ZIP code.'})
            if radius not in ALLOWED_RADII:return self.sendj(400,{'error':'Choose a supported search radius.'})
            results,geo=search_db(z,q,radius)
            self.sendj(200,{'results':results,'count':len(results),'verified_records_only':True,'database_connected':bool(DB),'radius':radius,
              'distance_search_available':geo,'official_sources':OFFICIAL_SOURCES,
              'note':'VerifySweep returns only reviewed records. Always use the linked official issuer directory to independently confirm the named individual and current credential.'})
        except Exception:self.sendj(500,{'error':'Directory search is temporarily unavailable. Use the official CSIA or NFI directory links.'})
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<2 or n>30000:raise ValueError('Invalid request.')
            p=json.loads(self.rfile.read(n).decode());required=['company','professional_name','credential','issuer','credential_source','postal_code']
            if any(not clean(p.get(k)) for k in required):raise ValueError('Company, professional name, credential, issuer, verification source, and ZIP are required.')
            if not valid_zip(clean(p.get('postal_code'),5)):raise ValueError('Enter a valid 5-digit ZIP code.')
            if not valid_http_url(clean(p.get('credential_source'),1000)):raise ValueError('Use a valid official-source URL.')
            for field in ('website',):
                if clean(p.get(field)) and not valid_http_url(clean(p.get(field),1000)):raise ValueError('Use a valid public business website URL.')
            rid=submit_db(p);self.sendj(201,{'id':rid,'status':'pending','message':'Profile submitted for VerifySweep review. It will not appear in homeowner search until the individual credential is verified.'})
        except (ValueError,json.JSONDecodeError) as e:self.sendj(400,{'error':str(e)})
        except RuntimeError as e:self.sendj(503,{'error':str(e)})
        except Exception:self.sendj(500,{'error':'The directory submission could not be saved.'})
