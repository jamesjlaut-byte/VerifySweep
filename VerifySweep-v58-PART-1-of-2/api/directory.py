import json, os, re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB=os.environ.get('DATABASE_URL','')

def clean(v,n=500): return re.sub(r'\s+',' ',str(v or '')).strip()[:n]
def valid_zip(z): return bool(re.fullmatch(r'\d{5}',z or ''))
def valid_http_url(v, optional=False):
    v=clean(v,1000)
    if not v:return optional
    try:
        u=urlparse(v)
        return u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password
    except ValueError:return False

def dbconn():
    if not DB: return None
    import psycopg
    return psycopg.connect(DB,connect_timeout=5)

def ensure(conn):
    with conn.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS pro_directory (
          id BIGSERIAL PRIMARY KEY,
          company TEXT NOT NULL,
          professional_name TEXT NOT NULL,
          credential TEXT NOT NULL,
          issuer TEXT NOT NULL,
          credential_source TEXT NOT NULL,
          city TEXT,
          state TEXT,
          postal_code TEXT,
          service_zips TEXT[] DEFAULT '{}',
          website TEXT,
          phone TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          verified_at TIMESTAMPTZ
        )''')
        cur.execute('ALTER TABLE pro_directory ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ')
        cur.execute('CREATE INDEX IF NOT EXISTS pro_directory_zip_idx ON pro_directory (postal_code)')
        cur.execute('CREATE INDEX IF NOT EXISTS pro_directory_status_idx ON pro_directory (status)')
    conn.commit()

def search_db(zipcode,q=''):
    conn=dbconn()
    if not conn:return []
    try:
        ensure(conn)
        with conn.cursor() as cur:
            params=[]; where=["status='verified'"]
            if zipcode:
                where.append('(postal_code=%s OR %s=ANY(service_zips))');params.extend([zipcode,zipcode])
            if q:
                where.append('(company ILIKE %s OR professional_name ILIKE %s OR city ILIKE %s)');like=f'%{q}%';params.extend([like,like,like])
            cur.execute(f'''SELECT id,company,professional_name,credential,issuer,credential_source,city,state,postal_code,website,phone,verified_at
                            FROM pro_directory WHERE {' AND '.join(where)} ORDER BY company,professional_name LIMIT 50''',params)
            rows=cur.fetchall()
            keys=['id','company','holder','credential','issuer','source','city','state','zip','website','phone','verified_at']
            return [dict(zip(keys,r)) for r in rows]
    finally: conn.close()

def submit_db(p):
    conn=dbconn()
    if not conn: raise RuntimeError('Directory database is not configured.')
    try:
        ensure(conn)
        service=[x for x in (p.get('service_zips') or []) if valid_zip(clean(x,5))][:100]
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO pro_directory(company,professional_name,credential,issuer,credential_source,city,state,postal_code,service_zips,website,phone,status)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending') RETURNING id''',(
                clean(p.get('company'),200),clean(p.get('professional_name'),200),clean(p.get('credential'),200),clean(p.get('issuer'),100),clean(p.get('credential_source'),1000),clean(p.get('city'),120),clean(p.get('state'),40),clean(p.get('postal_code'),5),service,clean(p.get('website'),1000),clean(p.get('phone'),80)))
            rid=cur.fetchone()[0]
        conn.commit();return rid
    finally: conn.close()

class handler(BaseHTTPRequestHandler):
    def sendj(self,code,p):
        b=json.dumps(p,default=str).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_OPTIONS(self):self.send_response(204);self.send_header('Allow','GET, POST, OPTIONS');self.end_headers()
    def do_GET(self):
        try:
            qs=parse_qs(urlparse(self.path).query); z=clean((qs.get('zip') or [''])[0],5); q=clean((qs.get('q') or [''])[0],120)
            if z and not valid_zip(z): return self.sendj(400,{'error':'Enter a valid 5-digit ZIP code.'})
            results=search_db(z,q)
            self.sendj(200,{'results':results,'count':len(results),'verified_only':True,'database_connected':bool(DB),
              'official_sources':{'csia':'https://web.csia.org/CSIA-Certified','nfi':'https://www.nficertified.org/public/find-an-nfi-pro/','fire':'https://www.f-i-r-e-service.com/certified_inspectors.php','ncsg_ccp':'https://ncsg.org/find-a-sweep/find-a-certified-sweep'},
              'note':'VerifySweep returns only records marked verified in its directory. Use the linked issuer directory to independently confirm current credential status.'})
        except Exception:self.sendj(500,{'error':'Directory search is temporarily unavailable. Use the official CSIA or NFI directory links.'})
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<2 or n>30000: raise ValueError('Invalid request.')
            p=json.loads(self.rfile.read(n).decode())
            if not isinstance(p,dict):raise ValueError('Submission data is required.')
            required=['company','professional_name','credential','issuer','credential_source','postal_code']
            if any(not clean(p.get(k)) for k in required):raise ValueError('Company, professional name, credential, issuer, verification source, and ZIP are required.')
            if not valid_zip(clean(p.get('postal_code'),5)):raise ValueError('Enter a valid 5-digit ZIP code.')
            if not valid_http_url(p.get('credential_source')):raise ValueError('Enter a valid http or https credential verification source URL.')
            if clean(p.get('website')) and not valid_http_url(p.get('website'),optional=True):raise ValueError('Enter a valid http or https company website URL.')
            rid=submit_db(p);self.sendj(201,{'id':rid,'status':'pending','message':'Profile submitted for VerifySweep review. It will not appear in homeowner search until verified.'})
        except (ValueError,json.JSONDecodeError) as e:self.sendj(400,{'error':str(e)})
        except RuntimeError as e:self.sendj(503,{'error':str(e)})
        except Exception:self.sendj(500,{'error':'The directory submission could not be saved.'})
