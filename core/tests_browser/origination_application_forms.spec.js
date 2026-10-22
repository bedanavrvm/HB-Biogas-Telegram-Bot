'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
// Render Django's complete shell, including its real stylesheet/script order.
// Only identity, operational API I/O and the Telegram client are synthetic.
const shell = execFileSync(path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python'), ['-c',
  "import django; django.setup(); from django.template.loader import render_to_string; print(render_to_string('loan_origination/app.html'))"],
  {cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8',DJANGO_SETTINGS_MODULE:'config.settings',DATABASE_URL:'sqlite:///:memory:',
    DJANGO_SECRET_KEY:'synthetic-origination-browser-only-'+ '0'.repeat(32),SENTRY_DSN:'',TELEGRAM_BOT_TOKEN:''}});
const clone = value => JSON.parse(JSON.stringify(value));

async function boot(page, {linked=false, failure=false, dark=false, width=360, delay=0, configure=()=>{}}={}) {
  await page.setViewportSize({width,height:844});
  const field = (key, section_key, subject='applicant', owner={kind:'main',section_key}) => ({
    key, label:key.replaceAll('_',' '),type:'text',section_key,input_owner:owner,
    value_contract:{version:2,scope:'application',source:'entered',subject},
  });
  const fields = [field('applicant_name','applicant'),field('applicant_phone','applicant'),field('applicant_id_number','applicant'),
    ...['name','id_number','phone'].map(key=>field(`spouse_${key}`,'applicant','spouse')),
    ...[1,2].flatMap(n=>['name','id_number','phone'].map(key=>field(`guarantor_${n}_${key}`,'guarantors',`guarantor_${n}`))),
    field('guaranteed_amount','document_details','loan',{kind:'document',document_key:'guarantee'})];
  const shared = fields.find(item=>item.key==='applicant_name');
  const amount = fields.at(-1);
  const note = {...field('guarantee_notes','undertaking','document'),value_contract:{scope:'document',source:'entered'}};
  const app = {id:'00000000-0000-4000-8000-000000000061',officer_id:1,revision:1,status:'draft',
    reference_number:'ORG-SYNTHETIC-FORMS',display_reference:'ORG-12',product_name:'Synthetic loan',branch:'Synthetic branch',
    applicant_summary:{name:'Synthetic Wanjiku Mwangi-Kamau',phone:'0700000001',national_id:'00099001'},
    value_contract_version:2,form_projection_version:1,product_terms:{},
    form_payload:{applicant_name:'Synthetic Wanjiku Mwangi-Kamau',applicant_phone:'0700000001',applicant_id_number:'00099001',
      spouse_name:'Synthetic spouse',spouse_id_number:'00099002',spouse_phone:'0700000002',
      guarantor_1_name:'Synthetic first',guarantor_1_id_number:'00099003',guarantor_1_phone:'0700000003',
      guarantor_2_name:'Synthetic spouse',guarantor_2_id_number:'00099002',guarantor_2_phone:'0700000002',
      _person_role_bindings:linked?{guarantor_2:'spouse'}:{}},
    person_role_fields:Object.fromEntries(['spouse','guarantor_1','guarantor_2'].map(role=>[role,{name:`${role}_name`,national_id:`${role}_id_number`,phone:`${role}_phone`}])),
    form_schema:{sections:[{key:'applicant',label:'Applicant'},{key:'guarantors',label:'Guarantors'},
      {key:'document_details',label:'Document details'}],fields},
    document_packet:{documents:[{key:'guarantee',name:'Guarantor form',role:'supporting',selected:true,applicable:true,
      field_payload:{applicant_name:'Stale document name',guarantee_notes:''},resolved_values:{applicant_name:'Synthetic Wanjiku Mwangi-Kamau'},
      schema:{sections:[{key:'undertaking',label:'Undertaking'}],fields:[shared,amount,note]}},
    {key:'confirmation',name:'Confirmation',role:'supporting',selected:true,applicable:true,field_payload:{},
      resolved_values:{applicant_name:'Synthetic Wanjiku Mwangi-Kamau'},schema:{sections:[],fields:[shared]}}]},
  };
  configure(app);
  const writes=[]; const previews=[]; const previewBodies=[];
  let fail=failure;
  await page.route('http://127.0.0.1:8161/**',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.pathname==='/') return route.fulfill({contentType:'text/html',body:shell});
    if(url.pathname.startsWith('/static/')) {
      const relative = url.pathname.slice('/static/'.length);
      const file = ['origination/static','core/static'].map(dir=>path.join(root,dir,relative)).find(file=>fs.existsSync(file));
      if(!file) return route.abort();
      const contentType = file.endsWith('.css')?'text/css':file.endsWith('.js')?'application/javascript':file.endsWith('.png')?'image/png':'application/octet-stream';
      return route.fulfill({contentType,body:fs.readFileSync(file)});
    }
    if(url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],capabilities:{can_create:true,user_id:1}}});
    if(url.pathname.endsWith('/applications/')) return route.fulfill({json:{ok:true,applications:[app],tab_counts:{action:1,applications:1},status_options:[],pagination:{page:1,pages:1,total:1},capabilities:{can_create:true,user_id:1}}});
    if(url.pathname.includes('/preview/')) {previews.push(url.pathname);previewBodies.push(request.postDataJSON());return route.fulfill({status:503,json:{ok:false,error:'Synthetic preview unavailable'}});}
    if(request.method()==='PATCH'||url.pathname.endsWith('/fields/')) {
      const body=request.postDataJSON();writes.push(clone(body));
      if(delay) await new Promise(resolve=>setTimeout(resolve,delay));
      if(fail) return route.fulfill({status:503,json:{ok:false,error:'Synthetic save failed'}});
      if(body.form_payload) app.form_payload=clone(body.form_payload);
      if(body.payload) {
        const doc=app.document_packet.documents.find(doc=>url.pathname.includes(`/documents/${doc.key}/`));
        for(const [key,value] of Object.entries(body.payload)) {
          if(fields.some(field=>field.key===key)) app.form_payload[key]=value;
          else doc.field_payload[key]=value;
        }
      }
      app.revision++;
      app.applicant_summary.name=app.form_payload.applicant_name;
      for(const doc of app.document_packet.documents) doc.resolved_values.applicant_name=app.form_payload.applicant_name;
    }
    if(url.pathname.includes(`/applications/${app.id}/`)) return route.fulfill({json:{ok:true,application:clone(app)}});
    return route.abort();
  });
  await page.route('https://telegram.org/**',route=>route.fulfill({contentType:'application/javascript',body:'/* Synthetic Telegram bridge supplied before page scripts. */'}));
  await page.addInitScript(({dark})=>{
    window.__copied=[];Object.defineProperty(navigator,'clipboard',{value:{writeText:async value=>window.__copied.push(value)},configurable:true});
    window.confirm=()=>true;
    window.Telegram={WebApp:{initData:'synthetic-only',colorScheme:dark?'dark':'light',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
    if(dark) document.addEventListener('DOMContentLoaded',()=>{
      for(const [key,value] of Object.entries({'bg-color':'#17201e','secondary-bg-color':'#111816','text-color':'#f4f7f5','hint-color':'#a7b5af'})) document.documentElement.style.setProperty(`--tg-theme-${key}`,value);
    });
  },{dark});
  const reopen = async () => {
  await page.goto('http://127.0.0.1:8161/');
  await page.locator('[data-application-open]').click();
  await page.evaluate(()=>document.fonts.ready);
  };
  await reopen();
  return {app,writes,previews,previewBodies,reopen,retry:()=>{fail=false;}};
}

async function section(page,label) {
  await page.locator('#origination-section-picker').click();
  await page.locator('[data-section-index]').filter({hasText:label}).click();
  await expect(page.locator('#origination-section-picker strong')).toHaveText(label);
}

for(const linked of [false,true]) test(`clear Guarantor 2 persists without changing source (linked=${linked})`,async({page})=>{
  const {app}=await boot(page,{linked});
  await section(page,'Guarantors');
  await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
  expect(app.form_payload._person_role_bindings).not.toHaveProperty('guarantor_2');
  expect(app.form_payload.spouse_name).toBe('Synthetic spouse');
  expect(app.form_payload.guarantor_1_name).toBe('Synthetic first');
  await section(page,'Applicant');await section(page,'Guarantors');
  await expect(page.locator('[data-field=guarantor_2_name]')).toHaveValue('');
  await page.locator('#origination-back').click();await page.locator('.application-card').click();
  await section(page,'Guarantors');
  await expect(page.locator('[data-field=guarantor_2_name]')).toHaveValue('');
});

test('supporting documents have one page each and reuse Main LAF values',async({page},info)=>{
  const {app,writes,previews}=await boot(page);
  await page.locator('#origination-section-picker').click();
  await expect(page.locator('[data-section-index]')).toHaveCount(5);
  await expect(page.locator('[data-section-index]').filter({hasText:'Document details'})).toHaveCount(0);
  await expect(page.locator('[data-section-index]').filter({hasText:'Supporting documents'})).toHaveCount(0);
  await page.locator('[data-section-index]').filter({hasText:'Guarantor form'}).click();
  await expect(page.locator('[data-document-field=guaranteed_amount]')).toBeVisible();
  await expect(page.locator('[data-document-field=applicant_name]')).toHaveCount(0);
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue(app.applicant_summary.name);
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveAttribute('readonly','');
  await expect(page.locator('[data-input-source]')).toHaveCount(0);
  await page.locator('[data-document-field=guarantee_notes]').fill('Synthetic undertaking');
  await page.locator('[data-document-field=guaranteed_amount]').fill('25000');
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  await expect.poll(()=>previews.length).toBe(1);
  expect(previews[0]).toContain('/documents/guarantee/');
  expect(writes.at(-1).payload).toMatchObject({guarantee_notes:'Synthetic undertaking',guaranteed_amount:'25000'});
  await page.locator('#preview-close').click();
  await section(page,'Confirmation');
  await expect(page.getByRole('button',{name:'Preview document',exact:true})).toBeVisible();
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue(app.applicant_summary.name);
  await page.screenshot({path:info.outputPath('autofilled-document.png'),fullPage:true});
});

for(const dark of [false,true]) test(`header contacts dial and copy without reference clutter (${dark?'dark':'light'})`,async({page},info)=>{
  await boot(page,{dark,width:dark?390:360});
  await expect(page.locator('.editor-contacts a[href="tel:+254700000001"]')).toBeVisible();
  await page.screenshot({path:info.outputPath(`application-header-${dark?'dark':'light'}.png`),fullPage:true});
  await page.getByRole('button',{name:'Copy National ID',exact:true}).click();
  expect(await page.evaluate(()=>window.__copied)).toEqual(['00099001']);
  await expect(page.locator('.editor-identity')).not.toContainText('ORG-SYNTHETIC');
  await expect(page.getByText('Applicant contacts',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Manage documents',exact:true})).toHaveCount(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await section(page,'Guarantor form');
  await page.screenshot({path:info.outputPath(`supporting-document-${dark?'dark':'light'}.png`),fullPage:true});
});

test('reused values are read only and refresh after saving their source section',async({page})=>{
  const {app}=await boot(page);
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Keep this document note');
  await expect(page.locator('[data-input-source]')).toHaveCount(0);
  await section(page,'Applicant');
  await page.locator('[data-field=applicant_name]').fill('Synthetic updated applicant');
  await section(page,'Guarantor form');
  await expect(page.locator('[data-reused-field=applicant_name]')).toHaveValue('Synthetic updated applicant');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Keep this document note');
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Keep this document note');
});

test('failed document save prevents navigation and keeps typed values for retry',async({page},info)=>{
  const {app,retry}=await boot(page,{failure:true});
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Keep after failure');
  await page.locator('#section-next').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Synthetic save failed');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Keep after failure');
  await page.screenshot({path:info.outputPath('document-save-failed.png'),fullPage:true});
  retry();await page.locator('#section-next').click();
  await expect(page.getByRole('heading',{name:'Confirmation',exact:true})).toBeVisible();
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Keep after failure');
});

test('clearing during an earlier save cannot restore the previous guarantor',async({page})=>{
  const {app,writes}=await boot(page,{linked:true,delay:500});
  await section(page,'Guarantors');
  await page.locator('[data-field=guarantor_1_name]').fill('Synthetic first updated');
  await expect.poll(()=>writes.length).toBe(1);
  await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
  expect(app.form_payload.guarantor_1_name).toBe('Synthetic first updated');
  expect(app.form_payload.spouse_name).toBe('Synthetic spouse');
  expect(app.form_payload._person_role_bindings).not.toHaveProperty('guarantor_2');
});

test('clearing save failure never reports success and can be retried',async({page})=>{
  const {app,retry}=await boot(page,{linked:true,failure:true});
  await section(page,'Guarantors');
  await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Could not save the cleared guarantor');
  expect(app.form_payload.guarantor_2_name).toBe('Synthetic spouse');
  retry();await page.getByRole('button',{name:'Clear Guarantor 2',exact:true}).click();
  await expect.poll(()=>app.form_payload.guarantor_2_name).toBe('');
});

test('clipboard failure is visible without a false success message',async({page})=>{
  await boot(page);
  await page.evaluate(()=>navigator.clipboard.writeText=async()=>{throw new Error('Synthetic denial');});
  await page.getByRole('button',{name:'Copy National ID',exact:true}).click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Could not copy');
});

test('separate document instances share canonical values but keep their own notes',async({page})=>{
  const {app,reopen}=await boot(page);
  const second=clone(app.document_packet.documents[0]);
  second.key='second-guarantee';second.name='Second guarantee';second.field_payload={};
  app.document_packet.documents.splice(1,0,second);
  await reopen();
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guaranteed_amount]').fill('25000');
  await page.locator('[data-document-field=guarantee_notes]').fill('First guarantee');
  await section(page,'Second guarantee');
  await expect(page.locator('[data-document-field=guaranteed_amount]')).toHaveCount(0);
  await expect(page.locator('[data-reused-field=guaranteed_amount]')).toHaveValue('25000');
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('');
  await page.locator('[data-document-field=guarantee_notes]').fill('Second guarantee');
  await section(page,'Review');
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('First guarantee');
  expect(app.document_packet.documents[1].field_payload.guarantee_notes).toBe('Second guarantee');
  expect(app.form_payload.guaranteed_amount).toBe('25000');
});

test('incomplete document preview asks and sends explicit confirmation',async({page})=>{
  const {app,reopen,previewBodies}=await boot(page);
  const doc=app.document_packet.documents[0];
  doc.schema.fields.find(field=>field.key==='guarantee_notes').required=true;
  doc.missing_fields=['guarantee_notes'];
  await reopen();await section(page,'Guarantor form');
  await page.evaluate(()=>window.confirm=()=>false);
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  expect(previewBodies).toHaveLength(0);
  await page.evaluate(()=>window.confirm=()=>true);
  await page.getByRole('button',{name:'Preview document',exact:true}).click();
  await expect.poll(()=>previewBodies.length).toBe(1);
  expect(previewBodies[0].allow_incomplete).toBe(true);
});

test('document recovery reopens the correct page and saves restored fields',async({page})=>{
  const {app,writes,retry,reopen}=await boot(page,{failure:true});
  await section(page,'Guarantor form');
  await page.locator('[data-document-field=guarantee_notes]').fill('Recover this document');
  await expect.poll(()=>writes.length).toBeGreaterThan(0);
  await expect(page.locator('#origination-save-status')).toContainText('Not saved');
  await reopen();
  await expect(page.locator('[data-document-field=guarantee_notes]')).toHaveValue('Recover this document');
  retry();await page.locator('#section-next').click();
  await expect(page.getByRole('heading',{name:'Confirmation',exact:true})).toBeVisible();
  expect(app.document_packet.documents[0].field_payload.guarantee_notes).toBe('Recover this document');
});

for (const width of [320,360,390,430]) for(const dark of [false,true]) test(`compact header and aligned fields ${width} ${dark?'dark':'light'}`,async({page},info)=>{
  await boot(page,{width,dark,configure:app=>{
    app.form_schema.fields.slice(0,2).forEach((field,index)=>Object.assign(field,{
      label:index?'Short label':'Applicant contact email with a longer visible label',
      help_text:index?'':'A longer explanation that should wrap below the input, not displace its neighbour.',
      ...(index?{}:{validation:{format:'email'}}),
    }));
    const doc=app.document_packet.documents[0];
    for(const [key,type,value] of [['zero','number',0],['consent','boolean',false],['nationality','choice','ke'],['missing','text','']]) {
      app.form_payload[key]=value;
      const field={key,label:key,type,value_contract:{source:'entered',scope:'application'},options:[{code:'ke',label:'Kenya'}]};
      app.form_schema.fields.push({...field,section_key:'guarantors',input_owner:{kind:'main',section_key:'guarantors'}});
      doc.schema.fields.push(field);
    }
  }});
  const first=page.locator('[data-field=applicant_name]'),second=page.locator('[data-field=applicant_phone]');
  if(width>390) {
    expect(Math.abs((await first.boundingBox()).y-(await second.boundingBox()).y)).toBeLessThan(1);
    await first.fill('bad');await second.focus();
    await page.locator('#section-next').click();
    await expect(page.locator('[data-field-wrap=applicant_name] .miniapp-field-error')).toBeVisible();
    expect(Math.abs((await first.boundingBox()).y-(await second.boundingBox()).y)).toBeLessThan(1);
    const error=await page.locator('[data-field-wrap=applicant_name] .miniapp-field-error').boundingBox();
    expect(error.y).toBeGreaterThanOrEqual((await first.boundingBox()).y+(await first.boundingBox()).height);
    await page.screenshot({path:info.outputPath('aligned-validation.png'),fullPage:true});
    await first.fill('synthetic@example.invalid');await second.focus();
  }
  const header=await page.locator('.editor-summary').boundingBox();
  expect(header.y).toBeLessThanOrEqual(1);
  const fontEvidence=await page.evaluate(()=>({
    bodyFont:getComputedStyle(document.body).fontFamily,
    loadedFaces:[...document.fonts].map(font=>({family:font.family,status:font.status})),
    sourceStyles:[...document.styleSheets].map(sheet=>sheet.href).filter(Boolean),
  }));
  const fontPath=info.outputPath('font-and-shell-evidence.json');
  fs.writeFileSync(fontPath,JSON.stringify(fontEvidence,null,2));
  await info.attach('font-and-shell-evidence',{contentType:'application/json',path:fontPath});
  for(const id of ['origination-back','origination-restart-laf','origination-preview-early','origination-download']) {
    const button=page.locator(`#${id}`),box=await button.boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);expect(box.height).toBeGreaterThanOrEqual(44);
    await expect(button).toHaveCSS('border-top-width','0px');
    await expect(button).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
  }
  await page.screenshot({path:info.outputPath('header.png'),fullPage:true});
  await section(page,'Guarantor form');
  for(const [key,value] of [['zero','0'],['consent','No'],['nationality','Kenya']]) await expect(page.locator(`[data-reused-field=${key}]`)).toHaveValue(value);
  await expect(page.locator('[data-reused-field=missing]')).toHaveAttribute('placeholder','Not entered');
  await expect(page.locator('[data-input-source]')).toHaveCount(0);
  await page.screenshot({path:info.outputPath('supporting-fields.png'),fullPage:true});
  await page.evaluate(()=>document.documentElement.style.fontSize='200%');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('bundle confirmation opens incomplete preview but never unlocks submission after refresh',async({page})=>{
  await boot(page);
  const requests=[];
  await page.route('**/packet/preview/',route=>{
    const body=route.request().postDataJSON();requests.push(body);
    if(!body.allow_incomplete) return route.fulfill({status:400,json:{ok:false,code:'incomplete_preview_confirmation_required',error:'Some details are missing.'}});
    return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png')),
      headers:{'X-Preview-Complete':'false','X-Preview-Page-Count':'1'}});
  });
  await page.getByRole('button',{name:'Preview application',exact:true}).click();
  await expect(page.locator('#document-preview-image')).toBeVisible();
  expect(requests.map(body=>body.allow_incomplete)).toEqual([false,true]);
  await page.getByRole('button',{name:'Refresh preview',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(3);
  await page.getByRole('button',{name:'Close preview',exact:true}).click();
  await section(page,'Review');
  await expect(page.locator('.review-card').filter({hasText:'Guarantor form'})).toContainText('Preview required');
  await page.locator('#origination-submit').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Preview the filled document');
});

function identityFixture(app) {
  app.identity_copies=[{key:'borrower_id_copy',label:'Borrower ID copy',type:'document',identity_role:'borrower',identity_field:'applicant_id_number',subject_sha256:'synthetic-only'}];
}

test('cancelling an incomplete bundle closes preview without a false error or readiness',async({page})=>{
  await boot(page);
  let requests=0;
  await page.route('**/packet/preview/',route=>{requests++;return route.fulfill({status:400,json:{
    ok:false,code:'incomplete_preview_confirmation_required',error:'Some required details are missing.'}});});
  await page.evaluate(()=>window.confirm=()=>false);
  await page.getByRole('button',{name:'Preview application',exact:true}).click();
  await expect(page.locator('#document-preview-overlay')).toBeHidden();
  expect(requests).toBe(1);
  await expect(page.locator('#miniapp-shared-toast')).not.toHaveClass(/is-visible/);
  await section(page,'Review');
  await expect(page.locator('.review-card').filter({hasText:'Guarantor form'})).toContainText('Preview required');
});

test('camera captures both sides, retakes and stops tracks without losing photos on failed upload',async({page},info)=>{
  await page.addInitScript(()=>{
    window.__cameraStreams=[];
    navigator.mediaDevices.getUserMedia=async()=>{
      const canvas=document.createElement('canvas');canvas.width=480;canvas.height=300;
      const context=canvas.getContext('2d');context.fillStyle='#dceee4';context.fillRect(0,0,480,300);
      context.fillStyle='#173d2d';context.font='32px sans-serif';context.fillText('Synthetic ID photo',40,140);
      const stream=canvas.captureStream(5);window.__cameraStreams.push(stream);return stream;
    };
  });
  await boot(page,{width:390,configure:identityFixture});
  await section(page,'Product requirements');
  await page.locator('[data-id-capture]').click();
  for(const side of ['front','back','front']) {
    await page.locator(`[data-id-camera=${side}]`).click();
    await expect(page.locator('#evidence-camera-capture')).toBeEnabled();
    await page.locator('#evidence-camera-capture').click();
    await expect(page.locator(`[data-id-image=${side}]`)).toBeVisible();
    await expect(page.locator('#origination-sheet-overlay')).toBeVisible();
  }
  expect(await page.evaluate(()=>__cameraStreams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended')))).toBe(true);
  await page.screenshot({path:info.outputPath('captured-front-back.png'),fullPage:true});
  const uploads=[];
  await page.route('**/requirements/borrower_id_copy/evidence/',route=>{
    uploads.push(route.request().postDataBuffer().toString());
    return route.fulfill({status:502,json:{ok:false,error:'Synthetic upload failed.'}});
  });
  await page.locator('[data-id-upload]').click();
  await expect(page.locator('[data-id-status]')).toContainText('Synthetic upload failed');
  await expect(page.locator('[data-id-image=front]')).toBeVisible();
  await expect(page.locator('[data-id-image=back]')).toBeVisible();
  await page.locator('[data-id-upload]').click();
  await expect.poll(()=>uploads.length).toBe(2);
  expect(uploads[0]).toContain('name="front"');expect(uploads[0]).toContain('name="back"');
  const requestKey=body=>body.match(/name="request_id"\r\n\r\n([^\r]+)/)?.[1];
  expect(requestKey(uploads[1])).toBe(requestKey(uploads[0]));
});

test('camera denied and unavailable leave file fallback and existing ID photos usable',async({page})=>{
  await page.addInitScript(()=>navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Synthetic denial','NotAllowedError');});
  await boot(page,{configure:identityFixture});await section(page,'Product requirements');
  await page.locator('[data-id-capture]').click();
  await page.locator('[data-id-camera=front]').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Camera access was unavailable');
  await expect(page.locator('#origination-sheet-overlay')).toBeVisible();
  await page.locator('[data-id-side=front]').setInputFiles({name:'synthetic-front.png',mimeType:'image/png',buffer:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png'))});
  await page.evaluate(()=>navigator.mediaDevices.getUserMedia=undefined);
  await page.locator('[data-id-camera=back]').click();
  await expect(page.locator('#miniapp-shared-toast')).toContainText('Use Choose file instead');
  await expect(page.locator('[data-id-image=front]')).toBeVisible();
});

test('queue identity slots remain aligned with absent data and show the readable reference',async({page},info)=>{
  await boot(page,{configure:app=>{app.applicant_summary={name:'Synthetic applicant',phone:'',national_id:''};}});
  await page.locator('#origination-back').click();
  await expect(page.locator('.application-reference')).toHaveText('ORG-12');
  await expect(page.locator('.application-card-identifiers>span')).toHaveCount(2);
  await expect(page.locator('.application-card-identifiers')).toContainText('Not provided');
  await expect(page.locator('.application-card-identifiers a')).toHaveCount(0);
  await expect(page.locator('.application-officer')).toHaveCount(0);
  const labels=await page.locator('.application-card-identifiers>span>small').evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().y));
  expect(Math.abs(labels[0]-labels[1])).toBeLessThan(1);
  const separated=await page.locator('.application-card-identifiers>span').evaluateAll(nodes=>nodes.every(node=>
    node.querySelector('small').getBoundingClientRect().right+4<=node.querySelector('span').getBoundingClientRect().left));
  expect(separated).toBe(true);
  await page.screenshot({path:info.outputPath('missing-card-values.png'),fullPage:true});
});

test('phone-check outcome stays behind its compact control instead of expanding the header',async({page},info)=>{
  await boot(page,{configure:app=>{
    app.phone_id_checks={allowed:true,enabled:true,environment:'sandbox',revision:1,targets:[{
      target:'primary',field_key:'applicant_phone',id_field_key:'applicant_id_number',status:'not_matched',
      checked_at:'2026-10-21T10:00:00Z',freshness:'current',can_check:true,
    }]};
  }});
  const target=page.locator('[data-phone-id-target=primary]');
  await expect(target.locator('details')).not.toHaveAttribute('open','');
  await expect(target.locator('.phone-check-popover')).toBeHidden();
  const height=(await page.locator('.editor-summary').boundingBox()).height;
  await target.getByLabel('Phone registration details').click();
  await expect(target.locator('.phone-check-popover')).toContainText('Registration does not match');
  expect((await page.locator('.editor-summary').boundingBox()).height).toBe(height);
  const popover=await target.locator('.phone-check-popover').boundingBox();
  expect(popover.x).toBeGreaterThanOrEqual(0);
  expect(popover.x+popover.width).toBeLessThanOrEqual(360);
  await page.screenshot({path:info.outputPath('phone-check-details.png'),fullPage:true});
});

test('cancelled pending camera permission releases the eventual stream',async({page})=>{
  await page.addInitScript(()=>{
    window.__cameraStopped=0;
    navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{
      window.__releaseCamera=()=>resolve({getTracks:()=>[{stop:()=>window.__cameraStopped++}]});
    });
  });
  await boot(page,{configure:identityFixture});await section(page,'Product requirements');
  await page.locator('[data-id-capture]').click();await page.locator('[data-id-camera=front]').click();
  await page.getByRole('button',{name:'Close camera',exact:true}).click();
  await page.evaluate(()=>__releaseCamera());
  await expect.poll(()=>page.evaluate(()=>__cameraStopped)).toBe(1);
  await expect(page.locator('.camera-capture-dialog')).toHaveCount(0);
  await expect(page.locator('#origination-sheet-overlay')).toBeVisible();
});
