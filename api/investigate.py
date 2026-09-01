import json, os, re
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

MAX_BODY=120000

OFFICIAL_POLICY_SOURCES={
 'eligibility':{'title':'Google Business Profile — Overview of policies / eligibility','url':'https://support.google.com/business/answer/13762416?hl=en','source':'Google Business Profile Help','checked':'2026-08-30'},
 'ownership':{'title':'Google Business Profile — Business eligibility and ownership','url':'https://support.google.com/business/answer/13763036?hl=en','source':'Google Business Profile Help','checked':'2026-08-30'},
 'representation':{'title':'Google Business Profile — Guidelines for representing your business','url':'https://support.google.com/business/answer/3038177?hl=en','source':'Google Business Profile Help','checked':'2026-08-30'},
 'service_area':{'title':'Google Business Profile — Service-area and hybrid businesses','url':'https://support.google.com/business/answer/9157481?hl=en','source':'Google Business Profile Help','checked':'2026-08-30'},
 'redressal':{'title':'Google Business Redressal Complaint Form','url':'https://support.google.com/business/contact/business_redressal_form','source':'Google Business Profile Help','checked':'2026-08-30'}
}

POLICIES={
 'possible_lead_generation':('Business eligibility / lead generation','Google Business Profile eligibility rules may be relevant when a profile represents a lead-generation agent/company rather than an eligible customer-facing business.'),
 'questionable_location':('Business location / service-area representation','Google representation and service-area rules may be relevant when an address does not appear to represent a legitimate staffed business location.'),
 'multiple_related_listings':('Duplicate / related profile review','Related profiles can be reviewed for duplicate representation or misleading identity, but shared data alone does not prove common ownership or a violation.'),
 'misleading_business_name':('Business name representation','Google generally expects a Business Profile name to reflect the real-world business name rather than added keywords or misleading locality terms.'),
 'impersonation':('Misrepresentation / impersonation','Evidence of identity misuse or misleading representation should be documented with the original source and the allegedly copied identity.'),
 'credential_claim':('Credential claim verification','Credential claims should be checked with the issuing organization. A missing directory result is an indicator to verify, not automatic proof of a false claim.'),
 'review_pattern':('Review-pattern concern','Unusual review patterns can justify further review, but pattern observations alone do not establish that reviews are fake.'),
 'routing_inconsistency':('Business identity / contact consistency','Phone or website routing that materially differs from the public business identity can be relevant to representation or lead-generation review.'),
 'no_in_person_contact':('Business eligibility','Eligibility may be relevant if the operation does not make in-person contact with customers during stated hours.'),
 'other_policy_issue':('Other policy concern','The specific policy should be identified only after the underlying facts are independently verified.')
}

def clean(v,limit=12000):
    return re.sub(r'\s+',' ',str(v or '')).strip()[:limit]

def list_clean(v,limit=30):
    if not isinstance(v,list): return []
    return [clean(x,1500) for x in v[:limit] if clean(x,1500)]

def host(url):
    try:return (urlparse(url).hostname or '').lower().lstrip('www.')
    except:return ''

def filing_route(concerns):
    redressal={'misleading_business_name','routing_inconsistency','impersonation','possible_lead_generation'}
    removal={'questionable_location','no_in_person_contact'}
    review={'review_pattern'}
    if any(x in redressal for x in concerns):
        return {'name':'Google Business Redressal Complaint Form','url':'https://support.google.com/business/contact/business_redressal_form','reason':'Google directs suspected fraudulent or misleading Maps information involving a business name, phone number, URL, or related malicious content to this form.','requires_human_filing':True}
    if any(x in removal for x in concerns):
        return {'name':'Google Maps — Suggest an edit / removal request','url':'https://support.google.com/business/answer/16043467?hl=en','reason':'Google provides a Maps removal flow for profiles that appear nonexistent or ineligible.','requires_human_filing':True}
    if any(x in review for x in concerns):
        return {'name':'Google review reporting guidance','url':'https://support.google.com/business/answer/4596773?hl=en','reason':'Review-specific concerns use Google review reporting tools rather than the Business Redressal form.','requires_human_filing':True}
    return {'name':'Google Maps business reporting guidance','url':'https://support.google.com/maps/answer/16109801?hl=en','reason':'Use Google’s reporting guide to select the route that matches the verified issue.','requires_human_filing':True}

