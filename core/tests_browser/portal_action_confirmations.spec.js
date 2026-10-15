'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const portal = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');

for (const width of [320, 390, 430, 1280]) {
  test(`compact confirmation has no input and fits at ${width}px`, async ({page}, info) => {
    await page.setViewportSize({width, height:844});
    await mountPortalShell(page, '<button id="trigger">Remove case</button><div id="sheet-overlay" class="sheet-overlay open" role="dialog"><div class="sheet-panel"><button id="sheet-close">Close</button></div></div>');
    await page.evaluate(() => document.body.classList.add('portal-app', 'workflow-standard'));
    await page.addScriptTag({path:asset('portal_dialogs.js')});
    await page.evaluate(() => {
      window.answers = [];
      document.getElementById('trigger').onclick = async () => answers.push(await PortalDialogs.confirmAction(
        'Remove case?', 'Remove this case from the unsigned payment? It can be added to another payment. This payment will need review again.', 'Remove case'));
    });
    // The fixture's parent panel models a confirmation on top of a real sheet.
    await page.evaluate(() => document.getElementById('trigger').click());
    const dialog = page.locator('.invoice-action-confirm');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('input,textarea,select')).toHaveCount(0);
    await expect(dialog.getByRole('button')).toHaveCount(2);
    await expect(page.locator('[data-confirm-cancel]')).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(page.locator('[data-confirm-yes]')).toBeFocused();
    for (const dark of [false,true]) {
      await page.evaluate(dark => {
        document.documentElement.dataset.miniappColorScheme = dark ? 'dark' : 'light';
        for (const [key,value] of Object.entries(dark ? {bg:'#17171e','secondary-bg':'#20202c',text:'#ffffff',hint:'#a8a8b3'} : {bg:'#f5f7f8','secondary-bg':'#ffffff',text:'#17212b',hint:'#6d7a86'})) document.documentElement.style.setProperty('--tg-theme-'+key+'-color', value);
      }, dark);
      const rect = await dialog.boundingBox();
      expect(rect.x).toBeGreaterThanOrEqual(12);
      expect(rect.x + rect.width).toBeLessThanOrEqual(width - 12);
      expect(rect.height).toBeLessThan(300);
      await page.screenshot({path:info.outputPath(`confirmation-${width}-${dark?'dark':'light'}.png`), animations:'disabled'});
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(page.locator('#sheet-overlay')).toHaveClass(/open/);
    expect(await page.evaluate(() => window.answers)).toEqual([false]);
    expect(await page.locator('#sheet-overlay').evaluate(node => node.inert)).toBe(false);
  });
}

test('payment case removal cancels safely and submits without asking for a reason', async ({page}) => {
  const start = portal.indexOf('    <section id="payments-detail"');
  const markup = portal.slice(start, portal.indexOf('  <dialog id="payment-receipt-dialog"', start));
  await mountPortalShell(page, '<div id="portal-screen" data-screen="payments" data-payment-batch-id="synthetic-batch">' + markup + '</div>');
  for (const name of ['portal_helpers.js','portal_dialogs.js','portal_payments.js']) await page.addScriptTag({path:asset(name)});
  await page.evaluate(async () => {
    window.changes = [];
    window.batch = {id:'synthetic-batch', status:'draft', revision:1, counts:{total:1,pending:1},
      cases:[{farmer_id:'synthetic-case',customer_name:'Synthetic applicant',primary_phone:'0712345678',decision:'pending',payment_mode:'CASH'}],activity:[]};
    PortalMiniAppPayments.init({el:id=>document.getElementById(id),escapeHtml:value=>String(value??''),
      state:{capabilities:new Set(['portal.payment.view','portal.payment.prepare'])}, setButtonLoading(){},showToast(){},
      apiFetch:async (url,options) => {
        if (url.endsWith('/remove/')) {changes.push(JSON.parse(options.body)); batch={...batch,cases:[],revision:2};}
        return {ok:true,data:{ok:true,batch,batches:[],pagination:{},results:[]}};
      }});
    await PortalMiniAppPayments.load();
  });
  await page.locator('[data-payment-case] summary').click();
  await page.locator('.payment-remove-case').click();
  await expect(page.locator('.invoice-action-confirm textarea')).toHaveCount(0);
  await page.locator('[data-confirm-cancel]').click();
  expect(await page.evaluate(()=>changes)).toHaveLength(0);
  await page.locator('.payment-remove-case').click();
  await page.locator('[data-confirm-yes]').click();
  await expect.poll(()=>page.evaluate(()=>changes.length)).toBe(1);
  expect(await page.evaluate(()=>changes[0].reason)).toBeUndefined();
  await expect(page.locator('[data-payment-case]')).toHaveCount(0);
});

test('confirmation text is escaped and a second confirmation cannot reuse the first answer', async ({page}) => {
  await mountPortalShell(page, '<button id="trigger">Open</button>');
  await page.addScriptTag({path:asset('portal_dialogs.js')});
  await page.evaluate(() => {
    window.answers=[];
    PortalDialogs.confirmAction('<img src=x onerror="window.injected=true">', 'Synthetic <b>message</b>').then(value=>answers.push(value));
    PortalDialogs.confirmAction('Second action', 'Must not share an answer').then(value=>answers.push(value));
  });
  await expect(page.locator('.invoice-action-confirm')).toHaveCount(1);
  await expect(page.locator('.invoice-action-confirm img, .invoice-action-confirm b')).toHaveCount(0);
  await page.locator('[data-confirm-yes]').click();
  expect(await page.evaluate(()=>answers)).toEqual([false,true]);
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
});

test('TAT authorized direct-save mode hides the audit-note field and reports Saved', async ({page},info) => {
  const template=fs.readFileSync(path.resolve(__dirname,'../templates/tat_tracker/app.html'),'utf8');
  const source=fs.readFileSync(asset('tat_tracker.js'),'utf8');
  const form=template.slice(template.indexOf('<form id="targetSettingsForm"'),template.indexOf('</form>',template.indexOf('<form id="targetSettingsForm"'))+7);
  await page.setViewportSize({width:390,height:844});
  await page.setContent('<main class="tat-app">'+form+'</main>');
  for(const name of ['base.css','tat_tracker.css']) await page.addStyleTag({content:fs.readFileSync(asset(name),'utf8').replace(/^@import[^\r\n]*(?:\r?\n|$)/gm,'')});
  await page.addScriptTag({content:`
    const $=id=>document.getElementById(id);window.calls=[];window.messages=[];
    const targetSettingsPayload=()=>({business:{total_minutes:'1440'}});
    const api=async (url,body)=>{calls.push({url,body});return {ok:true,data:{status:'approved'}};};
    const setStatus=message=>messages.push(message); const loadSettings=async()=>{};
    ${source.slice(source.indexOf('  function setSettingsSaveMode('),source.indexOf('  function applyPersonalPreference('))}
    $('targetSettingsForm').classList.remove('hidden');
    setSettingsSaveMode({can_save_directly:true},'targetSettingsReason','saveTargetSettingsBtn','Save targets','Submit target change');
    $('targetSettingsForm').onsubmit=event=>{event.preventDefault();saveTargetSettings();};
  `});
  await expect(page.locator('#targetSettingsReason')).toBeHidden();
  await expect(page.getByRole('button',{name:'Save targets',exact:true})).toBeVisible();
  await page.screenshot({path:info.outputPath('tat-direct-settings.png')});
  await page.getByRole('button',{name:'Save targets',exact:true}).click();
  expect(await page.evaluate(()=>messages)).toEqual(['Targets saved.']);
  expect(await page.evaluate(()=>calls[0].body.reason)).toBe('');
});
