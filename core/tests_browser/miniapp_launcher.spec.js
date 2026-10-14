const fs=require('node:fs');
const path=require('node:path');
const {test,expect}=require('playwright/test');
const root=path.resolve(__dirname,'../..');
const template=fs.readFileSync(path.join(root,'core/templates/miniapp_launcher.html'),'utf8')
  .replace(/\{% static '([^']+)' %\}/g,'/static/$1').replace(/\{%[\s\S]*?%\}/g,'').replace(/<script[\s\S]*?<\/script>/g,'').replace(/<link[^>]+>/g,'');
async function mount(page, apps, status=200){
  const requests=[];
  await page.route('http://127.0.0.1/**',route=>{
    if(route.request().url().includes('/static/miniapp/jawabu-logo.png')) return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'core/static/miniapp/jawabu-logo.png'))});
    if(route.request().url().includes('/api/miniapps/available/')){
      requests.push(route.request().headers());
      return route.fulfill({status,json:status===200?{ok:true,apps}:{ok:false,error:'Open JBL Apps from Telegram using your linked staff account.'}});
    }
    return route.fulfill({contentType:'text/html',body:template});
  });
  await page.goto('http://127.0.0.1/apps/');
  await page.evaluate(()=>{window.__opened=[];window.Telegram={WebApp:{initData:'synthetic-only',openTelegramLink:url=>__opened.push(url)}};});
  for(const name of ['base.css','miniapp_launcher.css'])await page.addStyleTag({path:path.join(root,'core/static/miniapp',name)});
  await page.addScriptTag({path:path.join(root,'core/static/miniapp/miniapp_launcher.js')});
  return requests;
}
const apps=[
  {key:'tat_tracker',label:'TAT Tracker',description:'Loan stages and turnaround',destinations:[{label:'Training',url:'https://t.me/example/training?startapp=synthetic'}]},
  {key:'loan_origination',label:'Origination',description:'Loan applications and signatures',destinations:[{label:'Training branch one',url:'http://127.0.0.1/origination/?group_id=training-one'},{label:'Training branch two',url:'http://127.0.0.1/origination/?group_id=training-two'}]},
];
for(const width of [320,390,430,768,1280])for(const dark of [false,true])test(`JBL Apps chooser ${width} ${dark?'dark':'light'}`,async({page},info)=>{
  await page.setViewportSize({width,height:844});await page.emulateMedia({colorScheme:dark?'dark':'light'});
  const requests=await mount(page,apps);
  await expect(page.locator('.app-choice')).toHaveCount(2);
  const heading=await page.locator('.apps-shell>header').boundingBox(), refresh=await page.locator('#apps-refresh').boundingBox();
  expect(Math.abs(heading.y+heading.height/2-refresh.y-refresh.height/2)).toBeLessThan(1);
  expect(heading.x+heading.width-refresh.x-refresh.width).toBeLessThan(1);
  expect(refresh.width).toBe(44);
  expect(requests[0]['x-telegram-init-data']).toBe('synthetic-only');
  await page.getByRole('link',{name:/TAT Tracker/}).click();
  expect(await page.evaluate(()=>__opened.length)).toBe(1);
  await page.getByText('Origination',{exact:true}).click();
  await expect(page.getByRole('link',{name:'Training branch one'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:info.outputPath(`apps-${width}-${dark?'dark':'light'}.png`),fullPage:true});
});
test('launcher shows empty and authentication errors with refresh recovery',async({page})=>{
  await mount(page,[]);await expect(page.locator('#apps-status')).toContainText('No apps are assigned');
  await page.route('**/api/miniapps/available/',route=>route.fulfill({status:403,json:{ok:false,error:'Open JBL Apps from Telegram using your linked staff account.'}}));
  await page.getByRole('button',{name:'Refresh apps'}).click();
  await expect(page.locator('#apps-status')).toContainText('linked staff account');
  await expect(page.getByRole('button',{name:'Refresh apps'})).toBeEnabled();
});
