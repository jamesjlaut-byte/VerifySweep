'use strict';
// Public presentation helpers. No identity, affiliation or credential is inferred.
(() => {
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const safeUrl=value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?u.href:'';}catch{return '';}};
  const date=value=>{if(!value)return 'Not recorded';const d=new Date(value);return Number.isNaN(d.getTime())?'Not recorded':d.toLocaleDateString(undefined,{timeZone:'UTC'});};
  const norm=value=>String(value||'').trim().toLowerCase();
  const credentialKey=c=>JSON.stringify([norm(c.issuer),norm(c.credential_type||c.credential),norm(c.credential_number),c.source||'',c.display_status||'',c.verified_at||'',c.last_checked_at||'',c.expiration_date||'',c.recheck_due_at||'']);
  function groupPeople(companies){
    const groups=new Map();
    companies.forEach(company=>(company.reviewed_professionals||company.professionals||[]).forEach(record=>{
      if(!record.holder)return;
      // Same-name people at different company records must not be collapsed.
      const key=JSON.stringify([String(company.id||company.company),norm(record.holder)]);
      if(!groups.has(key))groups.set(key,{key,holder:record.holder,company,credentials:[],industry_leader:null});
      const person=groups.get(key);
      const duplicate=person.credentials.some(c=>credentialKey(c)===credentialKey(record));
      if(!duplicate)person.credentials.push(record);
      if(record.industry_leader)person.industry_leader=record.industry_leader;
    }));
    return [...groups.values()].sort((a,b)=>Number(b.credentials.some(c=>c.display_status==='CREDENTIAL VERIFIED'))-Number(a.credentials.some(c=>c.display_status==='CREDENTIAL VERIFIED'))||a.holder.localeCompare(b.holder)||String(a.company.company).localeCompare(String(b.company.company)));
  }
  function anchor(label,href,cls='btn'){
    const a=node('a',label,cls);a.href=href;return a;
  }
  function credential(record){
    const row=node('div',undefined,'pro credential-detail');
    row.append(node('div',(record.credential_type||record.credential||'Credential')+(record.issuer?' · '+record.issuer:''),'proName'));
    row.append(node('span',record.display_status||'VERIFICATION NEEDED','status'));
    row.append(node('p','Last checked: '+date(record.last_checked_at)+' · Expiration: '+(record.expiration_date?date(record.expiration_date):'Not documented'),'small'));
    if(record.recheck_due_at)row.append(node('p','Next review: '+date(record.recheck_due_at),'small'));
    if(record.status_note)row.append(node('p',record.status_note,'small'));
    const source=safeUrl(record.source);
    if(source){const a=anchor('Check credential source',source,'proSource');a.target='_blank';a.rel='noopener noreferrer';row.append(a);}
    return row;
  }
  function personCard(person,{returnTo='',compact=false}={}){
    const card=node('article',undefined,compact?'row professional-group':'result professional-result personResult');
    const title=node('div',undefined,'titleLine');title.append(node(compact?'h3':'h2',person.holder));
    if(person.industry_leader){const image=node('img');image.src='/VerifySweep-Industry-Leader-Badge.png';image.alt='VerifySweep Industry Leader';image.width=64;image.height=64;image.className='leaderMark';title.append(image);}
    card.append(title);
    if(!compact)card.append(node('p','Listed company: '+person.company.company,'proMeta'));
    const verified=person.credentials.filter(c=>c.display_status==='CREDENTIAL VERIFIED');
    card.append(node('p',verified.length?verified.length+' current verified credential'+(verified.length===1?'':'s')+' on file':'Credential records available; current verification requires review.','small'));
    // Only show completed separate checks; a listed company alone is not proof.
    const facts=node('div',undefined,'tags');
    if(person.credentials.some(c=>norm(c.identity_status)==='verified'))facts.append(node('span','Identity verified','tag'));
    if(person.credentials.some(c=>norm(c.company_affiliation_status)==='verified'))facts.append(node('span','Company affiliation verified','tag'));
    if(facts.children.length)card.append(facts);
    const list=node('section',undefined,'pros');list.append(node('h3','Individual credentials'));person.credentials.forEach(c=>list.append(credential(c)));card.append(list);
    const actions=node('div',undefined,'actions'),record=verified[0]||person.credentials[0];
    if(record&&record.id!=null)actions.append(anchor('View Professional','/professional-profile.html?id='+encodeURIComponent(record.id)+(returnTo?'&return='+encodeURIComponent(returnTo):'')));
    if(!compact)actions.append(anchor('View Company','/company-profile.html?id='+encodeURIComponent(person.company.id)+(returnTo?'&return='+encodeURIComponent(returnTo):''),'btn alt'));
    card.append(actions);return card;
  }
  function returnLink(){
    const value=new URLSearchParams(location.search).get('return');
    if(value&&/^\/find-a-pro\.html(?:\?|$)/.test(value)&&!/[\r\n]/.test(value)){
      const url=new URL(value,location.origin);if(url.origin===location.origin)return url.pathname+url.search;
    }
    return '/find-a-pro.html';
  }
  window.VerifySweepDirectoryUI={node,safeUrl,date,groupPeople,personCard,anchor,returnLink};
})();
