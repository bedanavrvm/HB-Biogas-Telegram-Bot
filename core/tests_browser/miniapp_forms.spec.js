'use strict';

const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);

async function mount(page, markup) {
  await page.setContent(`<body>${markup}</body>`);
  await page.addStyleTag({path: asset('base.css')});
  await page.addStyleTag({content:'* { transition: none !important; animation: none !important; }'});
  await page.addScriptTag({path: asset('utils.js')});
}

async function formScale(page, selector = 'form') {
  return page.locator(selector).evaluate(form => [...form.querySelectorAll('label,input,select,textarea,small:not(.miniapp-field-error),.field-help')].map(node => {
    const css = getComputedStyle(node);
    return {font:css.fontSize,line:css.lineHeight,minHeight:css.minHeight,padding:css.padding};
  }));
}

test('Shared forms collect all errors, preserve input, and revalidate only flagged fields', async ({page}, info) => {
  await mount(page, '<form><label>Name<input name="name" required aria-describedby="name-help"></label><small id="name-help">Customer name</small><label>National ID<input name="id" required></label><label>Phone<input name="phone" required></label><button>Save</button></form>');
  await page.evaluate(() => {
    window.formController = MiniAppUtils.bindAccessibleForm(document.querySelector('form'), {validators: {
      id: value => /^\d{1,9}$/.test(value) ? '' : 'Enter a National ID using 1 to 9 digits.',
      phone: value => MiniAppUtils.normalizeKenyanPhone(value) ? '' : 'Enter a valid Kenyan mobile number.',
    }});
    window.writes = 0;
    document.querySelector('form').addEventListener('submit', event => {event.preventDefault(); window.writes++;});
  });
  await page.locator('[name=id]').fill('1');
  await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
  await expect(page.locator('[aria-invalid=true]')).toHaveCount(0);
  await page.getByRole('button', {name: 'Save'}).click();
  await expect(page.locator('.miniapp-field-error:visible')).toHaveCount(2);
  await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
  await expect(page.locator('[name=name]')).toBeFocused();
  expect(await page.evaluate(() => window.writes)).toBe(0);
  await page.locator('[name=phone]').fill('07');
  await expect(page.locator('[name=phone]')).toHaveAttribute('aria-invalid', 'true');
  await page.locator('[name=name]').fill('Training Customer');
  await expect(page.locator('[name=name]')).not.toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('[name=name]')).toHaveAttribute('aria-describedby', 'name-help');
  await page.locator('[name=id]').fill('123456');
  await expect(page.locator('.miniapp-field-error:visible')).toHaveCount(1);
  await page.getByRole('button', {name:'Save'}).click();
  await expect(page.locator('[name=phone]')).toBeFocused();
  await page.locator('[name=phone]').fill('0712345678');
  await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
  await page.getByRole('button', {name: 'Save'}).click();
  expect(await page.evaluate(() => window.writes)).toBe(1);
  await page.evaluate(() => window.formController.show({name: 'Please check the customer name.', phone: 'Check the mobile number.'}));
  await expect(page.locator('[name=name]')).toHaveAttribute('aria-describedby', /name-help .*error/);
  await page.setViewportSize({width: 320, height: 700});
  await page.screenshot({path: info.outputPath('shared-form-errors-320.png'), fullPage: true});
});

test('Hidden and disabled requirements never block an unrelated action', async ({page}) => {
  await mount(page, '<form><label>Comment<textarea name="comment" required></textarea></label><section hidden><label>Resolution<input name="resolution" required></label></section><label>Disabled<input name="disabled" disabled required></label></form>');
  await page.locator('[name=comment]').fill('Training feedback');
  expect(await page.evaluate(() => MiniAppUtils.bindAccessibleForm(document.querySelector('form')).validate())).toBe(true);
});

