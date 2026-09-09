'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const queues = {
    claims: {view:'admin_claims', key:'claims', action:'review_profile_claim', id:'claim_id', statuses:['pending','needs_evidence','approved','rejected','withdrawn'], limit:200},
    reports: {view:'admin_reports', key:'reports', action:'review_report', id:'report_id', statuses:['pending','reviewing','resolved','dismissed'], limit:200},
    submissions: {view:'admin_submissions', key:'submissions', action:'review_credential_submission', id:'submission_id', statuses:['pending','reviewing','needs_evidence','ready_for_verification','rejected','withdrawn'], limit:250},
    reverification: {view:'admin_reverification', key:'records', statuses:[], limit:250}
  };
  let token = '', reviewer = '', generation = 0, loading = false, saving = false;
  const requests = new Set();
  const el = (tag, text, cls) => {const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
  const label = value => value.replaceAll('_',' ');
  function message(text){$('message').textContent=text;}
  function busy(value){loading=value;['queue','status','refresh'].forEach(id=>$(id).disabled=value||saving);}
  function lock(){token='';reviewer='';generation++;requests.forEach(c=>c.abort());requests.clear();$('records').replaceChildren();$('count').textContent='';$('workspace').hidden=true;$('access').hidden=false;$('access').reset();busy(false);message('Review session cleared.');}
  async function request(query, payload){
    const controller=new AbortController();requests.add(controller);const timer=setTimeout(()=>controller.abort(),25000);
    try{
      const response=await fetch('/api/directory'+query,{method:payload?'POST':'GET',credentials:'omit',cache:'no-store',redirect:'error',signal:controller.signal,headers:{Authorization:'Bearer '+token,'X-VerifySweep-Reviewer':reviewer,'Content-Type':'application/json'},...(payload?{body:JSON.stringify(payload)}:{})});
      if(response.status===403){lock();throw new Error('Admin authorization was rejected. Enter the existing directory admin token.');}
      let data;try{data=await response.json();}catch{throw new Error('The server response could not be confirmed. Refresh the queue before retrying a saved review.');}
      if(!response.ok)throw new Error(data.error||'The review request failed.');return data;
    }catch(error){if(error.name==='AbortError')throw new Error('The request timed out or the session was cleared. Refresh the queue to confirm its status before retrying a review.');throw error;}
    finally{clearTimeout(timer);requests.delete(controller);}
  }
  function configure(){const q=queues[$('queue').value];$('status').replaceChildren(...q.statuses.map(s=>{const option=el('option',label(s));option.value=s;return option;}));$('status').parentElement.hidden=!q.statuses.length;}
  function sourceLink(url){try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))return null;const a=el('a','Open submitted source (unverified)');a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}}
  function card(record, q, epoch){
    const box=el('article',undefined,'card');box.append(el('h2',record.professional_name||record.claimant_name||'Record '+(record.id||record.credential_id)));
    const fields=[['Reference',record.id||record.credential_id],['Target', [record.target_type,record.target_id].filter(Boolean).join(' ')],['Company',record.company],['Status',record.review_status||record.status||record.review_reason],['Reason',record.reason],['Submitted details',record.details||record.submission_notes_private],['Contact (private)',record.claimant_email_private||record.reporter_email_private||record.submitter_email_private],['Business phone (private)',record.business_phone_private],['Credential',record.credential_type||record.credential],['Issuer',record.issuer],['Expiration',record.expiration_date],['Review due',record.recheck_due_at],['Created',record.created_at],['Last reviewer',record.reviewed_by],['Previous review note (private)',record.review_note]];
    const details=el('dl');fields.forEach(([name,value])=>{if(value!==undefined&&value!==null&&String(value)!=='')details.append(el('dt',name),el('dd',String(value)));});box.append(details);
    const links=el('p',undefined,'links');const source=sourceLink(record.evidence_url_private||record.source_url||record.credential_source||record.official_source_url);if(source)links.append(source);
    if(['company','professional'].includes(record.target_type)&&/^[A-Za-z0-9_-]{1,160}$/.test(String(record.target_id))){const a=el('a','View public profile');a.href='/'+(record.target_type==='company'?'company-profile':'professional-profile')+'.html?id='+encodeURIComponent(record.target_id);a.target='_blank';a.rel='noopener noreferrer';links.append(a);}box.append(links);
    if(!q.action)return box;
    const form=el('form');const statusLabel=el('label','Review decision'),select=el('select');select.required=true;select.append(el('option','Choose a decision'));select.firstChild.value='';q.statuses.filter(s=>s!=='pending').forEach(s=>{const option=el('option',label(s));option.value=s;select.append(option);});statusLabel.append(select);
    const noteLabel=el('label','Evidence and decision note (private)'),note=el('textarea');note.required=true;note.minLength=5;note.maxLength=1000;noteLabel.append(note);const button=el('button','SAVE REVIEW'),feedback=el('p',undefined,'feedback');feedback.setAttribute('role','status');form.append(statusLabel,noteLabel,button,feedback);box.append(form);
    form.addEventListener('submit',async event=>{event.preventDefault();if(saving||loading||!token)return;if(!confirm('Save this review decision? This changes only the queue status, not public facts or access.'))return;saving=true;button.disabled=true;busy(false);feedback.textContent='Saving review…';
      try{const data=await request('',{action:q.action,[q.id]:record.id,status:select.value,review_note:note.value});if(epoch!==generation)return;if(String(data.id)!==String(record.id)||(data.review_status||data.status)!==select.value)throw new Error('Review result could not be confirmed. Refresh before retrying.');feedback.textContent='Saved: '+label(select.value)+'. No public verification status or listing was changed.';select.disabled=true;note.disabled=true;button.hidden=true;}
      catch(error){if(epoch===generation)feedback.textContent=error.message;}
      finally{saving=false;button.disabled=false;busy(false);}
    });return box;
  }
  async function load(){if(!token||saving)return;const epoch=++generation,q=queues[$('queue').value];busy(true);$('records').replaceChildren();message('Loading private review queue…');
    try{const data=await request('?view='+q.view+($('status').value?'&status='+encodeURIComponent($('status').value):''));if(epoch!==generation)return;if(!Array.isArray(data[q.key]))throw new Error('Invalid queue response.');$('workspace').hidden=false;$('access').hidden=true;$('token').value='';$('count').textContent=data[q.key].length+' records shown (up to '+q.limit+' per queue).';$('records').replaceChildren(...data[q.key].map(r=>card(r,q,epoch)));message(data[q.key].length?'Queue loaded. Review source evidence before recording decisions.':'No records in this queue/status.');}
    catch(error){if(epoch===generation||!token)message(error.message);}
    finally{if(epoch===generation)busy(false);}
  }
  $('access').addEventListener('submit',event=>{event.preventDefault();token=$('token').value.trim();reviewer=$('reviewer').value.trim();if(!token||!reviewer)return;load();});
  $('queue').addEventListener('change',()=>{configure();load();});$('status').addEventListener('change',load);$('refresh').addEventListener('click',load);$('lock').addEventListener('click',lock);
  addEventListener('pagehide',lock);configure();
})();
