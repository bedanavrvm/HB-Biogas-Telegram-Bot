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
        staff:p.staff,required:true,session_status:'',slots:[{key:`signature_${index}`,type:'signature',
          document_key:'primary',required:true,completed:p.complete}]}))}}};
}

async function mount(page, {approved=false,dark=false}={}) {
  const errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  let payload;
  await page.route('**/*', async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1') return route.abort();
    if(url.pathname==='/origination/') return route.fulfill({contentType:'text/html',body:template});
    if(url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],
      capabilities:{user_id:2,can_create:false,can_review:false,can_start_signing:false,can_staff_sign:true,
        staff_signer_roles:['branch_manager']}}});
    if(url.pathname.endsWith('/applications/')) return route.fulfill({json:{ok:true,applications:[application(approved)],
      capabilities:{user_id:2,can_staff_sign:true,staff_signer_roles:['branch_manager']},pagination:{pages:1,page:1,total:1}}});
    if(url.pathname.endsWith('/staff-signature/')) {
      payload=route.request().postDataJSON();
      return route.fulfill({json:{ok:true,application:application(true)}});
    }
    if(url.pathname.includes(`/applications/${applicationId}/`)) return route.fulfill({json:{ok:true,application:application(approved)}});
    return route.fulfill({json:{ok:true}});
  });
  await page.goto(`http://127.0.0.1/origination/?application=${applicationId}`);
  await page.addStyleTag({path:asset('core','base.css')});
  await page.addStyleTag({content:fs.readFileSync(asset('core','workflow_standard.css'),'utf8').replace(/@import[^;]+;/g,'')});
  await page.addStyleTag({path:asset('origination','loan_origination.css')});
  if(dark) await page.evaluate(()=>{
    document.documentElement.dataset.telegramTheme='dark';
    document.documentElement.dataset.miniappColorScheme='dark';
    for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'}))
      document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
  });
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('origination','loan_origination.js')});
  await expect(page.locator('.signing-workspace')).toBeVisible();
  return {errors,payload:()=>payload};
}

for(const width of [320,360,390,430,1280]) for(const dark of [false,true]) {
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
  await page.locator('[data-staff-consent]').check();
  await page.locator('[data-test-signature-confirm]').click();
  await expect.poll(()=>audit.payload()?.participant_id).toBe('00000000-0000-4000-8000-000000000004');
  expect(audit.payload().signer_role).toBe('branch_manager');
  await page.screenshot({path:info.outputPath('staff-signing-390.png'),fullPage:true});
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
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1') return route.abort();
    if(url.pathname==='/sign/') return route.fulfill({contentType:'text/html',body:markup});
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
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('origination','origination_signing.js')});
  if(!verified) await expect(page.locator('#packet-page')).toBeVisible();
  else await expect(page.locator('#sign-content')).toBeVisible();
}

test('recipient keeps saved signature when SMS fails and resumes on refresh',async({page},info)=>{
  await page.setViewportSize({width:390,height:844});
  await mountRecipient(page);
  await expect(page.locator('#signature-card')).toBeVisible();
  await expect(page.locator('#verification-card')).toBeHidden();
  await page.getByRole('button',{name:'Type',exact:true}).click();
  await page.locator('#typed-name').fill('Synthetic Applicant');
  await page.locator('#packet-consent').check();
  await page.getByRole('button',{name:'Confirm & send code',exact:true}).click();
  await expect(page.locator('#sign-status')).toContainText('Your signature is saved.');
  await expect(page.locator('#signature-card')).toBeHidden();
  await expect(page.locator('#verification-card')).toBeVisible();
  await page.reload();
  await page.addStyleTag({path:asset('core','base.css')});
  await page.addStyleTag({path:asset('origination','origination_signing.css')});
  await page.addScriptTag({path:asset('core','utils.js')});
  await page.addScriptTag({path:asset('origination','origination_signing.js')});
  await expect(page.locator('#sign-status')).toContainText('Your signature is saved.');
  await page.getByRole('button',{name:'Send verification code',exact:true}).click();
  await page.locator('#otp-code').fill('123456');
  await page.screenshot({path:info.outputPath('recipient-verification-390.png'),fullPage:true});
  await page.getByRole('button',{name:'Verify & sign',exact:true}).click();
  await expect(page.locator('#sign-status')).toHaveText('Your signature is complete. The application is approved.');
  await page.screenshot({path:info.outputPath('recipient-complete-390.png'),fullPage:true});
});

test('reopening a completed recipient link does not replace its success message',async({page},info)=>{
  await page.setViewportSize({width:320,height:844});
  await mountRecipient(page,{verified:true});
  await expect(page.locator('#sign-status')).toHaveText('Your signature is complete. The application is approved.');
  await expect(page.locator('#send-otp')).toBeDisabled();
  await expect(page.locator('#verification-card')).toBeHidden();
  await page.screenshot({path:info.outputPath('recipient-approved-320.png'),fullPage:true});
});
