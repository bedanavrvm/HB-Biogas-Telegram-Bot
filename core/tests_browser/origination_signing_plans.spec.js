'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = (owner, name) => path.join(root, owner, 'static', 'miniapp', name);
const applicationId = '00000000-0000-4000-8000-000000000123';
const packageId = '00000000-0000-4000-8000-000000000321';
const template = fs.readFileSync(path.join(root,'origination/templates/loan_origination/app.html'),'utf8')
  .replace(/\{%[\s\S]*?%\}/g,'').replace(/<script[\s\S]*?<\/script>/g,'').replace(/<link[^>]+>/g,'')
  .replace('src=""',`src="data:image/png;base64,${fs.readFileSync(asset('core','jawabu-logo.png')).toString('base64')}"`);

function application(approved = false) {
  const roles = ['borrower', 'borrower', 'officer', 'branch_manager'];
  const people = roles.map((role,index) => ({id:`00000000-0000-4000-8000-00000000000${index+1}`,
    role,name:index===1 ? 'Synthetic joint applicant with a longer readable name' : `Synthetic person ${index+1}`,
    staff:index>1,complete:approved || index===2,can_sign:!approved && index===3}));
  return {id:applicationId,reference_number:'ORG-SYNTHETIC-PLAN',product_name:'Synthetic Loan',
    status:approved ? 'approved' : 'partially_signed',officer_id:1,revision:4,branch:'Synthetic branch',
    applicant_summary:{name:'Synthetic Applicant'}, form_schema:{fields:[],sections:[{key:'applicant',label:'Applicant'}]},
    form_payload:{},product_terms:{},requirement_evidence:[],
    document_packet:{documents:[{key:'primary',name:'Main LAF',role:'primary',selected:true,applicable:true,schema:{fields:[]}}]},
    signing_workspace:{policy:'all_required',status_label:approved?'Approved':'Awaiting signatures',
      required_count:4,completed_count:approved?4:1,can_recall:false,participants:people},
    activity:[{label:'Submitted for signing',actor:'Synthetic Officer',at:'2026-10-12T06:00:00Z'}],
    signing_package:{id:packageId,status:approved?'fully_signed':'in_progress',verified_signing:{enabled:true,
      test_mode:false,archive_status:approved?'uploaded':'not_ready',production_stamps:[],packet_version:'synthetic-v1',
      participants:people.map((p,index)=>({role:p.role,participant_id:p.id,name:p.name,label:p.role.replaceAll('_',' '),
        signed_at:p.complete?'2026-10-13T09:15:00Z':'',
        staff:p.staff,required:true,session_status:'',slots:[{key:`signature_${index}`,type:'signature',
          document_key:'primary',required:true,completed:p.complete}]}))}}};
}

