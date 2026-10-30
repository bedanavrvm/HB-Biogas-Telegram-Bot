/* Direct browser capture and observations. No assertions or test framework. */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const base=__dirname,origin='http://127.0.0.1:8778';
const sandbox={window:{}};vm.runInNewContext(fs.readFileSync(path.join(base,'catalogue.js'),'utf8'),sandbox);
const catalogue=sandbox.window.PORTAL_UX;
const only=process.argv.find(a=>a.startsWith('--only='))?.split('=')[1].split(',');
const scenarios=only?catalogue.scenarios.filter(s=>only.includes(s.id)):catalogue.scenarios;
(async()=>{
 const browser=await chromium.launch();
 const context=await browser.newContext({viewport:{width:390,height:844}});
 const errors=[],requests=[],observations=[];
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin===origin&&route.request().method()==='GET')return route.continue();
  if(['data:','blob:'].includes(url.protocol))return route.continue();
  requests.push({method:route.request().method(),url:route.request().url(),blocked:true});return route.abort();
 });
 const page=await context.newPage();page.on('pageerror',error=>errors.push({url:page.url(),message:error.message}));
 for(const dir of ['after','boards','responsive'])fs.mkdirSync(path.join(base,'assets',dir),{recursive:true});
 for(const s of scenarios){
  for(const v of ['a','b']){
   await page.setViewportSize({width:s.width,height:844});
   await page.goto(`${origin}/preview.html?case=${s.id}&variant=${v}&capture=1`);
   await page.waitForTimeout(150);
   await page.screenshot({path:path.join(base,'assets/after',`${s.id}-${v}.png`),animations:'disabled'});
   const geometry=await page.evaluate(()=>({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,heading:document.querySelector('main h1')?.textContent,primaryActions:Array.from(document.querySelectorAll('.primary')).map(n=>n.textContent.trim())}));
   observations.push({case:s.id,variant:v,...geometry});
  }
  console.log('Captured '+s.id+' A/B');
 }
 if(!only){
  for(const s of scenarios){
   await page.setViewportSize({width:1280,height:1000});
   await page.goto(`${origin}/index.html?board=${s.id}`);
   await page.waitForFunction(()=>Array.from(document.images).every(img=>img.complete&&img.naturalWidth>0));
   await page.screenshot({path:path.join(base,'assets/boards',s.id+'.png'),fullPage:true,animations:'disabled'});
  }
  for(const id of ['farmup','payment-list','upload-error'])for(const v of ['a','b'])for(const width of id==='upload-error'?[320]:[320,1280]){
   await page.setViewportSize({width,height:844});await page.goto(`${origin}/preview.html?case=${id}&variant=${v}&capture=1`);await page.waitForTimeout(120);
   await page.screenshot({path:path.join(base,'assets/responsive',`${id}-${v}-${width}.png`),animations:'disabled'});
   observations.push({case:id,variant:v,width,...await page.evaluate(()=>({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth}))});
  }
  for(const id of ['invoice','payment-done','upload-error'])for(const v of ['a','b']){
   await page.setViewportSize({width:390,height:844});await page.goto(`${origin}/preview.html?case=${id}&variant=${v}&capture=1&theme=dark`);await page.waitForTimeout(120);
   await page.screenshot({path:path.join(base,'assets/responsive',`${id}-${v}-dark.png`),animations:'disabled'});
  }
 }
 const result={captured_at:new Date().toISOString(),method:'Direct Playwright capture; no assertions or test runner',observations,errors,blockedRequests:requests};
 fs.writeFileSync(path.join(base,only?'capture-incremental.json':'capture-observations.json'),JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify({screens:observations.length,errors,blockedRequests:requests}));
 await browser.close();
})();