def policy_sources_for(concern):
    mapping={
      'possible_lead_generation':['eligibility','ownership'],
      'questionable_location':['ownership','representation','service_area'],
      'multiple_related_listings':['representation'],
      'misleading_business_name':['representation'],
      'impersonation':['representation'],
      'credential_claim':['representation'],
      'review_pattern':['representation'],
      'routing_inconsistency':['representation'],
      'no_in_person_contact':['eligibility','ownership'],
      'other_policy_issue':['eligibility','representation']
    }
    return [OFFICIAL_POLICY_SOURCES[k] for k in mapping.get(concern,['eligibility','representation'])]

def analyze(c):
    concerns=list_clean(c.get('concerns'))
    route=filing_route(concerns)
    links=list_clean(c.get('evidence_links'))
    verified=clean(c.get('verified_observations'))
    observed=clean(c.get('observed'))
    suspicions=clean(c.get('suspicions'))
    business=clean(c.get('business_name'),300) or 'Reported business/listing'
    website=clean(c.get('website'),1000)
    maps=clean(c.get('maps_url'),1000)
    phone=clean(c.get('phone'),100)
    city=clean(c.get('city_state'),300)
    related=list_clean(c.get('related_entities'))
    relationship_notes=clean(c.get('relationship_notes'))
    raw_relationship_items=c.get('relationship_items') if isinstance(c.get('relationship_items'),list) else []
    relationship_items=[]
    allowed_rel_types={'phone','domain','address','business_name','email','other'}
    allowed_rel_status={'unreviewed','reporter_observed','independently_verified','disputed'}
    for item in raw_relationship_items[:60]:
        if not isinstance(item,dict): continue
        rel={
          'type':clean(item.get('type'),60),
          'value':clean(item.get('value'),1200),
          'target':clean(item.get('target'),600),
          'source_url':clean(item.get('source_url'),1200),
          'status':clean(item.get('status'),60),
          'note':clean(item.get('note'),3000)
        }
        if rel['type'] not in allowed_rel_types: rel['type']='other'
        if rel['status'] not in allowed_rel_status: rel['status']='unreviewed'
        if rel['value'] or rel['target'] or rel['source_url'] or rel['note']: relationship_items.append(rel)
    evidence_notes=clean(c.get('evidence_notes'))
    raw_attachment_items=c.get('evidence_attachments') if isinstance(c.get('evidence_attachments'),list) else []
    evidence_attachments=[]
    for item in raw_attachment_items[:60]:
        if not isinstance(item,dict): continue
        att={'id':clean(item.get('id'),120),'name':clean(item.get('name'),500),'type':clean(item.get('type'),200),'size':int(item.get('size') or 0),'addedAt':clean(item.get('addedAt'),80)}
        if att['name'] or att['id']: evidence_attachments.append(att)
    raw_evidence_items=c.get('evidence_items') if isinstance(c.get('evidence_items'),list) else []
    evidence_items=[]
    allowed_types={'google_profile','google_listing','website','credential','certification_claim','business_record','advertisement','review','phone_number','address','email','social_media','customer_communication','screenshot','other'}
    allowed_status={'unreviewed','reporter_observed','independently_verified','disputed','verified_fact','unverified_claim','possible_concern','needs_more_evidence'}
    for item in raw_evidence_items[:60]:
        if not isinstance(item,dict): continue
        ev={
          'url':clean(item.get('url'),1200),
          'capture_date':clean(item.get('capture_date'),40),
          'type':clean(item.get('type'),60),
          'status':clean(item.get('status'),60),
          'note':clean(item.get('note'),3000)
        }
        if ev['type'] not in allowed_types: ev['type']='other'
        if ev['status'] not in allowed_status: ev['status']='unreviewed'
        if ev['url'] or ev['note']: evidence_items.append(ev)
    raw_timeline_items=c.get('timeline_items') if isinstance(c.get('timeline_items'),list) else []
    timeline_items=[]
    allowed_timeline_status={'unreviewed','reporter_observed','independently_verified','disputed'}
    for item in raw_timeline_items[:80]:
        if not isinstance(item,dict): continue
        ti={'date':clean(item.get('date'),40),'event':clean(item.get('event'),600),'source_url':clean(item.get('source_url'),1200),'status':clean(item.get('status'),60),'detail':clean(item.get('detail'),3000)}
        if ti['status'] not in allowed_timeline_status: ti['status']='unreviewed'
        if ti['date'] or ti['event'] or ti['source_url'] or ti['detail']: timeline_items.append(ti)
    chronology_notes=clean(c.get('chronology_notes'))
    unresolved_questions=clean(c.get('unresolved_questions'))
    policy_notes=clean(c.get('policy_notes'))
    reviewer_notes=clean(c.get('reviewer_notes'))

    signals=[]
    if concerns:
        signals += [{'indicator':POLICIES.get(x,(x,''))[0],'basis':'Reporter selected this concern category.','status':'needs verification'} for x in concerns]
    if len(links)>=3: signals.append({'indicator':'Multiple evidence sources available','basis':f'{len(links)} source links were supplied.','status':'useful evidence lead'})
    if website and maps and host(website): signals.append({'indicator':'Website/listing identity can be cross-checked','basis':f'Website domain: {host(website)}','status':'ready to compare'})
    if phone: signals.append({'indicator':'Phone routing can be verified','basis':f'Reported phone: {phone}','status':'ready to compare'})
    if not verified: signals.append({'indicator':'Independent verification gap','basis':'No personally verified facts were entered.','status':'high priority gap'})
    if not links: signals.append({'indicator':'Source gap','basis':'No source URLs were supplied.','status':'high priority gap'})

    domains=[]
    for u in ([website,maps]+links):
        h=host(u)
        if h and h not in domains: domains.append(h)
    relationships=[]
    if len(domains)>1: relationships.append({'type':'source/domain set','value':', '.join(domains[:12]),'interpretation':'These are the domains present in the case. Their presence does not establish common ownership.'})
    if phone: relationships.append({'type':'phone identifier','value':phone,'interpretation':'Check whether this number appears on other profiles, websites, ads, or business records.'})
    if city: relationships.append({'type':'claimed geography','value':city,'interpretation':'Compare the claimed service area/location with the public profile, website, and authoritative records.'})
    structured_rel_values={x.get('target') or x.get('value') for x in relationship_items if x.get('target') or x.get('value')}
    for item in related:
        if item not in structured_rel_values:
            relationships.append({'type':'reporter-supplied relationship lead','value':item,'interpretation':'Treat this as an investigative lead until the underlying identifier or source is independently verified.'})
    for item in relationship_items:
        status_label=item['status'].replace('_',' ')
        label=item['value'] or item['target'] or 'Relationship lead'
        interpretation='Structured relationship lead. A match is not proof of common ownership or wrongdoing.'
        if item['status']=='independently_verified': interpretation='The identifier match is marked independently verified, but the meaning of that match still requires human interpretation.'
        elif item['status']=='disputed': interpretation='The relationship is disputed or conflicting and should not be stated as established.'
        relationships.append({'type':f"structured {item['type']} relationship lead",'value':label,'target':item['target'],'source_url':item['source_url'],'status':status_label,'note':item['note'],'interpretation':interpretation})
    if relationship_notes:
        relationships.append({'type':'relationship working notes','value':relationship_notes,'interpretation':'Working notes are not proof. Preserve the source for each claimed connection.'})

    evidence=[]
    if verified: evidence.append({'class':'reporter-verified observation','text':verified,'confidence':'reported as personally checked'})
    if observed: evidence.append({'class':'reporter observation','text':observed,'confidence':'reported observation; verify independently'})
    structured_urls={x.get('url') for x in evidence_items if x.get('url')}
    for u in links:
        if u not in structured_urls: evidence.append({'class':'source URL','text':u,'confidence':'source supplied; content must be reviewed'})
    for item in evidence_items:
        label={
          'independently_verified':'independently verified source item',
          'verified_fact':'verified fact',
          'reporter_observed':'reporter-observed source item',
          'unverified_claim':'unverified claim',
          'possible_concern':'possible concern',
          'needs_more_evidence':'item needing more evidence',
          'disputed':'disputed/conflicting source item',
          'unreviewed':'unreviewed source item'
        }.get(item['status'],'unreviewed source item')
        desc=item['note'] or item['url'] or 'Evidence item supplied.'
        evidence.append({'class':label,'text':desc,'confidence':item['status'].replace('_',' '),'source_url':item['url'],'capture_date':item['capture_date'],'evidence_type':item['type']})
    if suspicions: evidence.append({'class':'unverified theory','text':suspicions,'confidence':'do not present as fact'})
    if evidence_notes: evidence.append({'class':'investigator evidence notes','text':evidence_notes,'confidence':'working notes; verify each factual statement against its source'})
    for item in evidence_attachments:
        evidence.append({'class':'local attachment metadata','text':item['name'] or item['id'],'confidence':'file stored locally in reporter browser; file contents were not sent to this analysis','attachment_type':item['type'],'attachment_size':item['size'],'added_at':item['addedAt']})

    timeline=[]
    if c.get('created_at'): timeline.append({'event':'Report created','when':clean(c.get('created_at'),100),'detail':'Reporter created the case.'})
    for item in timeline_items:
        detail=item['detail'] or 'No additional detail supplied.'
        if item['source_url']: detail += f" Source: {item['source_url']}"
        timeline.append({'event':item['event'] or 'Chronology event','when':item['date'] or 'date not supplied','detail':detail,'status':item['status'].replace('_',' '),'source_url':item['source_url']})
    timeline.append({'event':'Automated triage run','when':'current review','detail':f'{len(signals)} triage item(s), {len(evidence)} evidence item(s), and {len(relationships)} relationship lead(s) organized.'})
    if chronology_notes: timeline.append({'event':'Investigator chronology notes','when':'reporter supplied','detail':chronology_notes})
    if unresolved_questions: timeline.append({'event':'Unresolved questions','when':'open','detail':unresolved_questions})

    policy=[]
    seen=set()
    for x in concerns:
        title,desc=POLICIES.get(x,(x,'Requires manual policy review.'))
        if title not in seen:
            policy.append({'topic':title,'analysis':desc,'status':'potentially relevant — human review required','official_sources':policy_sources_for(x)})
            seen.add(title)
    if not policy: policy.append({'topic':'Policy selection pending','analysis':'No concern category was selected. Review verified facts before choosing a Google policy theory.','status':'human review required','official_sources':[OFFICIAL_POLICY_SOURCES['eligibility'],OFFICIAL_POLICY_SOURCES['representation']]})

    if policy_notes:
        policy.append({'topic':'Investigator policy notes','analysis':policy_notes,'status':'working note — compare against current official source before filing','official_sources':[OFFICIAL_POLICY_SOURCES['eligibility'],OFFICIAL_POLICY_SOURCES['representation']]})

    verified_text=verified or 'No independently verified facts were entered in the case.'
    source_lines=[f'{i+1}. {u}' for i,u in enumerate(links) if u not in structured_urls]
    offset=len(source_lines)
    for i,item in enumerate(evidence_items):
        detail=item['url'] or '[no URL]'
        meta=', '.join(x for x in [item['type'].replace('_',' '), item['capture_date'], item['status'].replace('_',' ')] if x)
        source_lines.append(f'{offset+i+1}. {detail}' + (f' — {meta}' if meta else '') + (f' — {item["note"]}' if item['note'] else ''))
    source_text='\n'.join(source_lines) or 'No source URLs supplied.'
    concerns_text=', '.join(POLICIES.get(x,(x,''))[0] for x in concerns) or 'No concern category selected.'
    complaint=(f"Subject: Request for Google Business Profile review — {business}\n\n"
               f"Business/listing: {business}\nLocation: {city or 'Not provided'}\nGoogle profile: {maps or 'Not provided'}\nWebsite: {website or 'Not provided'}\nPhone: {phone or 'Not provided'}\n\n"
               f"Potential policy area(s): {concerns_text}\n\nVerified / personally checked facts supplied by reporter:\n{verified_text}\n\n"
               f"Observed issue:\n{observed or 'No observation narrative supplied.'}\n\nSupporting sources:\n{source_text}\n\n"
               + (f"Reviewer notes (internal — remove unsupported material before filing):\n{reviewer_notes}\n\n" if reviewer_notes else '')
               + "Requested action:\nPlease review the profile against the applicable Google Business Profile eligibility and representation policies. "
               "This package identifies potential concerns and supporting sources; it does not assert that Google must remove the profile. Google makes the enforcement decision.")

    completeness=0
    source_present=bool(links or evidence_items)
    for present in [bool(maps),bool(website),bool(phone),bool(verified),bool(observed),source_present,bool(concerns)]: completeness+=1 if present else 0
    completeness=round(completeness/7*100)

    # Give the professional a concrete investigation order instead of a generic score.
    investigation_plan=[]
    def add_step(priority, action, why, stage):
        investigation_plan.append({'priority':priority,'action':action,'why':why,'stage':stage})
    if maps:
        add_step('high','Preserve the exact Google Business Profile','Capture the live profile URL, business name, category, address/service area, phone, website and dated screenshots before anything changes.','FraudWatch AI')
    else:
        add_step('high','Locate and preserve the exact Google Business Profile','The complaint needs to identify the specific listing being reviewed.','FraudWatch AI')
    if phone:
        add_step('high','Cross-check the public phone number','Search the same number across other listings and websites. Record matches as relationship leads, not proof of common ownership.','Integrity Graph')
    if website:
        add_step('high','Compare the website identity with the Google profile','Check business name, domain, phone, location claims, contact forms and where customer leads are routed.','Integrity Graph')
    if 'credential_claim' in concerns:
        add_step('high','Verify the claimed credential with the issuing organization','Record the named credential holder, credential type, issuer and authoritative verification result.','Evidence AI')
    if 'questionable_location' in concerns:
        add_step('high','Verify the claimed business location','Compare the profile with authoritative public information and document only what can be independently supported.','Evidence AI')
    if 'multiple_related_listings' in concerns:
        add_step('medium','Build a listing relationship table','Compare names, phones, domains, addresses and routing across each suspected related profile. Shared identifiers are leads requiring review.','Integrity Graph')
    if 'review_pattern' in concerns:
        add_step('medium','Preserve the review pattern without alleging fake reviews','Capture dates and observable patterns. Use Google’s review-reporting process for review-specific concerns.','Evidence AI')
    if len(links)<2:
        add_step('high','Add independent supporting sources','A stronger complaint package should rely on independently checkable evidence rather than one observation or theory.','CaseBuilder AI')
    add_step('medium','Compare verified facts with the applicable Google policy','Only map policy after the underlying facts are documented.','PolicyCheck AI')
    add_step('final','Human-review the complaint package before filing','Remove unsupported conclusions, attach the strongest evidence, and submit through the Google route that matches the verified issue.','ReportBuilder AI')

    # Evidence-strength summary helps the investigator distinguish preserved facts from leads and theories.
    strength={
      'strong': sum(1 for x in evidence if x.get('class')=='reporter-verified observation') + (1 if len(links)>=2 else 0) + sum(1 for x in evidence_items if x.get('status') in {'independently_verified','verified_fact'}),
      'supporting': sum(1 for x in evidence if x.get('class') in ('source URL','reporter observation','reporter-observed source item')),
      'unverified': sum(1 for x in evidence if x.get('class')=='unverified theory') + sum(1 for x in signals if x.get('status')=='needs verification')
    }
    evidence_status='developing'
    source_count=len(set(links+[x.get('url','') for x in evidence_items if x.get('url')]))
    if strength['strong']>=2 and source_count>=2 and verified: evidence_status='strong starting package'
    elif not verified or source_count==0: evidence_status='insufficient for filing'

    gaps=[]
    if not maps:gaps.append('Add the exact Google Maps / Business Profile URL.')
    if not links and not evidence_items:gaps.append('Add source URLs and preserve screenshots with dates.')
    if not verified:gaps.append('Separate at least one independently checked fact from suspicion.')
    if suspicions:gaps.append('Keep the unverified theory internal until independently supported.')
    if not phone:gaps.append('Add the public phone number if phone routing is part of the concern.')
    if not website:gaps.append('Add the public website if site identity or routing is relevant.')

    # Filing readiness is deliberately stricter than intake completeness. A generated draft is not a finding.
    verified_structured=sum(1 for x in evidence_items if x.get('status') in {'independently_verified','verified_fact'})
    policy_human_review=bool(c.get('policy_human_review'))
    human_approved=bool(c.get('human_approved'))
    filing_checks=[
      {'key':'profile_identified','label':'Exact Google profile identified','passed':bool(maps)},
      {'key':'verified_fact','label':'At least one independently checked fact recorded','passed':bool(verified or verified_structured)},
      {'key':'supporting_sources','label':'At least two independently checkable source URLs preserved','passed':source_count>=2},
      {'key':'policy_review','label':'Current official Google policy reviewed by a human','passed':policy_human_review},
      {'key':'human_review','label':'Final evidence package reviewed by a human','passed':human_approved},
    ]
    filing_ready=all(x['passed'] for x in filing_checks)
    filing_readiness={
      'ready':filing_ready,
      'status':'human-reviewed package ready for filing consideration' if filing_ready else 'not ready for filing',
      'checks':filing_checks,
      'passed':sum(1 for x in filing_checks if x['passed']),
      'total':len(filing_checks),
      'note':'Ready means the VerifySweep review gates are complete. It does not mean the reported business violated policy or that Google will take action.'
    }

    return {
      'engine':'VerifySweep Investigation Engine v1',
      'mode':'automated evidence analysis',
      'case_completeness':completeness,
      'stages':[
        {'name':'FraudWatch AI','status':'complete','summary':f'Organized {len(signals)} potential indicator(s) and evidence gaps.','items':signals},
        {'name':'Integrity Graph','status':'complete','summary':f'Created {len(relationships)} relationship lead(s) from identifiers supplied in the case.','items':relationships},
        {'name':'Evidence AI','status':'complete','summary':f'Classified {len(evidence)} evidence item(s) and kept suspicion separate from reported facts.','items':evidence},
        {'name':'CaseBuilder AI','status':'complete','summary':'Built a basic case timeline and evidence inventory.','items':timeline},
        {'name':'PolicyCheck AI','status':'complete','summary':f'Mapped the case to {len(policy)} potentially relevant policy topic(s).','items':policy},
        {'name':'ReportBuilder AI','status':'complete','summary':'Prepared a Google complaint-support draft for human review.','items':[{'type':'complaint draft','text':complaint}]}
      ],
      'evidence_strength':strength,
      'evidence_status':evidence_status,
      'gaps':gaps,
      'investigation_plan':investigation_plan,
      'filing_route':route,
      'filing_readiness':filing_readiness,
      'official_policy_sources':list(OFFICIAL_POLICY_SOURCES.values()),
      'complaint_draft':complaint,
      'disclaimer':'This automated analysis identifies potential indicators and organizes evidence. It does not determine that a company is fraudulent, does not guarantee a Google policy violation, and does not submit anything to Google. A human must verify the evidence and decide what to file.'
    }

