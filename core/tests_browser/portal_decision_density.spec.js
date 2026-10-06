'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/miniapp/portal_farmer_sheet.js'), 'utf8');
const farmup = fs.readFileSync(path.join(root, 'static/miniapp/portal_farmup.js'), 'utf8');
const portal = fs.readFileSync(path.join(root, 'static/miniapp/portal.js'), 'utf8');
const template = fs.readFileSync(path.join(root, 'templates/portal/portal.html'), 'utf8');
const fn = (text, name) => {
  const match = text.match(new RegExp('  (?:async )?function ' + name + '\\([^]*?\\n  \\}'));
  if (!match) throw new Error('Missing production function: ' + name);
  return match[0];
};
const reasons = {
  rejected: ['Affordability','Poor credit history','Multi-funded','Insufficient livestock','Missing Consent','Policy not met','Other reason'].map((label,i)=>({value:`r0${i+1}`,label})),
  deferred: ['Customer deciding','KYC pending','Customer unavailable','Site not prepared','Not enough livestock','Deposit pending','Family/spouse deciding','Health/personal circumstances','Land/ownership issue pending','Reassessment pending','Existing Loan Not Cleared','Other reason'].map((label,i)=>({value:`d${String(i+1).padStart(2,'0')}`,label})),
};

for(const prefix of ['jbl','final']) {
  test(`${prefix} reasons use the selected outcome and restore independently of JSON key order`,async({page})=>{
    await mountPortalShell(page,'<main id="content"><div id="form"></div></main>');
    await page.evaluate(({code,prefix,reasons})=>{
      const deps={escapeHtml:value=>String(value??'')},state=()=>({metaPipelineReasons:reasons});
      const el=id=>document.getElementById(id);
      const jblLocationRefresh=null,syncJblDateControls=()=>{},setGpsUnavailableReasonVisible=()=>{};
      eval(code+`
        el('form').innerHTML = '<select id="'+(prefix==='jbl'?'jbl-status':'final-decision')+'"><option>Approved</option><option>Rejected</option><option>Deferred / On Hold</option></select><textarea id="'+prefix+'-comment"></textarea>'+decisionReasonMarkup(prefix,false);
        wireDecisionReasonFields(prefix);
        window.restoreDraft=applyJblVisitDraft;
      `);
    },{prefix,reasons,code:['decisionReasonMarkup','decisionNeedsReason','wireDecisionReasonFields','applyJblVisitDraft'].map(name=>fn(source,name)).join('\n')});
    if(prefix==='jbl') {
      await page.evaluate(()=>window.restoreDraft({values:{'jbl-comment':'Synthetic explanation','jbl-reason-code':'d12','jbl-status':'Deferred / On Hold'}}));
    } else {
      await page.locator('#final-decision').selectOption('Deferred / On Hold');
      await page.locator('#final-reason-code').selectOption('d12');
    }
    await expect(page.locator(`#${prefix}-reason-code`)).toHaveValue('d12');
    await expect(page.locator(`#${prefix}-reason-code option`)).toHaveText(['Select a reason',...reasons.deferred.map(r=>r.label)]);
    await expect(page.locator(`#${prefix}-comment`)).toHaveAttribute('required','');
  });
}