async function mount(page, {approved=false,dark=false,download=''}={}) {
  const errors=[];
  const queries=[];
  page.on('pageerror', error=>errors.push(error.message));
  let payload;
  await page.route('**/*', async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1') return route.abort();
    if(url.pathname==='/origination/') return route.fulfill({contentType:'text/html',body:template});
    if(url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],
      capabilities:{user_id:2,can_create:false,can_review:false,can_start_signing:false,can_staff_sign:true,
        staff_signer_roles:['branch_manager']}}});
    if(url.pathname.endsWith('/applications/')) {
      queries.push(url.search);
      return route.fulfill({json:{ok:true,applications:[application(approved)],
        status_group_options:[{value:'draft',label:'Draft'},{value:'changes',label:'Needs changes'},
          {value:'progress',label:'In progress'},{value:'completed',label:'Completed'},{value:'closed',label:'Closed'}],
        capabilities:{user_id:2,can_staff_sign:true,staff_signer_roles:['branch_manager']},pagination:{pages:1,page:1,total:1}}});
    }
    if(url.pathname.endsWith('/staff-signature/')) {
      payload=route.request().postDataJSON();
      return route.fulfill({json:{ok:true,application:application(true)}});
    }
    if(url.pathname.endsWith('/signature-preview/')) {
      const values=route.request().postDataJSON();
      const image=execFileSync(path.join(root,'.venv','Scripts','python.exe'),['-c',
        'import json,sys; from origination.services.signature_appearance import preview_capture; print(json.dumps(preview_capture(sys.argv[1],sys.argv[2])))',values.name,values.font],{cwd:root,encoding:'utf8'});
      return route.fulfill({json:{ok:true,...JSON.parse(image)}});
    }
    if(url.pathname.endsWith('/download/')) {
      payload=route.request().postDataJSON();
      return route.fulfill({json:{ok:true,download_url:'http://127.0.0.1/copy.pdf',
        filename:`ORG-SYNTHETIC-PLAN-${approved?'SIGNED':'UNSIGNED'}.pdf`,copy_type:approved?'signed':'unsigned'}});
    }
    if(url.pathname.includes(`/applications/${applicationId}/`)) return route.fulfill({json:{ok:true,application:application(approved)}});
    return route.fulfill({json:{ok:true}});
  });
  await page.goto(`http://127.0.0.1/origination/?application=${applicationId}`);
  if(download) await page.evaluate(mode=>{
    window.__downloads=[];
    window.Telegram={WebApp:{initData:'synthetic-download',ready(){},expand(){},onEvent(){},isVersionAtLeast(){return true},
      downloadFile(parameters,callback){window.__downloads.push(parameters);if(mode==='throw')throw new Error('unsupported');callback(mode!=='cancel');}}};
    if(mode==='browser') delete window.Telegram.WebApp.downloadFile;
  }, download);
  await page.addStyleTag({path:asset('core','base.css')});
  await page.addStyleTag({content:fs.readFileSync(asset('core','workflow_standard.css'),'utf8').replace(/^@import[^\r\n]*;\s*$/gm,'')});
  await page.addStyleTag({path:asset('origination','loan_origination.css')});
  await page.addStyleTag({path:asset('origination','origination_signing_completion.css')});
  await page.addStyleTag({path:asset('origination','origination_compact.css')});
  await page.addStyleTag({path:asset('origination','signature_appearance.css')});
  if(dark) await page.evaluate(()=>{
    document.documentElement.dataset.telegramTheme='dark';
    document.documentElement.dataset.miniappColorScheme='dark';
    for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'}))
      document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
  });
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('core','secure_media_viewer.js')});
  await page.addScriptTag({path:asset('origination','origination_signing_completion.js')});
  await page.addScriptTag({path:asset('origination','signature_appearance.js')});
  await page.addScriptTag({path:asset('origination','loan_origination.js')});
  await expect(page.locator('.signing-workspace')).toBeVisible();
  return {errors,payload:()=>payload,queries};
}

test('grouped status filter uses five plain choices and the grouped API parameter', async({page})=>{
  const audit=await mount(page);
  await page.getByRole('button',{name:'Back to applications',exact:true}).click();
  await page.getByRole('button',{name:'Filters',exact:true}).click();
  await expect(page.getByLabel('Status')).toContainText('Needs changes');
  await expect(page.getByLabel('Status').locator('option')).toHaveCount(6);
  await page.getByLabel('Status').selectOption('completed');
  await page.getByRole('button',{name:'Apply filters',exact:true}).click();
  await expect.poll(()=>audit.queries.some(query=>query.includes('status_group=completed') && !query.includes('&status='))).toBe(true);
});