class handler(BaseHTTPRequestHandler):
    def sendj(self,code,p):
        b=json.dumps(p).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204); self.send_header('Allow','POST, OPTIONS'); self.end_headers()
    def do_GET(self): self.sendj(405,{'error':'Use POST with a JSON investigation case.'})
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<2 or n>MAX_BODY: raise ValueError('Invalid request size.')
            c=json.loads(self.rfile.read(n).decode())
            if not isinstance(c,dict): raise ValueError('Case data is required.')
            result=ai_enhance(c,analyze(c))
            focus=clean(c.get('stage'),80)
            if focus:
                match=next((x for x in result.get('stages',[]) if x.get('name','').lower().replace(' ','-').replace('ai','').strip('-') in focus.lower() or focus.lower() in x.get('name','').lower()),None)
                if match: result['focused_stage']=match
            self.sendj(200,result)
        except (ValueError,json.JSONDecodeError) as e:self.sendj(400,{'error':str(e)})
        except Exception:self.sendj(500,{'error':'The investigation could not be completed.'})

# Optional live model layer. Set OPENAI_API_KEY in the server environment to enable it.
def ai_enhance(case, deterministic_result):
    key=os.environ.get('OPENAI_API_KEY','').strip()
    if not key:
        deterministic_result['ai_mode']='evidence_engine'
        deterministic_result['ai_note']='Live model analysis is not configured; VerifySweep used its evidence and policy engine.'
        return deterministic_result
    try:
        import urllib.request
        safe_case={k:case.get(k) for k in ['business_name','city_state','phone','website','maps_url','concerns','verified_observations','suspicions','observed','evidence_links','evidence_items','evidence_attachments','related_entities','relationship_items','relationship_notes','evidence_notes','timeline_items','chronology_notes','unresolved_questions','policy_notes','reviewer_notes']}
        instructions=('You are VerifySweep AI, an evidence-review assistant for chimney professionals. '
          'Never declare fraud, ownership, illegality, fake credentials, or a Google policy violation unless the supplied evidence establishes it. '
          'Keep reporter allegations separate from verified facts. Identify evidence gaps and useful next verification steps. '
          'Do not invent sources. Return concise JSON only with keys executive_summary, strongest_support, evidence_gaps, next_steps, complaint_improvements. '
          'Each value except executive_summary must be an array of short strings.')
        payload={'model':os.environ.get('OPENAI_MODEL','gpt-5.6-luna'),'store':False,
          'input':instructions+'\n\nCASE:\n'+json.dumps(safe_case,ensure_ascii=False)+'\n\nCURRENT EVIDENCE ENGINE RESULT:\n'+json.dumps(deterministic_result,ensure_ascii=False)[:30000],
          'text':{'format':{'type':'json_object'}}}
        req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=25) as r: raw=json.loads(r.read().decode())
        txt=raw.get('output_text')
        if not txt:
            parts=[]
            for item in raw.get('output',[]):
                for c in item.get('content',[]):
                    if c.get('type')=='output_text': parts.append(c.get('text',''))
            txt=''.join(parts)
        model_review=json.loads(txt)
        deterministic_result['ai_mode']='live_model_plus_evidence_engine'
        deterministic_result['model_review']=model_review
        deterministic_result['ai_note']='Live AI review completed. Human verification is still required.'
        return deterministic_result
    except Exception as e:
        deterministic_result['ai_mode']='evidence_engine_fallback'
        deterministic_result['ai_note']='Live AI was unavailable, so the evidence and policy engine completed the review.'
        return deterministic_result