for (const width of [320,390,430,1024]) {
  test(`decision controls and document actions fit ${width}px`, async ({page},info)=>{
    await page.setViewportSize({width,height:800});
    await mountPortalShell(page, '<main id="content"><section class="page active"><div id="form"></div><div id="documents" class="case360-documents"></div></section></main>');
    await page.evaluate(({code,reasons})=>{
      const deps = {escapeHtml:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),openPortalLink:url=>window.opened=url};
      const state = ()=>({metaPipelineReasons:reasons}),voiceWidget=()=>'';
      const el = id=>document.getElementById(id);
      const openClientMediaPreview = item=>window.previewed=item.name;
      const openClientMediaExternally = ()=>{};
      eval(code + `
        el('form').innerHTML = '<h2>Credit decision</h2><select id="credit-decision"><option>Approved</option><option>Rejected</option><option>Deferred / On Hold</option></select>' + decisionReasonMarkup('credit',true);
        wireDecisionReasonFields('credit');
        renderCaseDocumentList([{name:'Synthetic signed requisition document with a long name.xlsx',mime_type:'application/pdf',preview_url:'/synthetic/preview',open_url:'/synthetic/open'}],el('documents'));
      `);
    },{reasons,code:['decisionReasonMarkup','decisionNeedsReason','wireDecisionReasonFields','caseDocumentKind','renderCaseDocumentList'].map(name=>fn(source,name)).join('\n')});
    await expect(page.locator('#credit-reason-row')).toBeHidden();
    await page.locator('#credit-decision').selectOption('Rejected');
    await expect(page.locator('#credit-reason-code option')).toHaveText(['Select a reason',...reasons.rejected.map(r=>r.label)]);
    await page.locator('#credit-reason-code').selectOption('r01');
    await expect(page.locator('#credit-comment-required')).toBeHidden();
    await expect(page.locator('#credit-decision-comment')).not.toHaveAttribute('required');
    await page.locator('#credit-reason-code').selectOption('r07');
    await expect(page.locator('#credit-comment-required')).toBeVisible();
    await expect(page.locator('#credit-decision-comment')).toHaveAttribute('required','');
    await page.locator('#credit-decision').selectOption('Deferred / On Hold');
    await expect(page.locator('#credit-reason-code option')).toHaveText(['Select a reason',...reasons.deferred.map(r=>r.label)]);
    await page.locator('#credit-reason-code').selectOption('d11');
    await expect(page.locator('#credit-comment-required')).toBeHidden();
    await expect(page.getByRole('button',{name:'Preview document'}).locator('svg')).toBeVisible();
    const labelBox = await page.locator('#documents strong').boundingBox();
    const actionBox = await page.getByRole('button',{name:'Preview document'}).boundingBox();
    expect(actionBox.x).toBeGreaterThan(labelBox.x + labelBox.width - 1);
    await page.getByRole('button',{name:'Preview document'}).click();
    expect(await page.evaluate(()=>window.previewed)).toContain('Synthetic');
    await page.getByRole('button',{name:'Open document externally'}).click();
    expect(await page.evaluate(()=>window.opened)).toBe('/synthetic/open');
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:info.outputPath('decision-documents.png'),fullPage:true});
  });
}

for(const width of [320,390]) {
  test(`actual JBL visit form has consistent required markers at ${width}px`,async({page},info)=>{
    await page.setViewportSize({width,height:850});
    await mountPortalShell(page,'<main id="content"><section class="page active jbl-visit-sheet"><div id="form"></div></section></main>');
    await page.evaluate(({code,reasons})=>{
      const deps={escapeHtml:value=>String(value??'')},hasCapability=()=>false,voiceWidget=()=>'';
      const state=()=>({businessDate:'2026-10-05',metaStatuses:['Approved','Rejected by JBL','Deferred / On Hold'],metaCounties:['Training county'],metaPipelineReasons:reasons});
      const el=id=>document.getElementById(id);
      eval(code+`el('form').innerHTML=buildJblForm({is_new_jbl_lead:true});wireDecisionReasonFields('jbl');`);
    },{reasons,code:['displayDateFromIso','calendarIcon','decisionReasonMarkup','decisionNeedsReason','wireDecisionReasonFields','buildJblForm'].map(name=>fn(source,name)).join('\n')});
    await expect(page.locator('#form')).not.toContainText('Maisha');
    await expect(page.locator('#jbl-date-help')).toHaveCount(0);
    for(const field of ['customer_name','national_id','primary_phone','visit_date','visit_status','county','sub_county','village']) {
      await expect(page.locator(`[data-jbl-field="${field}"] .required-marker`)).toHaveCSS('color','rgb(220, 38, 38)');
    }
    await page.locator('#jbl-status').selectOption('Rejected by JBL');
    await expect(page.locator('#jbl-reason-row')).toBeVisible();
    await expect(page.locator('#jbl-reason-code option')).toHaveText(['Select a reason',...reasons.rejected.map(r=>r.label)]);
    const county=await page.locator('[data-jbl-field="county"]').boundingBox();
    for(const id of ['jbl-officer','jbl-new-lead-hb-sales-person','jbl-village']) {
      const row=await page.locator('#'+id).locator('..').boundingBox();
      expect(row.width).toBeGreaterThan(county.width*1.8);
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:info.outputPath('jbl-visit.png'),fullPage:true});
  });
}

test('FarmUp source rows page independently and escape source contents',async({page})=>{
  await mountPortalShell(page,'<main id="content"><div id="farmup-source-content"></div></main>');
  await page.evaluate(code=>{
    const active={id:'synthetic-batch'},tg=null;
    const node=id=>document.getElementById(id);
    const escapeHtml=value=>String(value).replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const api={apiFetch:async url=>{window.sourceCalls=(window.sourceCalls||[]).concat(url);return {ok:true,data:{ok:true,source_table:{headers:['Name','Source note'],rows:[['Synthetic lead','<script>not executable</script>']]},pagination:{page:url.endsWith('=2')?2:1,pages:2}}};}};
    eval(code+';window.loadSourceRows=loadSourceRows;');
    return window.loadSourceRows();
  },fn(farmup,'loadSourceRows'));
  await expect(page.locator('thead th')).toHaveText(['Name','Source note']);
  await expect(page.locator('tbody')).toContainText('<script>not executable</script>');
  await expect(page.locator('tbody script')).toHaveCount(0);
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page.locator('.farmup-source-pages span')).toHaveText('2 / 2');
  await expect(page.getByRole('button',{name:'Next',exact:true})).toBeDisabled();
  expect(await page.evaluate(()=>window.sourceCalls)).toEqual(['/farmup/synthetic-batch/?source_page=1','/farmup/synthetic-batch/?source_page=2']);
});

