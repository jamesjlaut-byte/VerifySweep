// Uses an existing Playwright installation; all network responses are fixtures.
// PLAYWRIGHT_MODULE=/path/to/playwright node tests/browser/directory-journey.cjs
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const credential=(id,extra={})=>({id,holder:'Person '+id,credential:'Certified Chimney Sweep',issuer:'CSIA',source:'https://example.test/evidence',display_status:'CREDENTIAL VERIFIED',verified_at:'2026-09-01',last_checked_at:'2026-09-01',expiration_date:'2027-09-01',identity_status:'UNKNOWN',company_affiliation_status:'UNKNOWN',...extra});
const companies=Array.from({length:27},(_,i)=>({id:'company-'+i,company:'Company '+i,public_status:'unverified',display_status:'UNVERIFIED',website:'https://example.test',service_area_labels:['Austin, TX','Buda, TX','Blanco, TX','Boerne, TX','Cedar Park, TX','Spring Branch, TX'],matched_service_area:'Austin',matched_service_state:'TX',reviewed_professionals:[credential('person-'+i)]}));
companies[0].reviewed_professionals.push(credential('second',{holder:'Person person-0',credential:'Gas Specialist',issuer:'NFI'}));
companies[1].reviewed_professionals=[credential('unconfirmed',{display_status:'SELF-REPORTED',holder:'<img src=x onerror=alert(1)>'})];
async function run(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try{for(const width of [390,1280]){
  const page=await browser.newPage({viewport:{width,height:900},timezoneId:'America/Chicago',locale:'en-US'}),errors=[],requests=[];
  let mode='normal';page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.pathname==='/api/directory'){
    assert.equal(route.request().method(),'GET');requests.push(u);
    if(mode==='error')return route.fulfill({status:503,json:{error:'Source temporarily unavailable'}});
    if(u.searchParams.has('id')){
     if(u.searchParams.get('view')==='companies')return route.fulfill({json:{result:{...companies[0],professionals:companies[0].reviewed_professionals}}});
     return route.fulfill({json:{result:{...credential('person-0'),holder:'Person person-0',company:'Company 0',state:'TX',company_record_id:'company-0',credentials:companies[0].reviewed_professionals}}});
    }
    if(u.searchParams.get('q')==='slow'){await new Promise(r=>setTimeout(r,200));return route.fulfill({json:{results:[],count:0}}).catch(()=>{});}
    let rows=mode==='empty'?[]:companies;
    if(u.searchParams.get('verified')==='1')rows=rows.filter(c=>c.reviewed_professionals.some(p=>p.display_status==='CREDENTIAL VERIFIED'));
    return route.fulfill({json:{results:rows,count:rows.length,coverage_notice:'Fixture coverage is not comprehensive.'}});
   }
   const file=path.join(root,u.pathname);if(file.startsWith(root+path.sep)&&fs.existsSync(file)&&fs.statSync(file).isFile())return route.fulfill({contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.png')?'image/png':'text/html',body:fs.readFileSync(file)});
   return route.fulfill({status:404});
  });
  await page.goto('https://directory.test/find-a-pro.html?q=Austin%2C%20TX');
  await page.locator('.professional-result').first().waitFor();
  assert.equal(requests[0].searchParams.get('city'),'Austin');assert.equal(requests[0].searchParams.get('state'),'TX');
  assert.equal(await page.locator('.professional-result').count(),12);
  assert.match(await page.locator('.searchSummary').innerText(),/27 named professionals.*26 with currently verified/);
  assert.equal(await page.locator('.professional-result img').count(),0);
  assert.equal(await page.locator('.professional-result').first().getByText('Identity verified',{exact:true}).count(),0);
  await page.getByRole('button',{name:'Next',exact:true}).click();assert.equal(new URL(page.url()).searchParams.get('page'),'2');assert.equal(await page.locator('.professional-result').count(),12);
  await page.getByRole('button',{name:'Next',exact:true}).click();assert.equal(await page.locator('.professional-result').count(),3);assert.equal(await page.getByRole('button',{name:'Next',exact:true}).isDisabled(),true);
  await page.getByRole('button',{name:'Companies (27)',exact:true}).click();assert.equal(await page.locator('.company-result').count(),12);assert.equal(await page.locator('.professional-result').count(),0);
  await page.locator('.company-result details').first().locator('summary').click();assert.match(await page.locator('.company-result details').first().innerText(),/Spring Branch/);
  await page.getByRole('button',{name:'Next',exact:true}).click();const saved=new URL(page.url()).pathname+new URL(page.url()).search;
  await page.locator('.company-result').first().getByRole('link',{name:'View Company & Professionals'}).click();
  await page.locator('#professionals .professional-group').waitFor();assert.equal(await page.locator('#professionals .professional-group').count(),1);assert.equal(await page.locator('#professionals .credential-detail').count(),2);
  assert.equal(await page.getByRole('link',{name:'Back to directory results',exact:true}).getAttribute('href'),saved);
  await page.getByRole('link',{name:'View Professional',exact:true}).click();await page.getByRole('link',{name:'VIEW LISTED COMPANY',exact:true}).waitFor();
  assert.equal(await page.getByRole('link',{name:'Back to Search',exact:true}).getAttribute('href'),saved);
  await page.getByRole('link',{name:'Back to Search',exact:true}).click();await page.locator('.company-result').first().waitFor();assert.equal(new URL(page.url()).searchParams.get('page'),'2');
  await page.locator('#verifiedOnly').check();await page.getByRole('button',{name:'Professionals (26)',exact:true}).waitFor();assert.equal(requests.at(-1).searchParams.get('verified'),'1');
  await page.locator('#clearSearch').click();assert.equal(new URL(page.url()).search,'');assert.equal(await page.locator('#q').inputValue(),'');
  mode='error';await page.locator('#q').fill('Austin');await page.getByRole('button',{name:'FIND & VERIFY',exact:true}).click();await page.getByRole('heading',{name:'Directory search could not be completed.'}).waitFor();
  mode='empty';await page.getByRole('button',{name:'FIND & VERIFY',exact:true}).click();await page.getByRole('heading',{name:'No matching professional credential records are currently on file.'}).waitFor();
  mode='normal';await page.locator('#q').fill('slow');await page.getByRole('button',{name:'FIND & VERIFY',exact:true}).click();await page.locator('#q').fill('latest');await page.getByRole('button',{name:'FIND & VERIFY',exact:true}).click();await page.locator('.professional-result').first().waitFor();await page.waitForTimeout(250);assert.match(await page.locator('.searchSummary').innerText(),/latest/);
  const groups=await page.evaluate(()=>VerifySweepDirectoryUI.groupPeople([{id:'a',company:'A',reviewed_professionals:[{id:'1',holder:'Same Name',issuer:'CSIA',credential:'Sweep'},{id:'1',holder:'Same Name',issuer:'CSIA',credential:'Sweep'}]},{id:'b',company:'B',reviewed_professionals:[{id:'2',holder:'Same Name',issuer:'CSIA',credential:'Sweep'}]}]).map(p=>p.credentials.length));assert.deepEqual(groups,[1,1]);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  const conflicting=await page.evaluate(()=>VerifySweepDirectoryUI.groupPeople([{id:'a',reviewed_professionals:[{id:'1',holder:'Person',credential:'Sweep',display_status:'EXPIRED'},{id:'2',holder:'Person',credential:'Sweep',display_status:'CREDENTIAL VERIFIED'}]}])[0].credentials.length);assert.equal(conflicting,2);
  await page.locator('#resultHeading').scrollIntoViewIfNeeded();
  await page.screenshot({path:'/private/tmp/verifysweep-directory-'+width+'.png',fullPage:false});
  console.log(width,'PASS: location parsing, grouping, trust counts, paging, company/profile links, return state, filters, errors, empty, racing requests, safe text, responsive layout');
  await page.close();
 }}finally{await browser.close();}
}
run().catch(error=>{console.error(error);process.exitCode=1;});