for(const width of [320,390,768,1280]) test(`internal preview toolbar and zoomed edge swipe ${width}`, async({page},info)=>{
  await page.setViewportSize({width,height:844});
  await mount(page);
  await page.route('**/current-signing-packet/**', route=>route.fulfill({contentType:'image/svg+xml',
    body:'<svg xmlns="http://www.w3.org/2000/svg" width="595" height="842"><rect width="100%" height="100%" fill="white"/><text x="20" y="40">Synthetic document</text></svg>',
    headers:{'X-Preview-Page-Count':'2','X-Signing-Packet-Version':'synthetic-v1'}}));
  await page.getByRole('button',{name:'Review documents',exact:true}).click();
  await expect(page.locator('#preview-page')).toHaveText('Page 1 of 2');
  expect(await page.locator('.preview-toolbar button').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label'))))
    .toEqual(['Previous page','Zoom out','Reset zoom','Zoom in','Refresh preview','Next page']);
  const stage=page.locator('#document-preview-stage');
  await stage.dispatchEvent('pointerdown',{pointerId:51,clientX:220,clientY:200});
  await stage.dispatchEvent('pointerup',{pointerId:51,clientX:100,clientY:200});
  await expect(page.locator('#preview-page')).toHaveText('Page 2 of 2');
  await page.getByRole('button',{name:'Zoom in',exact:true}).click();
  await stage.dispatchEvent('pointerdown',{pointerId:52,clientX:100,clientY:200});
  await stage.dispatchEvent('pointermove',{pointerId:52,clientX:1000,clientY:200});
  await stage.dispatchEvent('pointerup',{pointerId:52,clientX:1000,clientY:200});
  await stage.dispatchEvent('pointerdown',{pointerId:53,clientX:100,clientY:200});
  await stage.dispatchEvent('pointerup',{pointerId:53,clientX:240,clientY:200});
  await expect(page.locator('#preview-page')).toHaveText('Page 1 of 2');
  await expect(stage).toHaveAttribute('data-zoom','1');
  await page.screenshot({path:info.outputPath(`internal-preview-${width}.png`),fullPage:true});
});

for (const mode of ['native','cancel','throw','browser']) test(`application download ${mode} handoff names the copy without false success`, async({page})=>{
  await page.setViewportSize({width:390,height:844});
  const audit=await mount(page,{download:mode});
  await page.getByRole('button',{name:'Download application',exact:true}).click();
  await expect(page.locator('#origination-toast')).toContainText(mode==='cancel'?'Download cancelled.':'Download requested: ORG-SYNTHETIC-PLAN-UNSIGNED.pdf');
  expect(audit.payload().revision).toBe(4);
  await expect(page.getByRole('button',{name:'Download application',exact:true})).toBeEnabled();
  expect(audit.errors).toEqual([]);
});

for(const width of [320,360,390,430,768,1280]) for(const dark of [false,true]) {
  test(`participant workspace ${width} ${dark?'dark':'light'}`,async({page},info)=>{
    await page.setViewportSize({width,height:844});
    const audit=await mount(page,{dark});
    await expect(page.locator('.signing-workspace header p')).toHaveText('1 of 4 signers complete');
    await expect(page.locator('.participant-row')).toHaveCount(4);
    const sign=page.getByRole('button',{name:'Sign',exact:true});
    const bounds=await sign.boundingBox();
    expect(bounds.y+bounds.height).toBeLessThan(844);
    const header=await page.locator('.signing-workspace > header').boundingBox();
    const preview=await page.locator('.signing-workspace > header button').boundingBox();
    expect(preview.y+preview.height).toBeLessThanOrEqual(header.y+header.height+1);
    expect(header.height).toBeLessThan(65);
    await expect(page.locator('#origination-prepare-review')).toHaveCount(0);
    await expect(page.locator('#origination-start-signing')).toHaveCount(0);
    await expect(page.locator('.wizard-progress')).toHaveCount(0);
    const overflow=await page.evaluate(()=>[...document.querySelectorAll('button')].filter(el=>el.getClientRects().length)
      .filter(el=>{const r=el.getBoundingClientRect();return r.left < -1 || r.right > innerWidth+1;}).map(el=>el.textContent));
    expect(overflow).toEqual([]);
    expect(audit.errors).toEqual([]);
    await page.screenshot({path:info.outputPath(`signers-${width}-${dark?'dark':'light'}.png`),fullPage:true});
  });
}

test('staff action addresses the individual and approved view is read-only',async({page},info)=>{
  await page.setViewportSize({width:390,height:844});
  const audit=await mount(page);
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await page.locator('[data-test-signature-mode="typed"]').click();
  await page.locator('[data-test-signature-name]').fill('Synthetic Manager');
  await expect(page.locator('.typed-mark-frame img')).toBeVisible();
  await page.locator('[data-staff-consent]').check();
  await page.locator('[data-test-signature-confirm]').click();
  await expect.poll(()=>audit.payload()?.participant_id).toBe('00000000-0000-4000-8000-000000000004');
  expect(audit.payload().signer_role).toBe('branch_manager');
  await expect(page.getByRole('heading',{name:'Signature saved'})).toBeVisible();
  await expect(page.getByText('Application approved.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Stay here',exact:true}).click();
  await expect(page.getByRole('button',{name:'Stay here',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Back to application',exact:true})).toHaveCSS('background-color','rgb(18, 100, 72)');
  await page.screenshot({path:info.outputPath('staff-signing-390.png'),fullPage:true});
  await page.getByRole('button',{name:'Back to application',exact:true}).click();
  await expect(page.locator('.signing-workspace header p')).toHaveText('4 of 4 signers complete');
});

test('approved applications expose signed documents without workflow buttons',async({page},info)=>{
  await page.setViewportSize({width:320,height:844});
  const audit=await mount(page,{approved:true});
  await expect(page.locator('.signing-workspace header p')).toHaveText('4 of 4 signers complete');
  await expect(page.getByRole('button',{name:'View signed documents'})).toBeVisible();
  await expect(page.locator('[data-staff-sign],#origination-recall')).toHaveCount(0);
  expect(audit.errors).toEqual([]);
  await page.screenshot({path:info.outputPath('approved-320.png'),fullPage:true});
});

for(const width of [320,360,390,430,768,1280]) for(const dark of [false,true]) {
  test(`typed signature images and compact actions ${width} ${dark?'dark':'light'}`,async({page},info)=>{
    await page.setViewportSize({width,height:844});
    const audit=await mount(page,{dark});
    await expect(page.locator('.origination-header')).toBeHidden();
    const actions=await page.locator('.editor-document-actions button').evaluateAll(nodes=>nodes.map(node=>{
      const box=node.getBoundingClientRect();return {y:box.y,height:box.height};
    }));
    expect(new Set(actions.map(box=>box.y)).size).toBe(1);
    await page.getByRole('button',{name:'Sign',exact:true}).click();
    await page.locator('[data-test-signature-mode="typed"]').click();
    await page.locator('[data-test-signature-name]').fill("Wanjiku O'Mwangi-Kamau with a longer synthetic name");
    await expect(page.locator('.typed-mark-frame img')).toBeVisible();
    await expect(page.locator('.signature-styles input')).toHaveCount(4);
    await page.getByLabel('Yellowtail',{exact:true}).check();
    await expect(page.locator('.typed-mark-frame img')).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    expect(audit.errors).toEqual([]);
    await page.screenshot({path:info.outputPath(`typed-signature-${width}-${dark?'dark':'light'}.png`),fullPage:true});
    await page.locator('[data-staff-consent]').check();
    await page.locator('[data-test-signature-confirm]').click();
    await expect.poll(()=>audit.payload()?.signature_capture?.font).toBe('yellowtail');
    expect(audit.payload().signature_capture.appearance_version).toBe(2);
  });
}

test('typed preview failure keeps the name and cannot silently sign',async({page})=>{
  const audit=await mount(page);
  await page.route('**/signature-preview/',route=>route.fulfill({status:503,json:{ok:false,error:'Preview unavailable. Retry.'}}));
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await page.locator('[data-test-signature-mode="typed"]').click();
  await page.locator('[data-test-signature-name]').fill('Synthetic Manager');
  await expect(page.locator('.typed-mark-frame [role=status]')).toContainText('Preview unavailable');
  await page.locator('[data-staff-consent]').check();
  await page.locator('[data-test-signature-confirm]').click();
  await expect(page.locator('[data-test-signature-name]')).toHaveValue('Synthetic Manager');
  expect(audit.payload()).toBeUndefined();
});

test('staff countdown returns to the application without closing the Mini App',async({page})=>{
  await mount(page);
  await page.evaluate(()=>{
    window.__closed=0;
    window.Telegram={WebApp:{initData:'synthetic-init',close(){window.__closed++;}}};
  });
  await page.getByRole('button',{name:'Sign',exact:true}).click();
  await page.locator('[data-test-signature-mode="typed"]').click();
  await page.locator('[data-test-signature-name]').fill('Synthetic Manager');
  await expect(page.locator('.typed-mark-frame img')).toBeVisible();
  await page.locator('[data-staff-consent]').check();
  await page.locator('[data-test-signature-confirm]').click();
  await expect(page.getByRole('heading',{name:'Signature saved'})).toBeVisible();
  await page.clock.install();
  await page.clock.runFor(11000);
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await expect(page.locator('.signing-workspace header p')).toHaveText('4 of 4 signers complete');
  expect(await page.evaluate(()=>window.__closed)).toBe(0);
});

function adminMarkup() {
  const source=fs.readFileSync(path.join(root,'origination/templates/admin/origination/application_signers.html'),'utf8');
  const fragment='{% load static %}'+source.slice(source.indexOf('<section'),source.indexOf('</section>')+10);
  const renderer=`
import os, sys
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
import django
django.setup()
from types import SimpleNamespace as N
from django import forms
from django.template import engines
from unfold.widgets import UnfoldAdminSelect2Widget
form=forms.Form()
for key,value in [('revision',1),('plan_revision',1),('request_id','synthetic-request')]:
    form.fields[key]=forms.CharField(initial=value,widget=forms.HiddenInput)
rows=[]
for index,(role,name,staff) in enumerate([('Applicant','Synthetic applicant',False),('Joint applicant','Synthetic joint applicant with a longer name',False),('Officer','',True),('Branch Manager','',True)]):
    selected='participant_'+str(index)
    assigned='assigned_'+str(index)
    form.fields[selected]=forms.BooleanField(initial=True,disabled=index!=1,required=False)
    if staff:form.fields[assigned]=forms.ChoiceField(required=False,choices=[('','Any eligible signer'),('1','Synthetic Officer'),('2','Synthetic Manager with a long name')],widget=UnfoldAdminSelect2Widget)
    rows.append(dict(key=str(index),selected=form[selected],assigned=form[assigned] if staff else None,label=role,name=name,staff=staff,required=index!=1,documents=['Main LAF']))
form.rows=rows
print(engines['django'].from_string(sys.stdin.read()).render(dict(form=form,editable=True,original=N(reference_number='ORG-SYNTHETIC-PLAN',product_definition=N(name='Synthetic Loan')))))
`;
  return '<!doctype html><meta charset="utf-8">'+execFileSync(path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python'),['-c',renderer],{
    cwd:root,input:fragment,encoding:'utf8',env:{...process.env,DATABASE_URL:'sqlite:///:memory:',
      DJANGO_SECRET_KEY:'synthetic-browser-only-'.padEnd(64,'x'),PYTHONUTF8:'1'},
  });
}

for(const width of [320,390,1280]) test(`Admin signers autosave and fit ${width}`,async({page},info)=>{
  const markup=adminMarkup();
  let saves=0;
  await page.route('**/*',route=>{
    if(route.request().method()==='POST') {saves++;return route.fulfill({json:{ok:true,revision:2,plan_revision:2}});}
    return new URL(route.request().url()).hostname==='127.0.0.1'
      ? route.fulfill({contentType:'text/html',body:markup}) : route.abort();
  });
  await page.setViewportSize({width,height:900});
  await page.goto('http://127.0.0.1/admin/synthetic/signers/');
  const adminStatic=path.join(root,'.venv/Lib/site-packages/django/contrib/admin/static/admin');
  const unfoldStatic=path.join(root,'.venv/Lib/site-packages/unfold/static/unfold');
  await page.addStyleTag({path:path.join(unfoldStatic,'css/styles.css')});
  await page.addStyleTag({content:fs.readFileSync(path.join(unfoldStatic,'fonts/material-symbols/styles.css'),'utf8')
    .replace('Material-Symbols-Outlined.woff2',`data:font/woff2;base64,${fs.readFileSync(path.join(unfoldStatic,'fonts/material-symbols/Material-Symbols-Outlined.woff2')).toString('base64')}`)});
  await page.addStyleTag({path:path.join(adminStatic,'css/vendor/select2/select2.css')});
  await page.addStyleTag({path:path.join(adminStatic,'css/autocomplete.css')});
  await page.addStyleTag({path:path.join(root,'origination/static/admin/origination_application_signers.css')});
  await page.addStyleTag({content:'body{padding:12px;font:14px/1.4 Arial,sans-serif}'});
  for(const name of ['js/vendor/jquery/jquery.js','js/vendor/select2/select2.full.js','js/jquery.init.js'])
    await page.addScriptTag({path:path.join(adminStatic,name)});
  await page.addScriptTag({path:path.join(unfoldStatic,'js/select2.init.js')});
  await page.addScriptTag({path:path.join(root,'origination/static/admin/origination_application_signers.js')});
  const dropdown=page.locator('.select2-selection').last();
  await dropdown.click();
  await page.locator('.select2-search__field').fill('Manager');
  await page.getByRole('option',{name:'Synthetic Manager with a long name'}).click();
  await expect(page.locator('[data-save-status]')).toHaveText('Saved');
  expect(saves).toBe(1);
  await expect(page.locator('[name=revision]')).toHaveValue('2');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`admin-signers-${width}.png`),fullPage:true});
});