for(const width of [320,390,1024]) for(const dark of [false,true]) {
  test(`settings and archive alignment ${width}px ${dark?'dark':'light'}`,async({page},info)=>{
    await page.setViewportSize({width,height:850});
    const blocks = ['portal-tat-target-settings','requisition-sequence-panel'].map(id=>{
      const start=template.indexOf(`<details id="${id}"`);
      if(start<0) throw new Error('Missing real settings panel '+id);
      return template.slice(start,template.indexOf('</details>',start)+10).replace(/ hidden/g,'');
    }).join('');
    await mountPortalShell(page,`<main id="content"><section class="page active"><h2>Settings</h2>${blocks}<h2>Orders</h2><div id="batches"></div><h2>Documents</h2><div id="history-list"></div></section></main>`);
    await page.evaluate(dark=>{
      window.Telegram={WebApp:{colorScheme:dark?'dark':'light',themeParams:dark
        ? {bg_color:'#17171e',secondary_bg_color:'#20202c',text_color:'#ffffff',hint_color:'#a8a8b3',button_color:'#63a7eb',button_text_color:'#10131a',link_color:'#63a7eb'}
        : {bg_color:'#f4f7f6',secondary_bg_color:'#ffffff',text_color:'#14201d',hint_color:'#66736f',button_color:'#2481cc',button_text_color:'#ffffff',link_color:'#2481cc'}}};
      // Telegram's SDK supplies these CSS variables; the offline shell omits it.
      for(const [key,value] of Object.entries(window.Telegram.WebApp.themeParams)) {
        document.documentElement.style.setProperty('--tg-theme-'+key.replaceAll('_','-'),value);
      }
    },dark);
    await page.addScriptTag({path:path.join(root,'static/miniapp/utils.js')});
    expect(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--tg-theme-bg-color').trim())).toBe(dark?'#17171e':'#f4f7f6');
    await page.evaluate(code=>{
      const el=id=>document.getElementById(id),escapeHtml=value=>String(value??'');
      const fmtDate=value=>value,fmtDateTime=()=> '05-10-2026 15:00';
      const hasCapability=()=>false;
      const physicalSignoffMarkup=()=>'',priorPhysicalSignoffsMarkup=()=>'';
      eval(code+`
        renderBatchesList(el('batches'),[{order_number:12,farmer_count:9,invoiced_count:9,has_requisition_file:true,drive_url:'/synthetic/drive',requisition_date:'05-10-2026',farmers:Array.from({length:9},()=>({customer_name:'Synthetic customer with a long display name',county:'Training county',invoiced:true})),amount_summary:{invoice_amount:'90000'}}],{});
        renderDocumentHistory([{id:'synthetic',order_number:12,row_count:9,version:1,fulfillment_partner:'HB',download_url:'/synthetic/workbook',generated_by:'Training officer'}],'orders');
      `);
      window.lucide.createIcons();
    },['renderBatchesList','renderDocumentHistory'].map(name=>fn(portal,name)).join('\n'));
    await expect(page.locator('#portal-tat-target-settings')).not.toHaveAttribute('open');
    await expect(page.locator('#requisition-sequence-panel')).not.toHaveAttribute('open');
    await expect(page.locator('.portal-batch-extras')).not.toHaveAttribute('open');
    const archiveTitle=await page.locator('#batches .fc-name').boundingBox();
    const archiveAction=await page.getByRole('button',{name:'View order',exact:true}).boundingBox();
    expect(archiveAction.x).toBeGreaterThan(archiveTitle.x);
    expect(Math.abs(archiveAction.y-archiveTitle.y)).toBeLessThan(12);
    await page.locator('#portal-tat-target-settings>summary').click();
    await expect(page.locator('#portal-tat-target-settings')).toHaveAttribute('open','');
    await page.locator('#portal-tat-target-settings>summary').click();
    const title=await page.locator('.history-document-title').boundingBox();
    const action=await page.getByRole('button',{name:'Preview workbook',exact:true}).boundingBox();
    expect(action.x).toBeGreaterThan(title.x);
    expect(Math.abs(action.y-title.y)).toBeLessThan(12);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({path:info.outputPath('settings-archive.png'),fullPage:true});
  });
}