test('Mapped workflow errors clear only when corrected and adjacent labels stay associated', async ({page}) => {
  await mount(page, '<form><div class="form-row"><label>Visit county</label><input id="visit-county"></div><button>Save</button></form>');
  await page.evaluate(() => {
    window.controller = MiniAppUtils.bindAccessibleForm(document.querySelector('form'), {
      resolveField: key => key === 'county' ? document.getElementById('visit-county') : null,
      validate: () => document.getElementById('visit-county').value === 'Synthetic county' ? {} : {county:'Choose a valid county.'},
    });
    window.controller.show({county:'Choose a valid county.'});
  });
  const input = page.getByRole('textbox', {name:'Visit county'});
  await input.fill('Not valid');
  await expect(input).toHaveAttribute('aria-invalid','true');
  await input.fill('Synthetic county');
  await expect(input).not.toHaveAttribute('aria-invalid','true');
  await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
});

test('Origination repeating-row errors target the actual column rather than the first input', async ({page}) => {
  await mount(page, '<main id="origination-root"><div data-field-wrap="assets"><div data-repeat-row><label>Item<input data-repeat-column="name"></label><label>Value<input data-repeat-column="value"></label></div><div data-repeat-row><label>Item<input data-repeat-column="name"></label><label>Value<input data-repeat-column="value"></label></div></div></main>');
  const source = fs.readFileSync(path.join(root,'origination/static/miniapp/loan_origination.js'),'utf8');
  const start = source.indexOf('  function originationErrorControl(');
  const resolver = source.slice(start, source.indexOf('  function showErrors(',start));
  await page.evaluate(resolver => {
    const resolve = new Function(`const root = () => document.getElementById('origination-root'); ${resolver}; return originationErrorControl;`)();
    window.controller = MiniAppUtils.bindAccessibleForm(document.getElementById('origination-root'), {resolveField:resolve});
    window.controller.show({'assets.1.value':'Enter the estimated value.'});
  }, resolver);
  await expect(page.locator('[data-repeat-row]').nth(1).locator('[data-repeat-column=value]')).toHaveAttribute('aria-invalid','true');
  await expect(page.locator('[data-repeat-row]').nth(0).locator('[aria-invalid=true]')).toHaveCount(0);
  await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
  await expect(page.locator('[data-repeat-row]').nth(1).locator('[data-repeat-column=value]')).toBeFocused();
});

test('Dynamic forms install once and preserve accessible field names', async ({page}) => {
  await mount(page, '<main></main>');
  await page.evaluate(() => {window.stopForms = MiniAppUtils.installAccessibleForms(); document.querySelector('main').innerHTML = '<form><label for="description">What happened?</label><textarea id="description" name="description" required></textarea></form>';});
  await expect(page.locator('form')).toHaveClass('miniapp-form');
  await page.evaluate(() => MiniAppUtils.bindAccessibleForm(document.querySelector('form')).show({description: 'Describe the complaint.'}));
  await expect(page.getByRole('textbox', {name: 'What happened?'})).toHaveCount(1);
  await expect(page.locator('.miniapp-field-error')).toHaveCount(1);
  await page.evaluate(() => window.stopForms());
});

test('Kenyan phone normalization matches the shared backend examples without changing invalid text', async ({page}) => {
  await mount(page, '<p>Shared identifiers</p>');
  for (const value of ['0712345678', '712345678', '+254 0712 345 678', '00254712345678', '005712345678']) {
    expect(await page.evaluate(value => MiniAppUtils.normalizeKenyanPhone(value), value)).toBe('254712345678');
  }
  for (const value of ['07', 'hello', '254199123456', '0712+345678', '07123abc5678']) {
    expect(await page.evaluate(value => MiniAppUtils.normalizeKenyanPhone(value), value)).toBe('');
  }
});

