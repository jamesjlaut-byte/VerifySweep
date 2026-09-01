from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, urljoin, urldefrag
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, re, socket, ipaddress, time

MAX_BYTES = 1_250_000
MAX_PAGES = 18
MAX_LINK_CHECKS = 36
MAX_EXTERNAL_CHECKS = 12
AUDIT_TIMEOUT_SECONDS = 45
CRAWL_TIMEOUT_SECONDS = 24
LINK_CHECK_TIMEOUT_SECONDS = 6
UA = 'VerifySweep-SiteAudit/1.5 (+https://www.verifysweep.com)'

class AuditTimeout(TimeoutError):
    pass

def timeout_for(deadline, maximum):
    remaining=deadline-time.monotonic()
    if remaining<=0.25: raise AuditTimeout('The website audit timed out before it could finish.')
    return max(0.25,min(maximum,remaining))

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


def fetch(url,timeout=6,limit=MAX_BYTES,deadline=None):
    assert_public_host(url)
    if deadline is not None: timeout=timeout_for(deadline,timeout)
    req=Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml;q=0.9,*/*;q=0.4'})
    with build_opener(SafeRedirect()).open(req,timeout=timeout) as r:
        final=r.geturl(); assert_public_host(final); ctype=r.headers.get('Content-Type','')
        data=r.read(limit+1)
        if len(data)>limit: raise ValueError('A page is too large for this audit.')
        return final,getattr(r,'status',200),ctype,data.decode(r.headers.get_content_charset() or 'utf-8',errors='replace')


def status_check(url,timeout=4,deadline=None):
    try:
        assert_public_host(url)
        if deadline is not None: timeout=timeout_for(deadline,timeout)
        req=Request(url,headers={'User-Agent':UA},method='GET')
        with build_opener(SafeRedirect()).open(req,timeout=timeout) as r: return getattr(r,'status',200),r.geturl()
    except AuditTimeout: raise
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


def clean_external(base_url,href,host):
    if not href or href.startswith(('#','mailto:','tel:','javascript:','data:')): return None
    u=urljoin(base_url,href); u,_=urldefrag(u); p=urlparse(u)
    if p.scheme not in ('http','https') or not p.hostname or p.hostname==host: return None
    return u

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
    visible_text=' '.join(p.text_parts)
    return {'url':url,'path':path,'status':status,'title':title,'title_length':len(title),'description':desc,'description_length':len(desc),
            'h1':p.h1,'h2_count':len(p.h2),'word_count':words,'images':len(p.images),'missing_alt':missing_alt,
            'viewport':bool(viewport),'canonical':canonical,'robots':robots,'schema_types':types,'phones':phones,'links':p.links,'issues':issues,
            '_text':visible_text[:30000]}


def result_item(name,status,detail,suggestion='',priority='medium'):
    return {'name':name,'status':status,'detail':detail,'suggestion':suggestion,'priority':priority}


def audit(raw_url,timeout_seconds=AUDIT_TIMEOUT_SECONDS):
    deadline=time.monotonic()+timeout_seconds
    requested=normalize_url(raw_url)
    final,status,ctype,html=fetch(requested,deadline=deadline)
    if 'html' not in ctype.lower() and '<html' not in html[:1000].lower(): raise ValueError('That URL did not return an HTML webpage.')
    host=urlparse(final).hostname; root=f'{urlparse(final).scheme}://{urlparse(final).netloc}'

    home=analyze_page(final,status,html)
    pages=[home]; seen={urldefrag(final)[0]}; queue=[]
    crawl_deadline=min(deadline,time.monotonic()+CRAWL_TIMEOUT_SECONDS)
    for href in home['links']:
        u=clean_internal(final,href,host)
        if u and u not in seen: queue.append(u)

    while queue and len(pages)<MAX_PAGES:
        u=queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try:
            fu,st,ct,body=fetch(u,timeout=5,deadline=crawl_deadline)
            if ('html' not in ct.lower() and '<html' not in body[:1000].lower()): continue
            page=analyze_page(fu,st,body); pages.append(page)
            for href in page['links']:
                nxt=clean_internal(fu,href,host)
                if nxt and nxt not in seen and nxt not in queue: queue.append(nxt)
        except AuditTimeout: break
        except Exception: continue

    # Internal-link inventory and status sampling.
    internal_urls=[]
    for page in pages:
        for href in page['links']:
            u=clean_internal(page['url'],href,host)
            if u and u not in internal_urls: internal_urls.append(u)
    incoming={p['url']:0 for p in pages}
    for source in pages:
        outs=[]
        for href in source['links']:
            u=clean_internal(source['url'],href,host)
            if u and u not in outs: outs.append(u)
        source['internal_links_out']=len(outs)
        for u in outs:
            target=next((x['url'] for x in pages if urldefrag(x['url'])[0].rstrip('/')==urldefrag(u)[0].rstrip('/')),None)
            if target: incoming[target]=incoming.get(target,0)+1
    for page in pages:
        page['internal_links_in']=incoming.get(page['url'],0)
        txt=(page.get('_text','')+' '+page.get('title','')+' '+' '.join(page.get('h1',[]))).lower()
        page['chimney_topics']=[t for t in ('inspection','sweep','repair','liner','fireplace','chimney') if t in txt]
        page['credential_signal']=any(t in txt for t in ('csia','nfi certified','f.i.r.e','fire certified','certified chimney'))
        page['location_signal']=bool(re.search(r'\b(?:tx|texas|service area|serving|austin|san antonio|houston|dallas|fort worth)\b',txt))
        page['trust_signal']=any(t in txt for t in ('about us','contact','warranty','insured','certified','credential','privacy'))
        if page is not home and page.get('internal_links_in',0)==0: page['issues'].append('No incoming internal link in crawl sample')
        if page.get('word_count',0)>=200 and page.get('internal_links_out',0)<2: page['issues'].append('Low internal-link support')

    checked=internal_urls[:MAX_LINK_CHECKS]; broken=[]
    internal_check_deadline=min(deadline,time.monotonic()+LINK_CHECK_TIMEOUT_SECONDS)
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut={ex.submit(status_check,u,4,internal_check_deadline):u for u in checked}
        for f in as_completed(fut):
            u=fut[f]
            try:
                st,_=f.result()
                if st==0 or st>=400: broken.append({'url':u,'status':st})
            except AuditTimeout: continue
            except Exception: broken.append({'url':u,'status':0})

    external_urls=[]
    for page in pages:
        for href in page['links']:
            u=clean_external(page['url'],href,host)
            if u and u not in external_urls: external_urls.append(u)
    external_checked=external_urls[:MAX_EXTERNAL_CHECKS]; broken_external=[]
    external_check_deadline=min(deadline,time.monotonic()+LINK_CHECK_TIMEOUT_SECONDS)
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut={ex.submit(status_check,u,4,external_check_deadline):u for u in external_checked}
        for f in as_completed(fut):
            u=fut[f]
            try:
                st,_=f.result()
                if st==0 or st>=400: broken_external.append({'url':u,'status':st})
            except AuditTimeout: continue
            except Exception: broken_external.append({'url':u,'status':0})

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
    noindex_pages=[p['url'] for p in pages if 'noindex' in (p['robots'] or '').lower()]
    missing_canonical=sum(1 for p in pages if not p['canonical'])
    canonical_mismatch=sum(1 for p in pages if p['canonical'] and urldefrag(urljoin(p['url'],p['canonical']))[0].rstrip('/') != urldefrag(p['url'])[0].rstrip('/'))
    missing_viewport=sum(1 for p in pages if not p['viewport'])
    error_pages=sum(1 for p in pages if int(p.get('status') or 0) >= 400)
    self_canonical=sum(1 for p in pages if p['canonical'] and urldefrag(urljoin(p['url'],p['canonical']))[0].rstrip('/') == urldefrag(p['url'])[0].rstrip('/'))
    title_length_issues=sum(1 for p in pages if p['title'] and not 30<=p['title_length']<=65)
    desc_length_issues=sum(1 for p in pages if p['description'] and not 70<=p['description_length']<=170)
    checks.append(result_item('Google indexability','pass' if not noindex_pages else 'fail',f'{len(noindex_pages)} crawled page(s) contain a noindex directive.','Remove noindex from pages you expect Google to index. Keep noindex only where it is intentional.' if noindex_pages else '', 'high'))
    checks.append(result_item('Canonical URLs','pass' if missing_canonical==0 and canonical_mismatch==0 else 'warn',f'{missing_canonical} page(s) are missing a canonical; {canonical_mismatch} page(s) point to a different canonical URL.','Give indexable pages a deliberate canonical URL and investigate canonicals that point somewhere unexpected.' if missing_canonical or canonical_mismatch else '', 'high'))
    checks.append(result_item('Mobile viewport','pass' if missing_viewport==0 else 'warn',f'{missing_viewport} crawled page(s) are missing a viewport meta tag.','Add a responsive viewport meta tag and test important pages on mobile devices.' if missing_viewport else '', 'medium'))
    checks.append(result_item('SERP snippet lengths','pass' if title_length_issues==0 and desc_length_issues==0 else 'warn',f'{title_length_issues} title(s) and {desc_length_issues} meta description(s) fall outside VerifySweep screening ranges.','Rewrite awkwardly short or long titles/descriptions for clarity. Length is a screening heuristic, not a Google ranking rule.' if title_length_issues or desc_length_issues else '', 'low'))
    checks.append(result_item('Broken internal links','pass' if not broken else 'fail',f'Checked {len(checked)} internal URLs; found {len(broken)} possible broken link(s).','Repair or redirect broken internal links so visitors and crawlers do not hit dead ends.' if broken else '', 'high'))
    checks.append(result_item('External link health','pass' if not broken_external else 'warn',f'Checked {len(external_checked)} external URLs; found {len(broken_external)} possible broken external link(s).','Update or remove broken credential, manufacturer, association, policy, or other outbound links so homeowners reach the intended source.' if broken_external else '', 'medium'))
    checks.append(result_item('Crawled page status','pass' if error_pages==0 else 'fail',f'{error_pages} crawled page(s) returned an HTTP error status.','Repair, redirect, or intentionally remove erroring pages that are linked from the site.' if error_pages else '', 'high'))
    checks.append(result_item('Structured data','pass' if no_schema==0 else 'warn',f'{len(pages)-no_schema}/{len(pages)} crawled pages contain JSON-LD schema.','Use accurate LocalBusiness/Organization schema on core pages and Service/Article/FAQ schema only where the page content supports it.' if no_schema else '', 'medium'))
    checks.append(result_item('Image accessibility','pass' if alt_missing==0 else 'warn',f'{alt_missing} image(s) across crawled pages are missing an alt attribute.','Add descriptive alt text to meaningful chimney/fireplace images; decorative images should use alt="".' if alt_missing else '', 'low'))
    checks.append(result_item('Content depth','pass' if thin==0 else 'warn',f'{thin} of {len(pages)} crawled pages have fewer than 200 visible words.','Expand thin pages only with useful original content: service process, inspection scope, common problems, qualifications, service-area specifics and FAQs.' if thin else '', 'medium'))
    checks.append(result_item('Phone consistency','warn' if inconsistent_phone else 'pass','Different phone-number sets were detected across crawled pages.' if inconsistent_phone else 'No obvious phone-number inconsistency found in the crawled sample.','Make sure location-specific numbers are intentional and clearly associated with the correct office/service area; keep primary NAP information consistent.' if inconsistent_phone else '', 'medium'))
    robots_ok=status_check(urljoin(root,'/robots.txt'),deadline=deadline)[0] in range(200,400)
    sitemap_ok=status_check(urljoin(root,'/sitemap.xml'),deadline=deadline)[0] in range(200,400)
    checks.append(result_item('robots.txt','pass' if robots_ok else 'warn','robots.txt is reachable.' if robots_ok else 'robots.txt was not found or could not be reached.','Publish a valid robots.txt and reference the XML sitemap.' if not robots_ok else '', 'medium'))
    checks.append(result_item('XML sitemap','pass' if sitemap_ok else 'warn','sitemap.xml is reachable.' if sitemap_ok else 'sitemap.xml was not found or could not be reached.','Publish an XML sitemap and submit it in Google Search Console.' if not sitemap_ok else '', 'medium'))

    # Chimney-industry focused prompts, without pretending these are ranking factors.
    all_text=(' '.join([p['title']+' '+' '.join(p['h1']) for p in pages])).lower()
    chimney_terms=['chimney','fireplace','sweep','inspection','repair']
    coverage=sum(1 for t in chimney_terms if t in all_text)
    checks.append(result_item('Service-topic clarity','pass' if coverage>=3 else 'warn',f'{coverage}/5 core chimney-service terms appear in crawled titles/H1s.','Make important service pages unmistakably about the exact service offered—such as chimney inspection, chimney sweep, fireplace repair, relining or dryer vent cleaning—without keyword stuffing.' if coverage<3 else '', 'medium'))

    # Chimney-company specific screening. These are editorial quality checks, not claimed Google ranking factors.
    combined=' '.join(' '.join([p['title'], ' '.join(p['h1'])]) for p in pages).lower()
    credential_terms=['csia','nfi','f.i.r.e','fire certified','certified chimney','credential']
    credential_hits=sum(1 for t in credential_terms if t in combined)
    checks.append(result_item('Credential clarity','pass' if credential_hits else 'warn',
        'Credential or certification language appears in crawled titles/H1s.' if credential_hits else 'No obvious credential language appeared in crawled titles/H1s.',
        'If your company holds current credentials, explain them accurately and link homeowners to an official issuer verification source. Do not imply that company membership equals an individual technician certification.' if not credential_hits else '', 'medium'))

    location_signals=0
    for p in pages:
        path=(p['path'] or '').lower(); head=(' '.join(p['h1'])+' '+p['title']).lower()
        if any(x in path for x in ('-tx','/tx/','-texas','/locations','/service-area','/areas')) or re.search(r'\b(?:austin|san antonio|houston|dallas|fort worth|texas|tx)\b',head):
            location_signals+=1
    checks.append(result_item('Local service-area clarity','pass' if location_signals else 'warn',
        f'{location_signals} crawled page(s) show an obvious location/service-area signal.' if location_signals else 'No obvious location/service-area page signal was detected in this crawl sample.',
        'For local search, make real service areas clear with useful, original location pages where appropriate. Avoid doorway pages that merely swap city names.' if not location_signals else '', 'medium'))

    call_terms=['call','schedule','appointment','request','estimate','contact','book']
    cta_pages=sum(1 for p in pages if any(t in (' '.join(p['h1'])+' '+p['description']).lower() for t in call_terms))
    checks.append(result_item('Customer action clarity','pass' if cta_pages>=max(1,len(pages)//3) else 'warn',
        f'{cta_pages}/{len(pages)} crawled pages show appointment/contact intent in prominent page signals.',
        'Make it obvious how a homeowner should contact or schedule with you, especially on service and location landing pages.' if cta_pages<max(1,len(pages)//3) else '', 'low'))

    # Trust and local-business quality screens. These are practical chimney-site checks, not claimed ranking factors.
    trust_terms=['privacy','terms','about','contact','warranty','insured','certified','credential']
    trust_hits=sum(1 for t in trust_terms if t in ' '.join((p['path']+' '+p['title']+' '+p['description']).lower() for p in pages))
    checks.append(result_item('Trust information','pass' if trust_hits>=3 else 'warn',
        f'{trust_hits}/8 trust-topic signals were detected in the crawl sample.',
        'Make ownership/contact information, qualifications, policies and other trust information easy for homeowners to find. Only state credentials, insurance or warranties that are accurate and current.' if trust_hits<3 else '', 'medium'))

    # Flag suspiciously repetitive city/location pages using visible text fingerprints.
    loc_pages=[p for p in pages if any(x in (p['path'] or '').lower() for x in ('-tx','-texas','/locations/','/service-area/','/areas/'))]
    repetitive_locations=0
    for i,a in enumerate(loc_pages):
        aw=set(re.findall(r'[a-z]{4,}', (a['title']+' '+a['description']+' '+' '.join(a['h1'])).lower()))
        for b in loc_pages[i+1:]:
            bw=set(re.findall(r'[a-z]{4,}', (b['title']+' '+b['description']+' '+' '.join(b['h1'])).lower()))
            if aw and bw and len(aw&bw)/max(1,len(aw|bw))>.82:
                repetitive_locations+=1
    checks.append(result_item('Location-page uniqueness','warn' if repetitive_locations else 'pass',
        f'{repetitive_locations} highly similar location-page pair(s) were detected in page-level signals.' if repetitive_locations else 'No highly repetitive location-page signals were detected in the crawl sample.',
        'Do not create city pages by only swapping place names. Add genuinely useful local service details, coverage, project context and homeowner information.' if repetitive_locations else '', 'medium'))

    # Internal-link discoverability: important pages should not be isolated in the crawl sample.
    orphan_like=[p for i,p in enumerate(pages) if i>0 and p.get('internal_links_in',0)==0]
    low_link_pages=[p for p in pages if p.get('internal_links_out',0)<2 and p.get('word_count',0)>=200]
    checks.append(result_item('Internal linking','pass' if not orphan_like and len(low_link_pages)<=max(1,len(pages)//4) else 'warn',
        f'{len(orphan_like)} crawled page(s) have no incoming link from another crawled page; {len(low_link_pages)} content page(s) have fewer than 2 internal links.',
        'Link related service, location and education pages together with useful descriptive anchors. Important pages should be reachable through the site structure, not isolated landing pages.' if orphan_like or low_link_pages else '', 'medium'))

    # Official credential/resource-link screen. This does not validate a credential; it checks whether trust claims can send a homeowner to an authoritative source.
    issuer_domains=('csia.org','nficertified.org','f-i-r-e-service.com','gotofire.com','ncsg.org')
    issuer_links=[]
    for u in external_urls:
        h=(urlparse(u).hostname or '').lower().lstrip('www.')
        if any(h==d or h.endswith('.'+d) for d in issuer_domains): issuer_links.append(u)
    credential_text=' '.join(p.get('_text','') for p in pages).lower()
    has_credential_claim=any(t in credential_text for t in ('csia','nfi certified','f.i.r.e','fire certified','certified chimney sweep','certified fireplace'))
    checks.append(result_item('Credential verification links','pass' if (not has_credential_claim or issuer_links) else 'warn',
        f'{len(issuer_links)} external link(s) to recognized credential-issuer domains were detected.' if issuer_links else ('Credential language appears, but no obvious issuer/resource link was detected.' if has_credential_claim else 'No prominent credential claim requiring an issuer link was detected in this sample.'),
        'When you state an individual technician credential, link homeowners to the issuing organization or its official verification resource. A logo alone does not identify who holds the credential.' if has_credential_claim and not issuer_links else '', 'medium'))

    # Better repetitive-location screening using visible body text, with place-like tokens normalized.
    def fingerprint(text):
        words=[w for w in re.findall(r'[a-z]{4,}',text.lower()) if w not in {'chimney','fireplace','sweep','sweeps','inspection','repair','service','services','texas','company','homeowners'}]
        return set(words[:1200])
    probable_city=[]
    for p in pages:
        path=(p.get('path') or '').lower(); text=(p.get('title','')+' '+(p.get('h1') or [''])[0]).lower()
        if any(x in path for x in ('-tx','-texas','/locations/','/service-area/','/areas/','/city/')) or re.search(r'\b(?:tx|texas)\b',text): probable_city.append(p)
    near_dupes=[]
    for i,a in enumerate(probable_city):
        af=fingerprint(a.get('_text',''))
        for b in probable_city[i+1:]:
            bf=fingerprint(b.get('_text',''))
            if len(af)>=40 and len(bf)>=40:
                sim=len(af&bf)/max(1,len(af|bf))
                if sim>=.72: near_dupes.append({'page_a':a['url'],'page_b':b['url'],'similarity':round(sim*100)})
    checks.append(result_item('City-page body uniqueness','warn' if near_dupes else 'pass',
        f'{len(near_dupes)} location-page pair(s) are highly similar by visible-body-text fingerprint.' if near_dupes else 'No highly similar city-page body-text pairs were detected in the crawl sample.',
        'Rewrite repetitive city pages around genuinely useful local information: actual service coverage, common housing/fireplace context, examples, scheduling details, and unique homeowner guidance. Do not merely swap city names.' if near_dupes else '', 'high'))

    # Chimney topic coverage page by page, not only globally.
    topic_terms={'inspection':('inspection','level 1','level 2'),'sweep':('chimney sweep','sweeping'),'repair':('chimney repair','masonry repair','fireplace repair'),'reline':('reline','relining','liner'),'water':('waterproof','water repellent','crown repair','leak')}
    service_pages=[]
    for p in pages:
        txt=(p.get('title','')+' '+' '.join(p.get('h1',[]))+' '+p.get('_text','')[:5000]).lower()
        hits=[k for k,vals in topic_terms.items() if any(v in txt for v in vals)]
        if hits: service_pages.append({'url':p['url'],'topics':hits})
    checks.append(result_item('Chimney service coverage','pass' if len(service_pages)>=min(3,len(pages)) else 'warn',
        f'{len(service_pages)} crawled page(s) clearly cover at least one chimney service topic.',
        'Create clear, useful pages for the services you actually perform. Keep inspection, sweeping, repair/relining and water-entry topics understandable to homeowners without stuffing every term onto every page.' if len(service_pages)<min(3,len(pages)) else '', 'medium'))

    weights={'pass':1.0,'warn':0.55,'fail':0.0}
    score=round(100*sum(weights[x['status']] for x in checks)/len(checks))
    pri={'high':0,'medium':1,'low':2}
    recommendations=sorted([x for x in checks if x['status']!='pass' and x['suggestion']],key=lambda x:(pri.get(x['priority'],9),0 if x['status']=='fail' else 1))[:8]
    return {
        'requested_url':requested,'final_url':final,'http_status':status,'score':score,
        'crawl':{'pages_crawled':len(pages),'page_limit':MAX_PAGES,'internal_links_found':len(internal_urls),'links_checked':len(checked),'broken_links':broken,'external_links_found':len(external_urls),'external_links_checked':len(external_checked),'broken_external_links':broken_external},
        'summary':{'title':home['title'],'description':home['description'],'h1_count':len(home['h1']),'word_count':home['word_count'],'internal_links':len(internal_urls),'images':sum(p['images'] for p in pages)},
        'checks':checks,'pages':[{k:v for k,v in p.items() if k not in ('links','_text')} for p in pages],
        'duplicates':{'titles':dup_titles,'descriptions':dup_descs,'city_body_pairs':near_dupes},
        'credential_resource_links':issuer_links[:20],
        'service_topic_pages':service_pages[:30],
        'top_suggestions':[{'name':x['name'],'priority':x['priority'],'suggestion':x['suggestion']} for x in recommendations],
        'disclaimer':'VerifySweep Site Audit is a technical and on-page SEO screening tool, not a guarantee of Google rankings. Search visibility also depends on relevance, authority, competition, local signals, content quality, links, reviews, Google Business Profile strength and other factors.'
    }

class handler(BaseHTTPRequestHandler):
    def _send(self,code,payload):
        body=json.dumps(payload).encode('utf-8'); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self): self.send_response(204); self.send_header('Allow','POST, OPTIONS'); self.send_header('Access-Control-Allow-Methods','POST, OPTIONS'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.send_header('Cache-Control','no-store'); self.end_headers()
    def do_GET(self): self._send(405,{'error':'Use POST with a JSON body containing a public website URL.'})
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>10000: raise ValueError('Invalid request.')
            if 'application/json' not in self.headers.get('Content-Type','').lower(): raise ValueError('Send the website URL as JSON.')
            payload=json.loads(self.rfile.read(n).decode('utf-8'))
            if not isinstance(payload,dict): raise ValueError('Invalid request.')
            self._send(200,audit(payload.get('url','')))
        except (ValueError,json.JSONDecodeError) as e: self._send(400,{'error':str(e)})
        except HTTPError as e: self._send(502,{'error':f'The website returned HTTP {e.code}.'})
        except (AuditTimeout,socket.timeout,TimeoutError): self._send(504,{'error':'The website audit timed out. The site may be slow, blocking automated requests, or too large to crawl right now.'})
        except URLError as e:
            if isinstance(getattr(e,'reason',None),(socket.timeout,TimeoutError)): self._send(504,{'error':'The website took too long to respond. Try again later.'})
            else: self._send(502,{'error':'The website could not be reached. Check the URL and confirm the site is publicly accessible.'})
        except Exception as e:
            print(f'[site-audit] failed: {type(e).__name__}: {e}',flush=True)
            self._send(500,{'error':'The audit could not be completed. Try again or check that the website allows automated crawlers.'})
