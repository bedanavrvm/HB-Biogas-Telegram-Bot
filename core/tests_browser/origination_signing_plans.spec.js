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

function application(approved = false, choices = null) {
  const roles = ['borrower', 'borrower', 'officer', 'branch_manager'];
  const people = roles.map((role,index) => ({id:`00000000-0000-4000-8000-00000000000${index+1}`,
    role,name:index===1 ? 'Synthetic joint applicant with a longer readable name' : `Synthetic person ${index+1}`,
    staff:index>1,complete:approved || index===2,can_sign:!approved && index===3}));
  return {id:applicationId,reference_number:'ORG-SYNTHETIC-PLAN',product_name:'Synthetic Loan',
    status:approved ? 'approved' : 'partially_signed',officer_id:1,revision:4,branch:'Synthetic branch',
    applicant_summary:{name:'Synthetic Applicant'}, form_schema:{fields:[],sections:[{key:'applicant',label:'Applicant'}]},
    form_payload:{},product_terms:{},requirement_evidence:[],
    download_choices:choices || [{document_key:'',label:'All documents',description:'Combined PDF',available:true},
      {document_key:'primary',label:'Main LAF',description:approved?'Signed PDF':'PDF',available:true}],
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

async function mount(page, {approved=false,dark=false,download='',choices=null,unsigned=false}={}) {
  const errors=[];
  const queries=[];
  const downloads=[];
  page.on('pageerror', error=>errors.push(error.message));
  let payload;
  let unsignedStatus = 'draft';
  const currentApplication = () => {
    const value = application(approved, choices);
    if (unsigned) Object.assign(value, {status:unsignedStatus, status_label:unsignedStatus==='completed'?'Completed':'Draft',
      status_text:unsignedStatus==='completed'?'Completed without e-signing':'Draft',
      completion_without_signing:true,signing_workspace:null,signing_package:null,short_acknowledgement:true,
      officer_id:2,form_payload:{applicant_full_name:'Synthetic Applicant'},
      form_schema:{sections:[{key:'applicant',label:'Applicant'}],fields:[{key:'applicant_full_name',label:'Applicant name',type:'text',required:true}]}});
    return value;
  };
  await page.route('**/*', async route=>{
    const url=new URL(route.request().url());
    if(url.hostname!=='127.0.0.1') return route.abort();
    if(url.pathname==='/origination/') return route.fulfill({contentType:'text/html',body:template});
    if(url.pathname.endsWith('/products/')) return route.fulfill({json:{ok:true,products:[],branches:[],
      capabilities:{user_id:2,can_create:unsigned,can_review:false,can_start_signing:false,can_staff_sign:true,
        staff_signer_roles:['branch_manager']}}});
    if(url.pathname.endsWith('/applications/')) {
      queries.push(url.search);
      return route.fulfill({json:{ok:true,applications:[currentApplication()],
        status_group_options:[{value:'draft',label:'Draft'},{value:'changes',label:'Needs changes'},
          {value:'progress',label:'In progress'},{value:'completed',label:'Completed'},{value:'closed',label:'Closed'}],
        capabilities:{user_id:2,can_staff_sign:true,staff_signer_roles:['branch_manager']},pagination:{pages:1,page:1,total:1}}});
    }
    if(url.pathname.endsWith('/staff-signature/')) {
      payload=route.request().postDataJSON();
      return route.fulfill({json:{ok:true,application:application(true)}});
    }
    if(unsigned && url.pathname.endsWith('/submit/')) {
      unsignedStatus = 'completed';
      return route.fulfill({json:{ok:true,application:currentApplication()}});
    }
    if(url.pathname.endsWith('/signature-preview/')) {
      const values=route.request().postDataJSON();
      const image=execFileSync(path.join(root,'.venv','Scripts','python.exe'),['-c',
        'import json,sys; from origination.services.signature_appearance import preview_capture; print(json.dumps(preview_capture(sys.argv[1],sys.argv[2])))',values.name,values.font],{cwd:root,encoding:'utf8'});
      return route.fulfill({json:{ok:true,...JSON.parse(image)}});
    }
    if(url.pathname.endsWith('/download/')) {
      payload=route.request().postDataJSON();
      downloads.push(payload);
      return route.fulfill({json:{ok:true,download_url:'http://127.0.0.1/copy.pdf',
        filename:`ORG-SYNTHETIC-PLAN-${approved?'SIGNED':'UNSIGNED'}${payload.document_key?'-'+payload.document_key:''}.pdf`,copy_type:approved?'signed':'unsigned'}});
    }
    if(url.pathname.includes(`/applications/${applicationId}/`)) return route.fulfill({json:{ok:true,application:currentApplication()}});
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
  await expect(page.locator(unsigned?'.wizard-card':'.signing-workspace')).toBeVisible();
  return {errors,payload:()=>payload,queries,downloads};
}

for(const width of [320,390,1280]) test(`unsigned completion and download ${width}`, async({page}, info)=>{
  await page.setViewportSize({width,height:844});
  const audit = await mount(page,{unsigned:true,download:'native'});
  // Enter the review section without pretending a download is a review.
  for(let count=0;count<10 && await page.locator('#section-next').isEnabled();count++) {
    await page.locator('#section-next').click();
  }
  await expect(page.locator('#origination-submit')).toHaveText('Complete application');
  await expect(page.locator('#origination-confirm-signing')).toHaveCount(0);
  await page.screenshot({path:info.outputPath(`unsigned-review-${width}.png`),fullPage:true});
  await page.route('**/preview/', route=>route.fulfill({contentType:'image/svg+xml',
    body:'<svg xmlns="http://www.w3.org/2000/svg" width="595" height="842"><rect width="100%" height="100%" fill="white"/><text x="20" y="40">Synthetic unsigned document</text></svg>',
    headers:{'X-Preview-Page-Count':'1'}}));
  await page.locator('#origination-preview').click();
  await expect(page.locator('#preview-page')).toHaveText('Page 1 of 1');
  await page.locator('#preview-close').click();
  await page.locator('#origination-submit').click();
  await expect(page.getByRole('heading',{name:'Application completed',exact:true})).toBeVisible();
  await expect(page.getByText('This does not approve the loan.',{exact:false})).toBeVisible();
  await expect(page.getByRole('button',{name:'Submit for signing',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Download application',exact:true}).last().click();
  await expect(page.getByRole('button',{name:/All documents/})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`unsigned-completed-${width}.png`),fullPage:true});
  expect(audit.errors).toEqual([]);
});

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
  const toolbar = await page.locator('.preview-toolbar').boundingBox();
  const previous = await page.locator('#preview-previous').boundingBox();
  const next = await page.locator('#preview-next').boundingBox();
  expect(previous.x-toolbar.x).toBeLessThanOrEqual(8);
  expect(toolbar.x+toolbar.width-next.x-next.width).toBeLessThanOrEqual(8);
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
  await expect(page.getByRole('heading',{name:'Download',exact:true})).toBeVisible();
  expect(audit.downloads).toHaveLength(0);
  await page.getByRole('button',{name:'Download All documents',exact:true}).click();
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
    await expect(page.locator('[data-approval-preview] svg')).toBeVisible();
    await expect(page.locator('.participant-row').first()).toHaveCSS('border-left-width','0px');
    await page.locator('.workspace-details').first().locator(':scope > summary').focus();
    await expect(page.locator('.workspace-details').first()).toHaveCSS('outline-style','none');
    await page.locator('.signing-workspace h3').click();
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

test('incomplete application download asks before native handoff',async({page})=>{
  await mount(page,{download:'native'});
  let count=0;
  await page.route('**/applications/*/download/', route=>{
    const body=route.request().postDataJSON();count++;
    return route.fulfill({json:body.allow_incomplete ? {ok:true,download_url:'http://127.0.0.1/copy.pdf',filename:'Synthetic Applicant Loan KES 100000 14-10-2026 12-30-00.pdf'}
      : {ok:false,code:'incomplete_copy_confirmation_required',error:'Some required details are missing. Download this copy anyway?'}});
  });
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Download application',exact:true}).click();
  await page.getByRole('button',{name:'Download All documents',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>window.__downloads.length)).toBe(1);
  expect(count).toBe(2);
  expect(await page.evaluate(()=>window.__downloads[0].file_name)).toContain('Synthetic Applicant Loan KES 100000');
});

for (const width of [320,390,1280]) for (const dark of [false,true]) {
  test(`document download chooser is compact at ${width}px ${dark?'dark':'light'}`,async({page},info)=>{
    await page.setViewportSize({width,height:844});
    const choices=[{document_key:'',label:'All documents',description:'Combined PDF',available:true},
      {document_key:'primary',label:'Main LAF',description:'Signed PDF',available:true},
      {document_key:'guarantee',label:'Guarantee and undertaking for a joint applicant with a longer document name',description:'Signed PDF',available:true},
      {document_key:'home_visit',label:'Home visit',description:'Signed PDF',available:true}];
    const audit=await mount(page,{approved:true,dark,download:'native',choices});
    await page.getByRole('button',{name:'Download application',exact:true}).click();
    const sheet=page.locator('#origination-sheet');
    await expect(sheet.getByRole('button',{name:/^Download /})).toHaveCount(4);
    await expect(sheet.locator('button')).toHaveCount(5); // Four choices and the existing Close icon.
    expect(audit.downloads).toHaveLength(0);
    const geometry=await sheet.evaluate(node=>{
      const title=node.querySelector('h2').getBoundingClientRect();
      const close=node.querySelector('#origination-sheet-close').getBoundingClientRect();
      const icons=[...node.querySelectorAll('.document-download-choice svg')].map(icon=>icon.getBoundingClientRect().width);
      return {height:node.getBoundingClientRect().height,overflow:document.documentElement.scrollWidth>innerWidth,
        aligned:close.top<title.bottom && close.bottom>title.top,icons};
    });
    expect(geometry.height).toBeLessThan(430);
    expect(geometry.overflow).toBe(false);
    expect(geometry.aligned).toBe(true);
    expect(geometry.icons.every(size=>size<=20)).toBe(true);
    await page.screenshot({path:info.outputPath(`download-chooser-${width}-${dark?'dark':'light'}.png`)});
    await page.getByRole('button',{name:'Download Main LAF',exact:true}).click();
    await expect(page.locator('#origination-toast')).toContainText('Download requested: ORG-SYNTHETIC-PLAN-SIGNED-primary.pdf');
    expect(audit.downloads[0].document_key).toBe('primary');
    expect(audit.errors).toEqual([]);
  });
}

test('individual supporting download and incomplete confirmation keep the selected document',async({page})=>{
  const choices=[{document_key:'',label:'All documents',available:true},
    {document_key:'guarantee',label:'Guarantee',available:true}];
  await mount(page,{download:'native',choices});
  const requests=[];
  await page.route('**/applications/*/download/',route=>{
    const body=route.request().postDataJSON();requests.push(body);
    return route.fulfill({json:body.allow_incomplete
      ? {ok:true,download_url:'http://127.0.0.1/copy.pdf',filename:'Synthetic Guarantee.pdf'}
      : {ok:false,code:'incomplete_copy_confirmation_required',error:'Some required details are missing. Download this copy anyway?'}});
  });
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Download application',exact:true}).click();
  await page.getByRole('button',{name:'Download Guarantee',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(2);
  expect(requests.map(body=>body.document_key)).toEqual(['guarantee','guarantee']);
  await expect.poll(()=>page.evaluate(()=>window.__downloads.length)).toBe(1);
  expect(await page.evaluate(()=>window.__downloads[0].file_name)).toBe('Synthetic Guarantee.pdf');
});

test('blank suggested filename is never handed to Telegram',async({page})=>{
  await mount(page,{download:'native'});
  await page.route('**/applications/*/download/',route=>route.fulfill({json:{ok:true,
    download_url:'https://miniapp.test/copy.pdf',filename:'   \t  '}}));
  await page.getByRole('button',{name:'Download application',exact:true}).click();
  await page.getByRole('button',{name:'Download All documents',exact:true}).click();
  await expect(page.locator('#origination-toast')).toContainText('download is unavailable');
  expect(await page.evaluate(()=>window.__downloads)).toEqual([]);
});

test('closing chooser or cancelling incomplete confirmation performs no download',async({page})=>{
  const audit=await mount(page,{download:'native'});
  const opener=page.getByRole('button',{name:'Download application',exact:true});
  await opener.click();
  await page.keyboard.press('Escape');
  await expect(page.locator('#origination-sheet-overlay')).toBeHidden();
  await expect(opener).toBeFocused();
  expect(audit.downloads).toHaveLength(0);
  let requests=0;
  await page.route('**/applications/*/download/',route=>{
    requests++;
    return route.fulfill({json:{ok:false,code:'incomplete_copy_confirmation_required',error:'Download incomplete copy?'}});
  });
  page.once('dialog',dialog=>dialog.dismiss());
  await opener.click();
  await page.getByRole('button',{name:'Download Main LAF',exact:true}).click();
  await expect(opener).toBeEnabled();
  expect(requests).toBe(1);
  expect(await page.evaluate(()=>window.__downloads.length)).toBe(0);
});

test('download failure is visible and repeated taps prepare only one copy',async({page})=>{
  await mount(page,{download:'native'});
  let requests=0, release;
  await page.route('**/applications/*/download/',async route=>{
    requests++;
    await new Promise(resolve=>{release=resolve;});
    return route.fulfill({status:503,json:{ok:false,error:'The document could not be retrieved. Try again.'}});
  });
  const opener=page.getByRole('button',{name:'Download application',exact:true});
  await opener.click();
  await page.getByRole('button',{name:'Download Main LAF',exact:true}).evaluate(button=>{button.click();button.click();});
  await expect.poll(()=>requests).toBe(1);
  await expect(opener).toBeDisabled();
  await expect(page.locator('#origination-toast')).toContainText('Preparing PDF');
  release();
  await expect(page.locator('#origination-toast')).toContainText('The document could not be retrieved. Try again.');
  await expect(opener).toBeEnabled();
  expect(await page.evaluate(()=>window.__downloads.length)).toBe(0);
  await opener.click();
  await expect(page.getByRole('button',{name:'Download Main LAF',exact:true})).toBeEnabled();
});

test('many documents scroll inside chooser and historical unavailable copies explain why',async({page})=>{
  await page.setViewportSize({width:320,height:568});
  const choices=[{document_key:'',label:'All documents',description:'Combined PDF',available:true},
    ...Array.from({length:14},(_,index)=>({document_key:`support_${index}`,label:`Supporting document ${index+1}`,available:true})),
    {document_key:'primary',label:'Individual documents',available:false,reason:'Separate copies are unavailable for this application. Download all documents instead.'}];
  const audit=await mount(page,{approved:true,download:'native',choices});
  await page.getByRole('button',{name:'Download application',exact:true}).click();
  expect(await page.locator('#origination-sheet-body').evaluate(node=>node.scrollHeight>node.clientHeight)).toBe(true);
  const unavailable=page.getByRole('button',{name:'Download Individual documents',exact:true});
  await unavailable.scrollIntoViewIfNeeded();
  await expect(unavailable).toBeDisabled();
  await expect(unavailable).toContainText('Download all documents instead.');
  expect(audit.downloads).toHaveLength(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
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

for(const width of [320,390,768])test(`recipient toolbar separates navigation from zoom ${width}`,async({page},info)=>{
  await page.setViewportSize({width,height:844});
  await mountRecipient(page);
  await page.addStyleTag({path:asset('origination','origination_compact.css')});
  const bar=await page.locator('.page-controls').boundingBox();
  const previous=await page.locator('#page-prev').boundingBox(), next=await page.locator('#page-next').boundingBox();
  expect(previous.x-bar.x).toBeLessThan(1);
  expect(bar.x+bar.width-next.x-next.width).toBeLessThan(1);
  expect(previous.y).toBe(next.y);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`recipient-toolbar-${width}.png`),fullPage:true});
});

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
