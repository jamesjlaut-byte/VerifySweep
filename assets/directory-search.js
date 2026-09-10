'use strict';
(() => {
  const ui=window.VerifySweepDirectoryUI,{node:el,safeUrl,anchor}=ui,$=id=>document.getElementById(id);
  const form=$('searchForm'),out=$('results'),q=$('q'),city=$('city'),state=$('state'),review=$('credentialStatus'),issuer=$('issuer'),type=$('credentialType');
  const stateNames=Object.fromEntries(('AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:District of Columbia').split('|').map(pair=>pair.split(':')));
  const stateAliases=Object.entries(stateNames).flatMap(([code,name])=>[[code.toLowerCase(),code],[name.toLowerCase(),code]]).sort((a,b)=>b[0].length-a[0].length);
  for(const o of state.options){const code=o.value;if(stateNames[code]){o.value=code;o.textContent=stateNames[code]+' ('+code+')';}}
  function locationQuery(value){
    const normalized=value.replace(/\s+/g,' '),lower=normalized.toLowerCase();
    const exact=stateAliases.find(([alias])=>lower===alias);if(exact)return {state:exact[1],city:''};
    for(const [alias,code] of stateAliases){if(lower.endsWith(' '+alias)||lower.endsWith(','+alias)){const town=normalized.slice(0,-alias.length).replace(/[,\s]+$/,'');if(town)return {state:code,city:town};}}
    return null;
  }
  const radiusBox=el('div');radiusBox.append(el('label','Radius'));radiusBox.firstChild.htmlFor='radius';
  const radius=el('select');radius.id='radius';[10,25,50,75,100].forEach(n=>{const o=el('option',n+' miles');o.value=String(n);radius.append(o);});radius.value='25';radiusBox.append(radius);state.parentElement.after(radiusBox);
  const quick=el('label',undefined,'verified-filter'),checkbox=el('input');checkbox.type='checkbox';checkbox.id='verifiedOnly';
  quick.append(checkbox,document.createTextNode(' Show only professionals with verified credentials'));form.querySelector('.primarySearch').append(quick);
  const reset=el('button','Clear search and filters','btn alt');reset.type='button';reset.id='clearSearch';form.append(reset);
  q.maxLength=120;city.maxLength=120;review.options[1].textContent='Only professionals with verified credentials';
  form.querySelector('label[for="q"]').textContent='ZIP, city and state, state, company, or professional';
  q.placeholder='New Jersey, Newark NJ, 07102, or a company / person';
  form.querySelector('.primarySearch .small').textContent='Examples: New Jersey · Newark, NJ · 78701 · Hill Country Sweeps · James Laut';
  ['NFI Woodburning Specialist','NFI Gas Specialist','NFI Pellet Specialist','NFI Hearth Design Specialist','NFI Master Hearth Professional'].forEach(name=>{const o=el('option',name);o.value=name;type.append(o);});
  let active=null,sequence=0,rows=[],meta={},params=new URLSearchParams(),tab='professionals',page=1;
  const PAGE_SIZE=12;
  function restore(){
    const p=new URLSearchParams(location.search);q.value=p.get('q')||p.get('zip')||'';city.value=p.get('city')||'';state.value=p.get('state')||'';
    review.value=p.get('verified')==='1'?'1':'';checkbox.checked=review.value==='1';issuer.value=p.get('issuer')||'';type.value=p.get('credential_type')||'';
    radius.value=['10','25','50','75','100'].includes(p.get('radius'))?p.get('radius'):'25';tab=p.get('results')==='companies'?'companies':'professionals';
    page=/^[1-9]\d{0,4}$/.test(p.get('page')||'')?Number(p.get('page')):1;
    form.querySelector('.advanced').open=Boolean(city.value||state.value||issuer.value||type.value||radius.value!=='25');
  }
  function queryParams(){
    const p=new URLSearchParams({view:'companies',radius:radius.value}),value=q.value.trim();
    const place=locationQuery(value);
    if(/^\d{5}$/.test(value))p.set('zip',value);
    else if(place){state.value=place.state;city.value=place.city;form.querySelector('.advanced').open=true;}
    else if(value)p.set('q',value);
    if(city.value.trim())p.set('city',city.value.trim());if(state.value)p.set('state',state.value);
    if(checkbox.checked)p.set('verified','1');if(issuer.value)p.set('issuer',issuer.value);if(type.value)p.set('credential_type',type.value);
    return p;
  }
  function saveUrl(replace=false){
    const visible=new URLSearchParams(params);visible.delete('view');visible.set('results',tab);if(page>1)visible.set('page',String(page));
    const url=location.pathname+'?'+visible;
    if(url!==location.pathname+location.search)history[replace?'replaceState':'pushState']({},'',url);
  }
  function companyCard(c){
    const card=el('article',undefined,'result company-result'),title=el('div',undefined,'titleLine');
    card.append(el('p',c.match_reason||'Company discovery match','match'));title.append(el('h2',c.company||'Company name unavailable'));
    if(c.public_status==='verified'){const image=el('img');image.src='/VerifySweep-Verified-Company-Badge.png';image.alt='Business identity verified—not certification of every technician';image.width=38;image.height=41;image.className='verifiedMark';title.append(image);}
    title.append(el('span',c.display_status||'UNVERIFIED','status'));card.append(title);
    const people=ui.groupPeople([c]),current=people.filter(p=>p.credentials.some(r=>r.display_status==='CREDENTIAL VERIFIED'));
    card.append(el('p',current.length?current.length+' named professional'+(current.length===1?'':'s')+' with current verified credentials on file.':'No independently verified professional credential is currently associated with this listing. This is not a negative finding.','small'));
    if(people.length){const names=el('p');names.append(el('b','Named professionals: '),document.createTextNode(people.map(p=>p.holder).join(', ')));card.append(names);}
    if(c.ranking_explanation&&current.length)card.append(el('p',c.ranking_explanation,'small'));
    const areas=[...new Set(c.service_area_labels||[])];
    if(c.matched_service_area){const match=[c.matched_service_area,c.matched_service_state].filter(Boolean).join(', ');areas.sort((a,b)=>Number(b===match)-Number(a===match));}
    if(areas.length){const tags=el('div',undefined,'tags');areas.slice(0,5).forEach(a=>tags.append(el('span','Serves '+a,'tag')));card.append(tags);
      if(areas.length>5){const details=el('details');details.append(el('summary','View all '+areas.length+' published service areas'),el('p',areas.join(' · ')));card.append(details);}
    }else card.append(el('p','Published service areas are not yet documented in this record. Confirm coverage with the company.','small'));
    if(typeof c.distance==='number'&&Number.isFinite(c.distance))card.append(el('p','Business location is approximately '+c.distance.toFixed(1)+' miles from the searched ZIP. This is not a service boundary.','small'));
    const actions=el('div',undefined,'actions');actions.append(anchor('View Company & Professionals','/company-profile.html?id='+encodeURIComponent(c.id)+'&return='+encodeURIComponent(location.pathname+location.search)));
    const site=safeUrl(c.website);if(site){const a=anchor('Company Website',site,'btn alt');a.target='_blank';a.rel='noopener noreferrer';actions.append(a);}card.append(actions);
    card.append(el('p','A company listing, logo, or claim does not establish every technician’s credentials.','small'));return card;
  }
  function render({focus=false,replace=false}={}){
    const people=ui.groupPeople(rows),current=people.filter(p=>p.credentials.some(c=>c.display_status==='CREDENTIAL VERIFIED'));
    const list=tab==='professionals'?people:rows,pages=Math.max(1,Math.ceil(list.length/PAGE_SIZE));page=Math.min(page,pages);saveUrl(replace);
    out.replaceChildren();
    const summary=el('section',undefined,'guide searchSummary'),place=meta.resolved_location;
    summary.append(el('h2',place?[place.city,place.state].filter(Boolean).join(', '):[params.get('q')||params.get('zip'),params.get('city'),stateNames[params.get('state')]||params.get('state')].filter(Boolean).join(' · ')||'Filtered directory results'));
    if(params.has('state'))summary.append(el('p','Location restricted to '+stateNames[params.get('state')]+(params.has('city')?' — '+params.get('city'):'')+'. Matches require a business location or recorded service area here.','small'));
    summary.append(el('p',people.length+' named professionals with credential records · '+current.length+' with currently verified credentials · '+rows.length+' company discovery records'));
    if(params.has('zip'))summary.append(el('p','Requested radius: '+params.get('radius')+' miles. Published service-area matches may also be included.','small'));
    summary.append(el('p',meta.coverage_notice||'Coverage varies by location and is not comprehensive.','small'));out.append(summary);
    const controls=el('div',undefined,'actions result-switch');controls.setAttribute('role','group');controls.setAttribute('aria-label','Result type');
    for(const [value,label,count] of [['professionals','Professionals',people.length],['companies','Companies',rows.length]]){
      const button=el('button',label+' ('+count+')',tab===value?'btn':'btn alt');button.type='button';button.setAttribute('aria-pressed',String(tab===value));
      button.addEventListener('click',()=>{tab=value;page=1;render({focus:true});});controls.append(button);
    }out.append(controls);
    const heading=el('h2',tab==='professionals'?'Verify the person—not just the company':'Companies matching this search');heading.tabIndex=-1;heading.id='resultHeading';out.append(heading);
    out.append(el('p',tab==='professionals'?'Each person is shown with their listed company and separate credential records. A listed company relationship is not the same as verified employment.':'Company discovery is not certification, endorsement, or proof that every technician is qualified.','small'));
    if(!list.length){const empty=el('div',undefined,'empty');empty.append(el('h3',tab==='professionals'?'No matching professional credential records are currently on file.':'No company records match these filters.'),el('p','This does not mean no qualified professional serves the area. Try another spelling, broaden the filters, or use the official directories below.'));
      if(tab==='professionals'&&rows.length){const button=el('button','Browse '+rows.length+' matching companies','btn');button.addEventListener('click',()=>{tab='companies';page=1;render({focus:true});});empty.append(button);}out.append(empty);
    }else{
      const start=(page-1)*PAGE_SIZE;out.append(el('p','Showing '+(start+1)+'–'+Math.min(start+PAGE_SIZE,list.length)+' of '+list.length+' '+tab,'small page-count'));
      list.slice(start,start+PAGE_SIZE).forEach(item=>out.append(tab==='professionals'?ui.personCard(item,{returnTo:location.pathname+location.search}):companyCard(item)));
      if(pages>1){const nav=el('nav',undefined,'actions pagination');nav.setAttribute('aria-label','Results pages');for(const [label,next] of [['Previous',page-1],['Next',page+1]]){const b=el('button',label,'btn');b.disabled=next<1||next>pages;b.addEventListener('click',()=>{page=next;render({focus:true});});nav.append(b);}nav.append(el('span','Page '+page+' of '+pages));out.append(nav);}
    }
    if(focus){heading.focus();heading.scrollIntoView({block:'center'});}
  }
  async function search({restorePage=false}={}){
    const ticket=++sequence;if(active)active.abort();active=null;params=queryParams();if(!restorePage){page=1;tab='professionals';}
    if(![...params.keys()].some(k=>!['view','radius'].includes(k))){out.replaceChildren(el('p','Enter a location or choose a credential filter.','empty'));out.removeAttribute('aria-busy');return;}
    const controller=new AbortController();active=controller;let timedOut=false;const timer=setTimeout(()=>{timedOut=true;controller.abort();},20000);
    out.setAttribute('aria-busy','true');out.replaceChildren(el('p','Searching directory records…','empty'));
    try{const r=await fetch('/api/directory?'+params,{signal:controller.signal,headers:{Accept:'application/json'}}),data=await r.json();if(ticket!==sequence)return;
      if(!r.ok)throw new Error(data.error||'Search unavailable.');if(!Array.isArray(data.results))throw new Error('The directory returned an incomplete response. Please try again.');rows=data.results;meta=data;render({replace:restorePage});
    }catch(error){if(ticket!==sequence)return;const box=el('div',undefined,'empty');box.append(el('h2','Directory search could not be completed.'),el('p',timedOut?'The search took too long. Please try again or use the official directory links below.':error instanceof SyntaxError?'The directory returned an unreadable response. Please try again.':error.message||'Please try again.'),el('p','A source outage is not evidence that a person lacks a credential.','small'));out.replaceChildren(box);
    }finally{clearTimeout(timer);if(ticket===sequence){active=null;out.removeAttribute('aria-busy');}}
  }
  form.addEventListener('submit',event=>{event.preventDefault();search();});
  checkbox.addEventListener('change',()=>{review.value=checkbox.checked?'1':'';search();});review.addEventListener('change',()=>{checkbox.checked=review.value==='1';});
  reset.addEventListener('click',()=>{++sequence;if(active)active.abort();active=null;form.reset();q.value='';city.value='';state.value='';issuer.value='';type.value='';review.value='';checkbox.checked=false;radius.value='25';form.querySelector('.advanced').open=false;out.replaceChildren(el('p','Enter a location or choose a credential filter.','empty'));out.removeAttribute('aria-busy');history.pushState({},'',location.pathname);q.focus();});
  addEventListener('popstate',()=>{restore();search({restorePage:true});});
  restore();if(q.value||city.value||state.value||checkbox.checked||issuer.value||type.value)search({restorePage:true});
})();
