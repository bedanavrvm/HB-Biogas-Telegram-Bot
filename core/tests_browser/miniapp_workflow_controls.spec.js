'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const root = path.resolve(__dirname, '../..');
const asset = name => path.join(root, 'core/static/miniapp', name);
const {initData} = require('./fixtures/local_mcp_fixtures.js');
const {mountPortalShell} = require('./fixtures/portal_shell');
test.use({hasTouch:true});

async function complaint(page, {native = false, empty = false} = {}) {
  await page.route(/^https?:\/\//, route => route.abort());
  const html = fs.readFileSync(path.join(root, 'core/templates/complaint_cases/app.html'), 'utf8')
    .replace('{% include "complaint_cases/lucide_icons.html" %}', fs.readFileSync(path.join(root, 'core/templates/complaint_cases/lucide_icons.html'), 'utf8'))
    .replace(/{#[\s\S]*?#}|{%[\s\S]*?%}|{{[\s\S]*?}}/g, '')
    .replace(/<script[^>]*>[\s\S]*?<\/script>|<link[^>]*>|<img[^>]*>/g, '');
  await page.setContent(html);
  for (const name of ['base.css', 'components.css', 'complaint_cases.css']) await page.addStyleTag({path:asset(name)});
  await page.evaluate(({initData, native, empty}) => {
    document.body.dataset.groupId = '-100-synthetic-controls';
    window.__handlers = new Set(); window.__native = {visible:false, setText(text){this.text=text;}, show(){this.visible=true;}, hide(){this.visible=false;},
      enable(){this.disabled=false;}, disable(){this.disabled=true;}, showProgress(){}, hideProgress(){}, onClick(fn){__handlers.add(fn);}, offClick(fn){__handlers.delete(fn);}};
    window.Telegram = {WebApp:{initData, ready(){},expand(){}, BackButton:{show(){},hide(){},onClick(){}}, onEvent(){}, ...(native ? {MainButton:__native} : {})}};
    window.__emptyCategories = empty;
    window.ComplaintCasesMiniAppApi = {
      postJson:async route => route === 'bootstrap/' ? {data:{actor:{name:'Training officer',role:'OFFICER',capabilities:['complaint.queue.view','complaint.case.create']},
        counts:{},branches:['Training branch'], categories:__emptyCategories?[]:['Leakage','Burner fault'], category_catalogue:[{label:'Leakage',description:'Synthetic leakage guidance'}],
        location_options:{counties:[{code:'TRAIN',name:'Training county'}]}}} : {cases:[],pagination:{page:1,pages:1,total:0}},
      getJson:async () => ({data:{counties:[{code:'TRAIN',name:'Training county'}],sub_counties:[{code:'TRAIN-SUB',name:'Training constituency'}]}}),
    };
    window.fetch = async () => new Response(JSON.stringify({ok:true,draft:null}));
  }, {initData,native,empty});
  for (const name of ['utils.js','secure_media_viewer.js','complaint_cases.js']) await page.addScriptTag({path:asset(name)});
  await page.locator('#newCaseBtn').click();
}

for (const width of [320,360,390,430,768,1280]) test(`full complaint form controls fit ${width}px in both themes`, async ({page}, info) => {
  const errors=[]; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({width,height:850}); await complaint(page);
  const form=page.locator('#createCaseForm');
  const category=form.locator('[name=complaint_category]');
  // A real tap/focus/keyboard selection, not selectOption alone: catch overlays
  // stealing taps and malformed/disabled native controls.
  await category.tap(); await expect(category).toBeFocused();
  await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter');
  await expect(category).toHaveValue('Leakage');
  await expect(page.locator('#categoryGuidance')).toHaveText('Synthetic leakage guidance');
  await form.locator('[name=branch_region]').selectOption('Training branch');
  await form.locator('[name=county]').selectOption('TRAIN');
  await expect(form.locator('[name=sub_county]')).toBeEnabled();
  await form.locator('[name=sub_county]').selectOption('TRAIN-SUB');
  await page.locator('#createSaveBtn').click();
  await expect(form.locator('[name=client_name]')).toHaveAttribute('aria-invalid','true');
  await expect(category).toHaveValue('Leakage');
  // The synthetic draft transport intentionally fails. Its retry control must
  // remain in the right-hand status group rather than become a third column.
  await expect(page.locator('.complaint-create-save button')).toBeVisible();
  for (const theme of ['light','dark']) {
    await page.evaluate(theme => {document.documentElement.dataset.miniappColorScheme=theme;},theme);
    await page.evaluate(() => scrollTo(0,0));
    const heading = await page.locator('.complaint-create-heading').boundingBox(), status = await page.locator('#createSaveState').boundingBox();
    expect(Math.abs(heading.x+heading.width-status.x-status.width)).toBeLessThan(2);
    const retry = await page.locator('.complaint-create-save button').boundingBox();
    expect(Math.abs(heading.x+heading.width-retry.x-retry.width)).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`complaint-create-${width}-${theme}.png`),fullPage:true});
  }
  expect(errors).toEqual([]);
});

test('complaint type unavailable state reloads without erasing entered fields', async ({page}) => {
  await complaint(page,{empty:true});
  await page.locator('[name=client_name]').fill('Synthetic Entered Name');
  await expect(page.locator('#createSaveBtn')).toBeDisabled();
  await expect(page.locator('#retryComplaintTypes')).toBeVisible();
  await page.evaluate(() => {__emptyCategories=false;});
  await page.locator('#retryComplaintTypes').click();
  await expect(page.locator('#retryComplaintTypes')).toBeHidden();
  await expect(page.locator('#createCaseForm [name=complaint_category]')).toBeEnabled();
  await expect(page.locator('[name=client_name]')).toHaveValue('Synthetic Entered Name');
});

