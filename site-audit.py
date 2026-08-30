from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin, urldefrag
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, re, socket, ipaddress

MAX_BYTES = 1_250_000
MAX_PAGES = 6
MAX_LINK_CHECKS = 18
UA = 'VerifySweep-SiteAudit/1.2 (+https://www.verifysweep.com)'

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=''; self._in_title=False; self.meta=[]; self.links=[]; self.images=[]
        self.h1=[]; self.h2=[]; self._heading=None; self._heading_text=[]
        self.scripts=[]; self.text_parts=[]; self._skip_text=0
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs); tag=tag.lower()
        if tag=='title': self._in_title=True
        if tag in ('script','style','noscript'): self._skip_text += 1
        if tag=='meta': self.meta.append(attrs)
        if tag=='a' and attrs.get('href'): self.links.append(attrs.get('href'))
        if tag=='img': self.images.append(attrs)
        if tag in ('h1','h2'): self._heading=tag; self._heading_text=[]
        if tag=='script' and attrs.get('type','').lower()=='application/ld+json':
            self.scripts.append('')
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag=='title': self._in_title=False
        if tag in ('script','style','noscript') and self._skip_text: self._skip_text -= 1
        if self._heading==tag:
            txt=' '.join(''.join(self._heading_text).split())
            (self.h1 if tag=='h1' else self.h2).append(txt)
            self._heading=None; self._heading_text=[]
    def handle_data(self, data):
        if self._in_title: self.title += data
        if self._heading: self._heading_text.append(data)
        if self.scripts and self._skip_text and getattr(self,'lasttag',None)=='script':
            # Best-effort JSON-LD capture; HTMLParser doesn't expose attrs here.
            pass
        if not self._skip_text:
            t=' '.join(data.split())
            if t: self.text_parts.append(t)


def normalize_url(raw):
    raw=(raw or '').strip()
    if not raw: raise ValueError('Enter a website URL.')
    if '://' not in raw: raw='https://'+raw
    p=urlparse(raw)
    if p.scheme not in ('http','https') or not p.hostname: raise ValueError('Use a valid http or https website URL.')
    return raw