async function mountRecipient(page,{verified=false}={}) {
  let session={reference:'ORG-SYNTHETIC-PLAN',signer_role:'borrower',phone_masked:'***0001',access_mode:'self_service',
    signing_policy:'all_required',application_status:verified?'approved':'partially_signed',status:verified?'verified':'pending',
    consented:verified,reviewed_pages:[1],packet_version:'synthetic-v1',consent_text:'Synthetic consent: all required signers complete approval.',
    documents:[{name:'Synthetic Loan Application',key:'primary',page_count:1}],otp:{}};
  let sends=0;
  const markup=fs.readFileSync(path.join(root,'origination/templates/loan_origination/sign.html'),'utf8')
    .replace(/\{%[\s\S]*?%\}/g,'').replace(/<script[\s\S]*?<\/script>/g,'').replace(/<link[^>]+>/g,'')
    .replace('src=""',`src="data:image/png;base64,${fs.readFileSync(asset('core','jawabu-logo.png')).toString('base64')}"`);
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1') return route.abort();
    if(url.pathname==='/sign/') return route.fulfill({contentType:'text/html',body:markup});
    if(url.pathname.endsWith('/signature-preview/')) {
      const values=route.request().postDataJSON();
      const rendered=execFileSync(path.join(root,'.venv','Scripts','python.exe'),['-c',
        'import json,sys; from origination.services.signature_appearance import preview_capture; print(json.dumps(preview_capture(sys.argv[1],sys.argv[2])))',values.name,values.font],{cwd:root,encoding:'utf8'});
      return route.fulfill({json:{ok:true,...JSON.parse(rendered)}});
    }
    if(url.pathname.endsWith('/packet/')) return route.fulfill({contentType:'image/svg+xml',
      headers:{'X-Preview-Page-Count':'1','X-Signing-Packet-Version':'synthetic-v1'},
      body:'<svg xmlns="http://www.w3.org/2000/svg" width="595" height="300"><rect width="595" height="300" fill="white"/><text x="30" y="50">Synthetic loan document - no customer data</text></svg>'});
    if(url.pathname.endsWith('/consent/')) session={...session,consented:true};
    if(url.pathname.endsWith('/otp/')) {
      sends++;
      if(sends===1) return route.fulfill({status:503,json:{ok:false,message:'Synthetic SMS temporarily unavailable.'}});
      session={...session,status:'otp_sent',otp:{expires_at:'2099-01-01T00:00:00Z'}};
    }
    if(url.pathname.endsWith('/verify/')) session={...session,status:'verified',application_status:'approved'};
    return route.fulfill({json:{ok:true,session}});
  });
  await page.goto('http://127.0.0.1/sign/#synthetic-bearer-token');
  await page.addStyleTag({path:asset('core','base.css')});
  await page.addStyleTag({path:asset('origination','origination_signing.css')});
  await page.addStyleTag({path:asset('origination','origination_signing_completion.css')});
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('origination','signature_appearance.js')});
  await page.addScriptTag({path:asset('origination','origination_signing_completion.js')});
  await page.addScriptTag({path:asset('origination','origination_signing.js')});
  if(!verified) await expect(page.locator('#packet-page')).toBeVisible();
  else await expect(page.locator('#sign-completion')).toBeVisible();
}

