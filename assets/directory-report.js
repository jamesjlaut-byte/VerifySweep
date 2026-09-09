'use strict';
(() => {
  const params = new URLSearchParams(location.search);
  const type = params.get('target_type') || '';
  const id = params.get('target_id') || '';
  const name = params.get('name') || 'directory record';
  const form = document.getElementById('form');
  const message = document.getElementById('message');
  const button = form.querySelector('button[type="submit"]');
  let submitting = false, received = false;
  document.getElementById('subject').textContent = 'Record: ' + name;
  function showMessage(text) {
    message.textContent = text;
    message.focus();
    message.scrollIntoView({block: 'center'});
  }
  if (!['company', 'professional'].includes(type) || !/^[A-Za-z0-9_-]{1,160}$/.test(id)) {
    form.hidden = true;
    form.before(message);
    showMessage('Open a directory profile and select REPORT A PROBLEM. A valid profile reference is required.');
    return;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || received) return;
    submitting = true;
    button.disabled = true;
    button.textContent = 'SAVING REPORT…';
    form.setAttribute('aria-busy', 'true');
    message.textContent = 'Saving your report. Please wait…';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    const uncertain = 'We could not confirm whether your report was saved. Your entries are preserved. Contact info@verifysweep.com before submitting again.';
    try {
      const response = await fetch('/api/directory', {
        method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, signal: controller.signal,
        body: JSON.stringify({action: 'report_problem', target_type: type, target_id: id,
          reason: document.getElementById('reason').value, details: document.getElementById('details').value,
          source_url: document.getElementById('source').value, reporter_email: document.getElementById('email').value,
          website: document.getElementById('website').value})
      });
      let data;
      try { data = await response.json(); } catch { throw new Error(uncertain); }
      if (!response.ok) throw new Error(data.error || uncertain);
      if (data.status !== 'pending' || !/^\d+$/.test(String(data.id))) throw new Error(uncertain);
      received = true;
      const reference = 'VS-REPORT-' + data.id;
      const receipt = document.createElement('section');
      receipt.className = 'receipt'; receipt.tabIndex = -1; receipt.setAttribute('role', 'status');
      for (const [tag, text] of [
        ['h2', 'Report received'], ['p', 'Reference: ' + reference + ' · Status: Pending review'],
        ['p', 'Your report is saved for human review. You do not need to submit it again. A report does not automatically change a listing or verification status.'],
        ['p', 'No automatic email has been sent. Save this reference for your records.']
      ]) { const node = document.createElement(tag); node.textContent = text; receipt.append(node); }
      const email = document.createElement('a');
      email.textContent = 'Email VerifySweep about this report';
      email.href = 'mailto:info@verifysweep.com?subject=' + encodeURIComponent('Directory report ' + reference) + '&body=' + encodeURIComponent('Reference: ' + reference + '\nProfile: ' + name + '\nProfile ID: ' + id);
      receipt.append(email);
      const note = document.createElement('p'); note.textContent = 'This opens your email app; you must send the email.'; receipt.append(note);
      const back = document.createElement('a'); back.href = '/find-a-pro.html'; back.textContent = 'Return to the directory'; receipt.append(back);
      form.hidden = true; form.before(receipt); receipt.focus(); receipt.scrollIntoView({block: 'start'});
    } catch (error) {
      showMessage(error.name === 'AbortError' || error instanceof TypeError ? uncertain : error.message || uncertain);
    } finally {
      clearTimeout(timer); submitting = false; button.disabled = false; button.textContent = 'SUBMIT FOR REVIEW'; form.removeAttribute('aria-busy');
    }
  });
})();
