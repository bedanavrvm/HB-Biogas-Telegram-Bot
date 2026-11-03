'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
  let input='';for await(const chunk of process.stdin)input+=chunk;
  const config=JSON.parse(input);assert.ok(['localhost','127.0.0.1'].includes(new URL(config.origin).hostname));
  fs.mkdirSync(config.artifacts,{recursive:true});
  const browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1280,height:900}});
  await context.addCookies([{name:config.cookieName,value:config.cookieValue,url:config.origin,httpOnly:true,sameSite:'Lax'}]);
  const page=await context.newPage();page.setDefaultTimeout(20000);
  await page.route('**/*',route=>new URL(route.request().url()).origin===config.origin?route.continue():route.abort());
  try{
    await page.goto(config.origin+`/admin/core/groupsheetconfiguration/${config.group}/reset-group-data/`);
    await page.locator('[name=backup_reference]').fill('verified-synthetic-backup-browser');
    await page.locator('[name=confirm_group]').fill(config.groupId);
    await page.locator('[name=confirm_number_reuse]').check();await page.locator('[name=confirm_reset]').check();
    await page.screenshot({path:path.join(config.artifacts,'01-reviewed-reset.png'),animations:'disabled'});
    await page.getByRole('button',{name:'Reset local DB data',exact:true}).click();
    await page.getByText(/Portal reset complete for/).waitFor();
    assert.match(await page.locator('body').innerText(),/1 case\(s\) and 0 verified Sheet row\(s\) removed/);
    await page.screenshot({path:path.join(config.artifacts,'02-legacy-reset-complete.png'),animations:'disabled'});
    fs.writeFileSync(path.join(config.artifacts,'observations.json'),JSON.stringify({realAdminForm:true,legacyHbWithoutSignedOrder:true,caseRemoved:true,importHoldRemoved:true,otherOwnerRetained:true,googleSimulated:true},null,2));
  }catch(error){await page.screenshot({path:path.join(config.artifacts,'failure.png'),animations:'disabled'});console.error((await page.locator('body').innerText()).slice(-1800));throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
