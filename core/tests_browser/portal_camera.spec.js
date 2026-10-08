'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const {mountPortalShell} = require('./fixtures/portal_shell');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const template = fs.readFileSync(path.resolve(__dirname, '../templates/portal/portal.html'), 'utf8');
const sheet = template.slice(template.indexOf('<div class="sheet-overlay" id="sheet-overlay"'), template.indexOf('<!-- Invoice upload overlay -->'));

async function mountCamera(page, newLead = false) {
  await page.route('http://127.0.0.1:8000/portal/', route=>route.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'}));
  await page.goto('http://127.0.0.1:8000/portal/');
  await mountPortalShell(page, sheet);
  await page.addScriptTag({path:asset('utils.js')});
  await page.addScriptTag({path:asset('portal_farmer_sheet.js')});
  await page.evaluate(newLead => {
    window.cameraRequests = 0; window.cameraStops = 0; window.cameraToasts = [];
    Object.defineProperty(navigator, 'mediaDevices', {configurable:true, value:{async getUserMedia() {
      window.cameraRequests++;
      const stream = new MediaStream();
      stream.getTracks = () => [{stop() {window.cameraStops++;}}];
      return stream;
    }}});
    HTMLMediaElement.prototype.play = async function () {};
    HTMLMediaElement.prototype.pause = function () {};
    Object.defineProperty(HTMLVideoElement.prototype,'videoWidth',{configurable:true,get:()=>640});
    Object.defineProperty(HTMLVideoElement.prototype,'videoHeight',{configurable:true,get:()=>480});
    // Keep real canvas encoding and a detailed synthetic frame above 4 KB.
    const contextFor = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args) {
      const context = contextFor.apply(this,args);
      if (context?.drawImage) context.drawImage=()=>{
        for (let y=0;y<this.height;y+=8) for (let x=0;x<this.width;x+=8) {
          context.fillStyle=(x+y)%16?'#f1c040':'#2369b0'; context.fillRect(x,y,8,8);
        }
      };
      return context;
    };
    window.MiniAppUtils.impactWithFallback=()=>true;
    const state = {capabilities:new Set(['portal.case.read','portal.jbl_visit.write','portal.jbl_media.write']),
      metaStatuses:['Visited'],metaCounties:[],jblVisitMediaMaxFiles:6,businessDate:'2026-10-08'};
    window.PortalMiniAppFarmerSheet.init({el:id=>document.getElementById(id),state,
      escapeHtml:value=>String(value ?? ''),fmt:value=>String(value ?? '-'),fmtDate:value=>String(value ?? '-'),
      locationText:()=>'-',showToast:message=>window.cameraToasts.push(message),
      apiFetch:async()=>({ok:true,data:{ok:true,counties:[],sub_counties:[]}})});
    window.PortalMiniAppFarmerSheet.openFarmerSheet({id:'synthetic-camera-case',customer_name:'Training customer',workflow_revision:1,is_new_jbl_lead:newLead},'jbl_visit');
    window.lucide.createIcons();
  }, newLead);
}

for (const newLead of [false, true]) test(`Portal ${newLead ? 'new lead' : 'existing case'} camera icon opens with shared validation active`, async ({page}, info) => {
  await page.setViewportSize({width:390,height:820});
  await mountCamera(page, newLead);
  await page.locator('[data-camera-category="CLIENT_ID"] svg').click();
  await expect(page.locator('#jbl-camera-overlay')).toHaveClass(/open/);
  await expect(page.locator('#jbl-camera-shutter')).toBeEnabled();
  expect(await page.evaluate(()=>window.cameraRequests)).toBe(1);
  await page.screenshot({path:info.outputPath('portal-camera-open-390.png'),animations:'disabled'});
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-live-camera-title')).toHaveText('Client ID — Back');
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-id-media-name')).toContainText('Ready');
  await expect(page.locator('#jbl-live-camera-title')).toHaveText('LAF — Page 1');
  await page.locator('#jbl-camera-shutter').click();
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-laf-media-name')).toContainText('Ready');
  await expect(page.locator('#jbl-live-camera-title')).toHaveText('Supporting photos');
  await page.locator('#jbl-camera-shutter').click();
  await expect(page.locator('#jbl-visit-photo-media-name')).toContainText('1 selected');
  expect(await page.evaluate(()=>window.cameraRequests)).toBe(1);
  await page.locator('#jbl-camera-close').click();
  expect(await page.evaluate(()=>window.cameraStops)).toBe(1);
  await page.locator('.jbl-document-slot-preview').first().click();
  await expect(page.locator('#media-viewer-overlay')).toHaveClass(/open/);
  await page.locator('#media-viewer-close').click();
  await page.locator('.jbl-media-remove').last().click();
  await expect(page.locator('#jbl-visit-photo-media-name')).toHaveText('No files selected');
});

test('Create lead camera permission errors show feedback instead of silently doing nothing', async ({page}) => {
  await mountCamera(page,true);
  await page.evaluate(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Synthetic permission denial','NotAllowedError');};});
  await page.locator('[data-camera-category="CLIENT_ID"]').click();
  await expect.poll(()=>page.evaluate(()=>window.cameraToasts.at(-1))).toContain('Camera permission was denied');
  await expect(page.locator('#jbl-camera-overlay')).not.toHaveClass(/open/);
  await page.evaluate(()=>{Object.defineProperty(navigator,'mediaDevices',{value:undefined});});
  await page.locator('[data-camera-category="CLIENT_ID"]').click();
  await expect.poll(()=>page.evaluate(()=>window.cameraToasts.at(-1))).toContain('Use the folder icon');
});

test('Create lead file picker is wired independently from server draft recovery', async ({page}) => {
  await mountCamera(page,true);
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQZkAAAAASUVORK5CYII=','base64');
  await page.locator('#jbl-id-media').setInputFiles({name:'synthetic-id-front.png',mimeType:'image/png',buffer:Buffer.concat([png,Buffer.alloc(5000)])});
  await expect(page.locator('.jbl-document-slot-preview:visible')).toHaveCount(1);
  await expect(page.locator('#jbl-id-media')).toHaveValue('');
  await expect(page.locator('#jbl-id-media-name')).toContainText('1 of 2');
});