def assert_public_host(url):
    p=urlparse(url); host=p.hostname
    if not host: raise ValueError('Invalid hostname.')
    if host.lower()=='localhost' or host.lower().endswith('.local'): raise ValueError('Private/local addresses cannot be audited.')
    try: infos=socket.getaddrinfo(host,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
    except socket.gaierror: raise ValueError('The website hostname could not be resolved.')
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError('Private or non-public network addresses cannot be audited.')

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        absolute=urljoin(req.full_url,newurl); assert_public_host(absolute)
        return super().redirect_request(req,fp,code,msg,headers,absolute)


def fetch(url,timeout=6,limit=MAX_BYTES):
    assert_public_host(url)
    req=Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml;q=0.9,*/*;q=0.4'})
    with build_opener(SafeRedirect()).open(req,timeout=timeout) as r:
        final=r.geturl(); assert_public_host(final); ctype=r.headers.get('Content-Type','')
        data=r.read(limit+1)
        if len(data)>limit: raise ValueError('A page is too large for this audit.')
        return final,getattr(r,'status',200),ctype,data.decode(r.headers.get_content_charset() or 'utf-8',errors='replace')


def status_check(url,timeout=4):
    try:
        assert_public_host(url)
        req=Request(url,headers={'User-Agent':UA},method='GET')
        with build_opener(SafeRedirect()).open(req,timeout=timeout) as r: return getattr(r,'status',200),r.geturl()
    except HTTPError as e: return e.code,url
    except Exception: return 0,url


def meta_value(p,key,value):
    value=value.lower()
    for m in p.meta:
        if m.get(key,'').lower()==value: return (m.get('content') or '').strip()
    return ''


def canonical_from(html):
    m=re.search(r'<link[^>]+rel=["\'][^"\']*canonical[^"\']*["\'][^>]+href=["\']([^"\']+)',html,re.I)
    if not m: m=re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\'][^"\']*canonical',html,re.I)
    return m.group(1).strip() if m else ''


def jsonld_types(html):
    out=[]
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',html,re.I|re.S):
        try:
            data=json.loads(raw.strip())
            objs=data if isinstance(data,list) else [data]
            for obj in objs:
                if isinstance(obj,dict):
                    if isinstance(obj.get('@graph'),list): objs += [x for x in obj['@graph'] if isinstance(x,dict)]
                    t=obj.get('@type')
                    if isinstance(t,list): out.extend(str(x) for x in t)
                    elif t: out.append(str(t))
        except Exception: continue
    return sorted(set(out))


def clean_internal(base_url,href,host):
    if not href or href.startswith(('#','mailto:','tel:','javascript:','data:')): return None
    u=urljoin(base_url,href); u,_=urldefrag(u); p=urlparse(u)
    if p.scheme not in ('http','https') or p.hostname!=host: return None
    # Ignore obvious files that do not need page SEO analysis.
    if re.search(r'\.(?:jpg|jpeg|png|gif|webp|svg|pdf|zip|css|js|xml|txt|ico|mp4|mov)(?:$|\?)',p.path,re.I): return None
    return u


def analyze_page(url,status,html):
    p=PageParser(); p.feed(html)
    title=' '.join(p.title.split()).strip(); desc=meta_value(p,'name','description')
    robots=meta_value(p,'name','robots').lower(); viewport=meta_value(p,'name','viewport')
    canonical=canonical_from(html); words=len(re.findall(r"\b[\w'-]+\b",' '.join(p.text_parts)))
    missing_alt=sum(1 for img in p.images if 'alt' not in img or img.get('alt') is None)
    types=jsonld_types(html)
    phones=sorted(set(re.findall(r'(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)', ' '.join(p.text_parts))))[:5]
    path=urlparse(url).path or '/'
    issues=[]
    if not title: issues.append('Missing title')
    elif not 30<=len(title)<=65: issues.append('Title length')
    if not desc: issues.append('Missing meta description')
    elif not 70<=len(desc)<=170: issues.append('Meta description length')
    if len(p.h1)!=1: issues.append('H1 count')
    if 'noindex' in robots: issues.append('Noindex')
    if not canonical: issues.append('Missing canonical')
    if words<200: issues.append('Thin content')
    return {'url':url,'path':path,'status':status,'title':title,'title_length':len(title),'description':desc,'description_length':len(desc),
            'h1':p.h1,'h2_count':len(p.h2),'word_count':words,'images':len(p.images),'missing_alt':missing_alt,
            'viewport':bool(viewport),'canonical':canonical,'robots':robots,'schema_types':types,'phones':phones,'links':p.links,'issues':issues}


def result_item(name,status,detail,suggestion='',priority='medium'):
    return {'name':name,'status':status,'detail':detail,'suggestion':suggestion,'priority':priority}


def audit(raw_url):
    requested=normalize_url(raw_url)
    final,status,ctype,html=fetch(requested)
    if 'html' not in ctype.lower() and '<html' not in html[:1000].lower(): raise ValueError('That URL did not return an HTML webpage.')
    host=urlparse(final).hostname; root=f'{urlparse(final).scheme}://{urlparse(final).netloc}'

    home=analyze_page(final,status,html)
    pages=[home]; seen={urldefrag(final)[0]}; queue=[]
    for href in home['links']:
        u=clean_internal(final,href,host)
        if u and u not in seen: queue.append(u)

    while queue and len(pages)<MAX_PAGES:
        u=queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            fu,st,ct,body=fetch(u,timeout=5)
            if ('html' not in ct.lower() and '<html' not in body[:1000].lower()): continue
            page=analyze_page(fu,st,body); pages.append(page)
            for href in page['links']:
                nxt=clean_internal(fu,href,host)
                if nxt and nxt not in seen and nxt not in queue: queue.append(nxt)
        except Exception: continue

    # Internal-link inventory and status sampling.
    internal_urls=[]
    for page in pages:
        for href in page['links']:
            u=clean_internal(page['url'],href,host)
            if u and u not in internal_urls: internal_urls.append(u)
    checked=internal_urls[:MAX_LINK_CHECKS]; broken=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut={ex.submit(status_check,u):u for u in checked}
        for f in as_completed(fut):
            u=fut[f]
            try:
                st,_=f.result()
                if st==0 or st>=400: broken.append({'url':u,'status':st})
            except Exception: broken.append({'url':u,'status':0})

    titles={}; descs={}
    for p in pages:
        if p['title']: titles.setdefault(p['title'].strip().lower(),[]).append(p['url'])
        if p['description']: descs.setdefault(p['description'].strip().lower(),[]).append(p['url'])
    dup_titles=[v for v in titles.values() if len(v)>1]; dup_descs=[v for v in descs.values() if len(v)>1]
    missing_titles=sum(1 for p in pages if not p['title']); missing_desc=sum(1 for p in pages if not p['description'])
    bad_h1=sum(1 for p in pages if len(p['h1'])!=1); thin=sum(1 for p in pages if p['word_count']<200)
    no_schema=sum(1 for p in pages if not p['schema_types']); alt_missing=sum(p['missing_alt'] for p in pages)
    phone_sets={tuple(p['phones']) for p in pages if p['phones']}; inconsistent_phone=len(phone_sets)>1

    checks=[]
    checks.append(result_item('HTTPS','pass' if final.startswith('https://') else 'warn','Site loads over HTTPS.' if final.startswith('https://') else 'Site is not using HTTPS.','Force HTTPS across the entire website.' if not final.startswith('https://') else '', 'high'))
    checks.append(result_item('Page titles','pass' if not missing_titles and not dup_titles else ('fail' if missing_titles else 'warn'),f'{len(pages)-missing_titles}/{len(pages)} crawled pages have titles; {len(dup_titles)} duplicate title group(s).','Give every important page a unique title built around that page’s service or location intent.' if missing_titles or dup_titles else '', 'high'))
    checks.append(result_item('Meta descriptions','pass' if not missing_desc and not dup_descs else 'warn',f'{len(pages)-missing_desc}/{len(pages)} crawled pages have descriptions; {len(dup_descs)} duplicate description group(s).','Write unique descriptions for service and city pages. Avoid copying the same description across locations.' if missing_desc or dup_descs else '', 'medium'))
    checks.append(result_item('H1 structure','pass' if bad_h1==0 else 'warn',f'{bad_h1} of {len(pages)} crawled pages do not have exactly one H1.','Use one clear page-level H1 on each indexable service, location and education page.' if bad_h1 else '', 'medium'))
    checks.append(result_item('Broken internal links','pass' if not broken else 'fail',f'Checked {len(checked)} internal URLs; found {len(broken)} possible broken link(s).','Repair or redirect broken internal links so visitors and crawlers do not hit dead ends.' if broken else '', 'high'))
    checks.append(result_item('Structured data','pass' if no_schema==0 else 'warn',f'{len(pages)-no_schema}/{len(pages)} crawled pages contain JSON-LD schema.','Use accurate LocalBusiness/Organization schema on core pages and Service/Article/FAQ schema only where the page content supports it.' if no_schema else '', 'medium'))
    checks.append(result_item('Image accessibility','pass' if alt_missing==0 else 'warn',f'{alt_missing} image(s) across crawled pages are missing an alt attribute.','Add descriptive alt text to meaningful chimney/fireplace images; decorative images should use alt="".' if alt_missing else '', 'low'))
    checks.append(result_item('Content depth','pass' if thin==0 else 'warn',f'{thin} of {len(pages)} crawled pages have fewer than 200 visible words.','Expand thin pages only with useful original content: service process, inspection scope, common problems, qualifications, service-area specifics and FAQs.' if thin else '', 'medium'))
    checks.append(result_item('Phone consistency','warn' if inconsistent_phone else 'pass','Different phone-number sets were detected across crawled pages.' if inconsistent_phone else 'No obvious phone-number inconsistency found in the crawled sample.','Make sure location-specific numbers are intentional and clearly associated with the correct office/service area; keep primary NAP information consistent.' if inconsistent_phone else '', 'medium'))
    robots_ok=status_check(urljoin(root,'/robots.txt'))[0] in range(200,400)
    sitemap_ok=status_check(urljoin(root,'/sitemap.xml'))[0] in range(200,400)
    checks.append(result_item('robots.txt','pass' if robots_ok else 'warn','robots.txt is reachable.' if robots_ok else 'robots.txt was not found or could not be reached.','Publish a valid robots.txt and reference the XML sitemap.' if not robots_ok else '', 'medium'))
    checks.append(result_item('XML sitemap','pass' if sitemap_ok else 'warn','sitemap.xml is reachable.' if sitemap_ok else 'sitemap.xml was not found or could not be reached.','Publish an XML sitemap and submit it in Google Search Console.' if not sitemap_ok else '', 'medium'))

    # Chimney-industry focused prompts, without pretending these are ranking factors.
    all_text=(' '.join([p['title']+' '+' '.join(p['h1']) for p in pages])).lower()
    chimney_terms=['chimney','fireplace','sweep','inspection','repair']
    coverage=sum(1 for t in chimney_terms if t in all_text)
    checks.append(result_item('Service-topic clarity','pass' if coverage>=3 else 'warn',f'{coverage}/5 core chimney-service terms appear in crawled titles/H1s.','Make important service pages unmistakably about the exact service offered—such as chimney inspection, chimney sweep, fireplace repair, relining or dryer vent cleaning—without keyword stuffing.' if coverage<3 else '', 'medium'))

    weights={'pass':1.0,'warn':0.55,'fail':0.0}
    score=round(100*sum(weights[x['status']] for x in checks)/len(checks))
    pri={'high':0,'medium':1,'low':2}
    recommendations=sorted([x for x in checks if x['status']!='pass' and x['suggestion']],key=lambda x:(pri.get(x['priority'],9),0 if x['status']=='fail' else 1))[:8]
    return {
        'requested_url':requested,'final_url':final,'http_status':status,'score':score,
        'crawl':{'pages_crawled':len(pages),'page_limit':MAX_PAGES,'internal_links_found':len(internal_urls),'links_checked':len(checked),'broken_links':broken},
        'summary':{'title':home['title'],'description':home['description'],'h1_count':len(home['h1']),'word_count':home['word_count'],'internal_links':len(internal_urls),'images':sum(p['images'] for p in pages)},
        'checks':checks,'pages':[{k:v for k,v in p.items() if k!='links'} for p in pages],
        'duplicates':{'titles':dup_titles,'descriptions':dup_descs},
        'top_suggestions':[{'name':x['name'],'priority':x['priority'],'suggestion':x['suggestion']} for x in recommendations],
        'disclaimer':'VerifySweep Site Audit is a technical and on-page SEO screening tool, not a guarantee of Google rankings. Search visibility also depends on relevance, authority, competition, local signals, content quality, links, reviews, Google Business Profile strength and other factors.'
    }

class handler(BaseHTTPRequestHandler):
    def _send(self,code,payload):
        body=json.dumps(payload).encode('utf-8'); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self.send_response(204); self.send_header('Allow','POST, OPTIONS'); self.end_headers()
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>10000: raise ValueError('Invalid request.')
            payload=json.loads(self.rfile.read(n).decode('utf-8')); self._send(200,audit(payload.get('url','')))
        except (ValueError,json.JSONDecodeError) as e: self._send(400,{'error':str(e)})
        except HTTPError as e: self._send(502,{'error':f'The website returned HTTP {e.code}.'})
        except URLError: self._send(502,{'error':'The website could not be reached.'})
        except Exception: self._send(500,{'error':'The audit could not be completed. Try again or check the URL.'})