for (const [app, template, id, css] of [
  ['complaints', 'core/templates/complaint_cases/app.html', 'createCaseForm', 'complaint_cases.css'],
  ['tat', 'core/templates/tat_tracker/app.html', 'newCaseForm', 'tat_tracker.css'],
]) for (const width of [320, 360, 390, 430, 768, 1280]) {
  test(`${app} creation keeps the existing form scale and inline errors at ${width}px`, async ({page}, info) => {
    const source = fs.readFileSync(path.join(root, template), 'utf8');
    const start = source.indexOf(`<form id="${id}"`);
    const html = source.slice(start, source.indexOf('</form>', start) + 7).replace(/\{%[\s\S]*?%\}/g, '').replace(/\{\{[\s\S]*?\}\}/g, '');
    await mount(page, `<main style="padding:12px">${html}</main>`);
    await page.setViewportSize({width, height: 820});
    await page.addStyleTag({path: asset(css)});
    const previousScale = await formScale(page);
    await page.evaluate(id => MiniAppUtils.bindAccessibleForm(document.getElementById(id)), id);
    expect(await formScale(page)).toEqual(previousScale);
    await page.screenshot({path: info.outputPath(`${app}-ready-${width}.png`), fullPage: true});
    await page.evaluate(id => MiniAppUtils.bindAccessibleForm(document.getElementById(id)).validate(), id);
    await expect(page.locator('.miniapp-field-error:visible')).not.toHaveCount(0);
    await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
    const inspect = () => page.locator('form').evaluate(form => {
      const controls = [...form.querySelectorAll('input:not([type=file]),select,textarea')];
      return {
        unlabelled: controls.filter(input => !input.labels?.length && !input.hasAttribute('aria-label')).map(input => input.name),
        overflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    await expect.poll(inspect).toEqual({unlabelled: [], overflow: false});
    await page.screenshot({path: info.outputPath(`${app}-errors-${width}.png`), fullPage: true});
  });
}

test('Creation recovery prompts before restoring and never saves files, tokens or OTPs', async ({page}) => {
  await mount(page, '<form><label>Name<input name="client_name"></label><input name="otp_code"><input name="token" type="hidden"><input name="files" type="file"><p id="draft-status"></p></form>');
  await page.evaluate(() => {
    window.draftWrites = [];
    window.fetch = async (url, options) => {
      if (options.method === 'POST') window.draftWrites.push(JSON.parse(options.body));
      return new Response(JSON.stringify({ok:true,draft:options.method === 'GET' ? {revision:1,payload:{client_name:'Restored customer'}} : {revision:2}}), {status:200});
    };
    window.recovery = MiniAppUtils.bindCreationDraft(document.querySelector('form'), {workflow:'complaint_create',contextKey:'synthetic-group',status:document.getElementById('draft-status')});
    return window.recovery.load();
  });
  await expect(page.locator('[name=client_name]')).toHaveValue('');
  await page.getByRole('button', {name:'Restore', exact:true}).click();
  await expect(page.locator('[name=client_name]')).toHaveValue('Restored customer');
  await page.locator('[name=client_name]').fill('Updated customer');
  await expect.poll(() => page.evaluate(() => window.draftWrites.length)).toBe(1);
  expect(await page.evaluate(() => window.draftWrites[0])).toEqual({revision:1,payload:{client_name:'Updated customer'}});
  await page.evaluate(() => window.recovery.clear());
  await expect(page.locator('.miniapp-draft-prompt')).toHaveCount(0);
});

test('Non-field server failures remain one concise notice without duplicating field errors', async ({page}) => {
  await mount(page, '<form><label>Name<input name="name"></label></form>');
  await page.evaluate(() => {
    window.controller = MiniAppUtils.bindAccessibleForm(document.querySelector('form'));
    window.controller.show({name:'Check the name.',__all__:'Connection interrupted. Retry saving.',other:'A second general error.'});
  });
  await expect(page.locator('[name=name]')).toBeFocused();
  await expect(page.locator('.miniapp-field-error')).toHaveText('Check the name.');
  await expect(page.getByRole('alert')).toHaveText('Connection interrupted. Retry saving.');
  await expect(page.locator('.miniapp-form-errors,ul')).toHaveCount(0);
  await page.evaluate(() => window.controller.show({__all__:'Please refresh before saving.'}));
  await expect(page.getByRole('alert')).toBeFocused();
  await page.evaluate(() => window.controller.clear());
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('Multi-section editors open and focus the first invalid field without a summary', async ({page}) => {
  await mount(page, '<main><section><label>Name<input name="name" value="Retained name"></label></section><section id="next-section"></section></main>');
  await page.evaluate(() => {
    window.controller = MiniAppUtils.bindAccessibleForm(document.querySelector('main'), {
      isFieldError: key=>key==='amount',
      focusField: key=>{
        if (key !== 'amount') return false;
        document.getElementById('next-section').innerHTML='<label>Amount<input name="amount"></label>';
        window.controller.show({amount:'Enter an amount.'},false);
        document.querySelector('[name=amount]').focus();
        return true;
      },
    });
    window.controller.show({amount:'Enter an amount.'});
  });
  await expect(page.locator('[name=amount]')).toBeFocused();
  await expect(page.locator('[name=amount]')).toHaveAttribute('aria-invalid','true');
  await expect(page.locator('.miniapp-field-error')).toHaveText('Enter an amount.');
  await expect(page.locator('[name=name]')).toHaveValue('Retained name');
  await expect(page.locator('.miniapp-form-errors,.miniapp-form-notice')).toHaveCount(0);
});

for (const width of [320,1280]) test(`Origination editor fields retain their original scale at ${width}px`, async ({page}, info) => {
  const source=fs.readFileSync(path.join(root,'origination/static/miniapp/loan_origination.js'),'utf8');
  const start=source.indexOf('  function fieldInput(');
  const renderer=source.slice(start,source.indexOf('  function numericInputError(',start));
  await mount(page,'<main id="origination-root"><div class="laf-grid"></div></main>');
  await page.setViewportSize({width,height:820});
  await page.addStyleTag({path:asset('workflow_standard.css')});
  await page.addStyleTag({path:path.join(root,'origination/static/miniapp/loan_origination.css')});
  await page.evaluate(renderer=>{
    const render=new Function(`const escapeHtml=value=>String(value??''); const normalizeLabel=field=>field.label; const FULL_WIDTH=new Set(); const current={status:'draft'}; ${renderer}; return fieldInput;`)();
    const fields=[{key:'name',label:'Applicant name',type:'text',required:true},
      {key:'national_id',label:'National ID',type:'national_id',required:true},
      {key:'phone',label:'Mobile number',type:'phone',required:true},
      {key:'loan_amount',label:'Loan amount',type:'money',required:true,help_text:'Enter whole KES amounts.'}];
    document.querySelector('.laf-grid').innerHTML=fields.map(field=>render(field,'',false)).join('');
  },renderer);
  const previousScale=await formScale(page,'#origination-root');
  await page.evaluate(()=>MiniAppUtils.bindAccessibleForm(document.getElementById('origination-root')).validate());
  expect(await formScale(page,'#origination-root')).toEqual(previousScale);
  await expect(page.locator('[data-field=name]')).toBeFocused();
  await expect(page.locator('.miniapp-form-errors')).toHaveCount(0);
  await page.screenshot({path:info.outputPath(`origination-editor-errors-${width}.png`),fullPage:true});
});

for (const theme of ['light','dark']) test(`Restore is green and Discard red in ${theme} without changing draft behavior`, async ({page}, info) => {
  await page.setViewportSize({width:320,height:700});
  await mount(page, '<form><label>Name<input name="name" value="Entered name"></label></form>');
  await page.evaluate(async theme => {
    document.documentElement.dataset.miniappColorScheme=theme;
    window.draftDeletes=0;
    window.fetch = async (_, options) => {
      if (options.method==='DELETE') window.draftDeletes++;
      return new Response(JSON.stringify({ok:true,draft:options.method==='GET'?{revision:1,payload:{name:'Saved name'}}:null}),{status:200});
    };
    window.recovery=MiniAppUtils.bindCreationDraft(document.querySelector('form'),{workflow:'tat_create',contextKey:'synthetic-group'});
    await window.recovery.load();
  }, theme);
  await expect(page.getByRole('button',{name:'Restore',exact:true})).toHaveCSS('color',theme==='dark'?'rgb(103, 211, 145)':'rgb(22, 128, 60)');
  await expect(page.getByRole('button',{name:'Discard',exact:true})).toHaveCSS('color',theme==='dark'?'rgb(255, 156, 151)':'rgb(192, 57, 43)');
  await page.screenshot({path:info.outputPath(`draft-actions-${theme}-320.png`)});
  await page.getByRole('button',{name:'Discard',exact:true}).click();
  expect(await page.evaluate(()=>window.draftDeletes)).toBe(1);
  await expect(page.locator('[name=name]')).toHaveValue('Entered name');
  await expect(page.locator('.miniapp-draft-prompt')).toHaveCount(0);
});

test('Real Origination signer form validates signature and OTP without losing typed input', async ({page}, info) => {
  let session = {reference:'SYNTHETIC-LAF',signer_role:'borrower',phone_masked:'+254 *** 001',access_mode:'remote',
    documents:[{key:'laf',name:'Synthetic loan form',page_count:1}],reviewed_pages:[],consented:false,status:'pending',otp:{},packet_version:'test-v1'};
  let consentWrites = 0, verificationWrites = 0;
  const template = fs.readFileSync(path.join(root,'origination/templates/loan_origination/sign.html'),'utf8')
    .replace(/\{%[\s\S]*?%\}/g,'').replace(/<script[\s\S]*?<\/script>/g,'').replace(/data-session-url=""/,'data-session-url="/api/origination/sign/api/session/"');
  await page.route('http://miniapp.test/**', async route => {
    const url = new URL(route.request().url());
    if(url.pathname === '/sign') return route.fulfill({contentType:'text/html',body:template});
    if(url.pathname.endsWith('/packet/')) return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQZkAAAAASUVORK5CYII=','base64'),headers:{'X-Preview-Page-Count':'1','X-Signing-Packet-Version':'test-v1'}});
    if(url.pathname.endsWith('/consent/')) {consentWrites++;session={...session,consented:true};}
    if(url.pathname.endsWith('/otp/')) session={...session,otp:{expires_at:'2099-01-01T00:00:00Z'}};
    if(url.pathname.endsWith('/verify/')) {verificationWrites++;session={...session,status:'verified',completion_text:'Synthetic signing complete.'};}
    return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,session})});
  });
  await page.setViewportSize({width:320,height:820});
  await page.goto('http://miniapp.test/sign#synthetic-only');
  await page.addStyleTag({path:asset('base.css')});
  await page.addStyleTag({path:path.join(root,'origination/static/miniapp/origination_signing.css')});
  await page.addScriptTag({path:asset('utils.js')});
  const originalOtpScale=await page.locator('#otp-code').evaluate(input=>[getComputedStyle(input).fontSize,getComputedStyle(input).minHeight]);
  await page.addScriptTag({path:path.join(root,'origination/static/miniapp/origination_signing.js')});
  await expect(page.locator('#page-label')).toHaveText('1 / 1');
  expect(await page.locator('#otp-code').evaluate(input=>[getComputedStyle(input).fontSize,getComputedStyle(input).minHeight])).toEqual(originalOtpScale);
  await page.locator('#save-signature').click();
  await expect(page.locator('#signature-pad')).toHaveAttribute('aria-invalid','true');
  expect(consentWrites).toBe(0);
  await page.locator('#mode-typed').click();
  await expect(page.locator('#signature-pad')).not.toHaveAttribute('aria-invalid','true');
  await page.locator('#typed-name').fill('Synthetic Borrower');
  await page.locator('#packet-consent').check();
  await page.locator('#save-signature').click();
  expect(consentWrites).toBe(1);
  await page.locator('#send-otp').click();
  await page.locator('#otp-code').fill('12');
  await page.locator('#verify-otp').click();
  await expect(page.locator('#otp-code')).toHaveAttribute('aria-invalid','true');
  await expect(page.locator('#typed-name')).toHaveValue('Synthetic Borrower');
  expect(verificationWrites).toBe(0);
  await page.screenshot({path:info.outputPath('signer-otp-error-320.png'),fullPage:true});
  await page.locator('#otp-code').fill('123456');
  await page.locator('#verify-otp').click();
  await expect(page.locator('#sign-status')).toHaveText('Synthetic signing complete.');
});
