'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);

test('native primary action preserves validation, has one owner and falls back safely', async ({page}) => {
  await page.setContent('<form><label>Name<input name="name" required></label><button type="submit">Save</button></form><section hidden id="preview"></section>');
  await page.addScriptTag({path:asset('utils.js')});
  await page.evaluate(() => {
    window.clicks = 0; window.handlers = new Set(); window.native = {visible:false,
      setText(value) {this.text=value;}, show() {this.visible=true;}, hide() {this.visible=false;},
      onClick(fn) {handlers.add(fn);}, offClick(fn) {handlers.delete(fn);},
      disable() {this.disabled=true;}, enable() {this.disabled=false;}, showProgress() {}, hideProgress() {}};
    const form=document.querySelector('form'), button=form.querySelector('button');
    MiniAppUtils.bindAccessibleForm(form);
    form.addEventListener('submit', e => {e.preventDefault(); clicks++;});
    window.primary=MiniAppUtils.bindMainAction({telegram:{initData:'synthetic',MainButton:native}, resolve:()=>document.getElementById('preview').hidden ? button : null});
    primary.sync(); primary.sync(); [...handlers][0]();
  });
  expect(await page.evaluate(()=>handlers.size)).toBe(1);
  expect(await page.evaluate(()=>clicks)).toBe(0);
  await expect(page.locator('input')).toHaveAttribute('aria-invalid','true');
  await page.locator('input').fill('Training');
  await page.evaluate(()=>[...handlers][0]());
  expect(await page.evaluate(()=>clicks)).toBe(1);
  await page.evaluate(()=>{document.querySelector('button').disabled=true;primary.sync();});
  expect(await page.evaluate(()=>native.disabled)).toBe(true);
  await page.evaluate(()=>{document.getElementById('preview').hidden=false;primary.sync();});
  expect(await page.evaluate(()=>native.visible)).toBe(false);
  expect(await page.evaluate(()=>handlers.size)).toBe(0);
  await page.evaluate(()=>{document.getElementById('preview').hidden=true;native.show=()=>{throw Error('Bridge unavailable');};primary.sync();});
  await expect(page.locator('button')).not.toHaveClass(/miniapp-native-action/);
});

for (const size of [[1200,800],[800,1600],[2400,300]]) test(`photo corners remain reachable without shrinking the viewport (${size.join('x')})`, async ({page}, info) => {
  await page.setViewportSize({width:390,height:800});
  await page.setContent('<div id="stage" style="width:370px;height:600px"><img alt="Training edge markers"></div>');
  await page.addScriptTag({path:asset('secure_media_viewer.js')});
  await page.evaluate(async ([w,h]) => {
    const image=document.querySelector('img');
    image.src='data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><rect width="100%" height="100%" fill="white"/><rect width="60" height="60" fill="red"/><rect x="${w-60}" y="${h-60}" width="60" height="60" fill="blue"/></svg>`);
    await image.decode(); window.navigations=0;
    window.viewer=SecureMediaViewer.bindImageGestures(document.getElementById('stage'),image,{onNavigate:()=>navigations++});
    viewer.zoom(5);
  },size);
  const initial=await page.locator('#stage').boundingBox();
  for (const direction of [-1,1]) {
    const stage=page.locator('#stage');
    await stage.dispatchEvent('pointerdown',{pointerId:1,pointerType:'touch',clientX:150,clientY:150});
    await stage.dispatchEvent('pointermove',{pointerId:1,pointerType:'touch',clientX:150+direction*10000,clientY:150+direction*10000});
    await stage.dispatchEvent('pointerup',{pointerId:1,pointerType:'touch',clientX:150+direction*10000,clientY:150+direction*10000});
    const boxes=await page.evaluate(()=>({s:document.getElementById('stage').getBoundingClientRect().toJSON(),i:document.querySelector('img').getBoundingClientRect().toJSON()}));
    expect(boxes.s.width).toBe(initial.width); expect(boxes.s.height).toBe(initial.height);
    if(direction===1) {expect(boxes.i.left).toBeGreaterThanOrEqual(boxes.s.left-1);expect(boxes.i.top).toBeGreaterThanOrEqual(boxes.s.top-1);}
    else {expect(boxes.i.right).toBeLessThanOrEqual(boxes.s.right+1);expect(boxes.i.bottom).toBeLessThanOrEqual(boxes.s.bottom+1);}
  }
  expect(await page.evaluate(()=>navigations)).toBe(0);
  await page.screenshot({path:info.outputPath(`photo-edge-${size.join('x')}.png`)});
});

test('draft recovery uses compact labelled icons, preserving the saved values', async ({page}) => {
  await page.setViewportSize({width:320,height:700});
  await page.setContent('<form><label>Name<input name="client_name"></label><p id="status"></p></form>');
  await page.addStyleTag({path:asset('base.css')});
  await page.addScriptTag({path:asset('utils.js')});
  await page.evaluate(async()=>{
    window.fetch=async()=>new Response(JSON.stringify({ok:true,draft:{revision:1,payload:{client_name:'Training customer'}}}));
    await MiniAppUtils.bindCreationDraft(document.querySelector('form'),{workflow:'complaint_create',contextKey:'training',status:document.getElementById('status')}).load();
  });
  await expect(page.locator('.miniapp-draft-prompt strong')).toHaveText('You have a saved draft');
  await expect(page.locator('[data-draft-action=restore] svg')).toHaveCount(1);
  await expect(page.locator('[data-draft-action=discard] svg')).toHaveCount(1);
  await page.getByRole('button',{name:'Restore',exact:true}).click();
  await expect(page.locator('input')).toHaveValue('Training customer');
});
