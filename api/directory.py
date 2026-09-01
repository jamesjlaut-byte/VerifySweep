import json, math, os, re
from functools import lru_cache
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB=os.environ.get('DATABASE_URL','')
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_RECORDS=os.path.join(ROOT,'data','certified-professionals.json')
ZIP_CENTROIDS=os.path.join(ROOT,'data','us-zcta-centroids.tsv')
PUBLISHED_STATUS='verified'
ALLOWED_RADII={10,25,50,75,100}
OFFICIAL_SOURCES={
  'csia':'https://web.csia.org/CSIA-Certified',
  'nfi':'https://www.nficertified.org/search-instructor/'
}

def clean(v,n=500): return re.sub(r'\s+',' ',str(v or '')).strip()[:n]
def valid_zip(z): return bool(re.fullmatch(r'\d{5}',z or ''))
def valid_http_url(v):
    try:return urlparse(v).scheme in ('http','https') and bool(urlparse(v).hostname)
    except:return False

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
            qs=parse_qs(urlparse(self.path).query);identifier=clean((qs.get('id') or [''])[0],30)
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