test('complaint native submit validates and gives way to evidence preview and queue', async ({page}) => {
  await complaint(page,{native:true});
  await expect.poll(() => page.evaluate(() => __native.visible && __handlers.size===1)).toBe(true);
  await expect(page.locator('#createSaveBtn')).toHaveClass(/miniapp-native-action/);
  await page.evaluate(() => [...__handlers][0]());
  await expect(page.locator('[name=client_name]')).toHaveAttribute('aria-invalid','true');
  await page.evaluate(() => {document.getElementById('mediaViewerOverlay').hidden=false;});
  await expect.poll(() => page.evaluate(() => __native.visible)).toBe(false);
  await page.locator('#mediaViewerClose').click();
  await expect.poll(() => page.evaluate(() => __native.visible)).toBe(true);
  await page.locator('#createView [data-back]').click();
  await expect.poll(() => page.evaluate(() => __handlers.size)).toBe(0);
});

test('complaint selected-photo preview reaches its corners and swipes only when fitted', async ({page},info) => {
  await page.setViewportSize({width:320,height:850}); await complaint(page);
  const png=await page.evaluate(()=>{
    const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=800;
    const context=canvas.getContext('2d');context.fillStyle='white';context.fillRect(0,0,1200,800);
    context.fillStyle='red';context.fillRect(0,0,60,60);return canvas.toDataURL('image/png').split(',')[1];
  });
  await page.locator('#createEvidenceInput').setInputFiles(['A','B'].map(label=>({name:`Training-${label}.png`,mimeType:'image/png',buffer:Buffer.from(png,'base64')})));
  await page.locator('#createSelectedEvidence .view-file').first().click();
  const stage=page.locator('#mediaViewerContent');
  await stage.locator('img').evaluate(image=>image.decode());
  const initial=await stage.boundingBox();
  await stage.dispatchEvent('pointerdown',{pointerId:1,clientX:100,clientY:200});
  await stage.dispatchEvent('pointerdown',{pointerId:2,clientX:140,clientY:200});
  await stage.dispatchEvent('pointermove',{pointerId:2,clientX:340,clientY:200});
  await expect(stage).toHaveAttribute('data-zoom','5');
  for(const pointerId of [1,2]) await stage.dispatchEvent('pointerup',{pointerId,clientX:100,clientY:200});
  await stage.dispatchEvent('pointerdown',{pointerId:3,clientX:150,clientY:150});
  await stage.dispatchEvent('pointermove',{pointerId:3,clientX:10000,clientY:10000});
  await stage.dispatchEvent('pointerup',{pointerId:3,clientX:10000,clientY:10000});
  await expect(page.locator('#mediaViewerSub')).toContainText('Training-A.png');
  const boxes=await stage.evaluate(node=>({s:node.getBoundingClientRect().toJSON(),i:node.querySelector('img').getBoundingClientRect().toJSON()}));
  expect(boxes.s.height).toBe(initial.height);expect(boxes.i.left).toBeGreaterThanOrEqual(boxes.s.left-1);
  await page.screenshot({path:info.outputPath('complaint-photo-corner-320.png')});
  await stage.dispatchEvent('keydown',{key:'0'});
  await stage.dispatchEvent('pointerdown',{pointerId:4,clientX:230,clientY:200});
  await stage.dispatchEvent('pointerup',{pointerId:4,clientX:100,clientY:200});
  await expect(page.locator('#mediaViewerSub')).toContainText('Training-B.png');
  await page.locator('#mediaViewerClose').click();
  await expect(stage).not.toHaveAttribute('data-zoom',/.+/);
});

test('Portal native action follows the current form and yields to its media viewer', async ({page}) => {
  await mountPortalShell(page, '<section id="portal-screen" data-screen="visits"><form><label>Name<input name="name" required></label><button type="submit" data-main-action="Log visit">Log visit</button></form><div id="media-viewer-overlay" class="media-viewer-overlay"></div></section>');
  await page.evaluate(({initData}) => {
    window.__writes=0; window.__handlers=new Set();
    window.__native={show(){this.visible=true;},hide(){this.visible=false;},setText(text){this.text=text;},enable(){},disable(){},hideProgress(){},onClick(fn){__handlers.add(fn);},offClick(fn){__handlers.delete(fn);}};
    window.Telegram={WebApp:{initData,ready(){},expand(){},onEvent(){},MainButton:__native,BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};
    window.PortalAppShell={activate(){}};
    document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();__writes++;});
  },{initData});
  for(const name of ['utils.js','miniapp-nav.js']) await page.addScriptTag({path:asset(name)});
  await page.evaluate(()=>{MiniAppUtils.installAccessibleForms(); document.dispatchEvent(new Event('DOMContentLoaded'));});
  await expect.poll(()=>page.evaluate(()=>__handlers.size)).toBe(1);
  await page.evaluate(()=>[...__handlers][0]());
  await expect(page.locator('[name=name]')).toHaveAttribute('aria-invalid','true');
  expect(await page.evaluate(()=>__writes)).toBe(0);
  await page.evaluate(()=>document.getElementById('media-viewer-overlay').classList.add('open'));
  await expect.poll(()=>page.evaluate(()=>__native.visible)).toBe(false);
  await page.evaluate(()=>document.getElementById('media-viewer-overlay').classList.remove('open'));
  await expect.poll(()=>page.evaluate(()=>__handlers.size)).toBe(1);
  await page.locator('[name=name]').fill('Synthetic Applicant');
  await page.evaluate(()=>[...__handlers][0]());
  expect(await page.evaluate(()=>__writes)).toBe(1);
});