test('recipient keeps saved signature when SMS fails and resumes on refresh',async({page},info)=>{
  await page.setViewportSize({width:390,height:844});
  await mountRecipient(page);
  await expect(page.locator('#signature-card')).toBeVisible();
  await expect(page.locator('#verification-card')).toBeHidden();
  await page.getByRole('button',{name:'Type',exact:true}).click();
  await page.locator('#typed-name').fill('Synthetic Applicant');
  await expect(page.locator('.typed-mark-frame img')).toBeVisible();
  await page.locator('#packet-consent').check();
  await page.getByRole('button',{name:'Save & send code',exact:true}).click();
  await expect(page.locator('#sign-status')).toContainText('Signature saved.');
  await expect(page.locator('#signature-card')).toBeHidden();
  await expect(page.locator('#verification-card')).toBeVisible();
  await page.reload();
  await page.addStyleTag({path:asset('core','base.css')});
  await page.addStyleTag({path:asset('origination','origination_signing.css')});
  await page.addStyleTag({path:asset('origination','origination_signing_completion.css')});
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('origination','origination_signing_completion.js')});
  await page.addScriptTag({path:asset('origination','signature_appearance.js')});
  await page.addScriptTag({path:asset('origination','origination_signing.js')});
  await expect(page.locator('#sign-status')).toContainText('Your signature is saved.');
  await page.getByRole('button',{name:'Resend code',exact:true}).click();
  await page.locator('#otp-code').fill('123456');
  await page.screenshot({path:info.outputPath('recipient-verification-390.png'),fullPage:true});
  await page.getByRole('button',{name:'Finish signing',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Signature saved'})).toBeVisible();
  await expect(page.getByText('Application approved.',{exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath('recipient-complete-390.png'),fullPage:true});
});

test('reopening a completed recipient link does not replace its success message',async({page},info)=>{
  await page.setViewportSize({width:320,height:844});
  await mountRecipient(page,{verified:true});
  await expect(page.getByRole('heading',{name:'Signature saved'})).toBeVisible();
  await expect(page.getByText('Application approved.',{exact:true})).toBeVisible();
  await expect(page.locator('#verification-card')).toBeHidden();
  await page.screenshot({path:info.outputPath('recipient-approved-320.png'),fullPage:true});
});
