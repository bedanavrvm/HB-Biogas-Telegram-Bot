/* Actual Django/AG Grid review; synthetic fixtures and loopback transport only. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
  let input='';for await(const chunk of process.stdin)input+=chunk;
  const config=JSON.parse(input);assert.equal(new URL(config.origin).hostname,'localhost');
  fs.mkdirSync(config.artifacts,{recursive:true});
  const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
  page.setDefaultTimeout(20000);page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>new URL(route.request().url()).origin===config.origin?route.continue():route.abort());
  await page.setExtraHTTPHeaders({'X-Telegram-Init-Data':config.initData});
  await page.addInitScript(initData=>{window.Telegram={WebApp:{initData,ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{onClick(){},offClick(){},show(){},hide(){}},MainButton:{hide(){},offClick(){},onClick(){}}}};},config.initData);
  const idle=()=>page.waitForFunction(()=>!document.querySelector('[data-source-sheet="Eco-conserve"]').disabled);
  const shot=name=>page.screenshot({path:path.join(config.artifacts,name+'.png'),animations:'disabled'});
  const rowCell=(index,field)=>page.locator(`[data-review-grid] .ag-row[row-index="${index}"] [col-id="${field}"]`);
  async function reach(index,field){
    if(!await rowCell(index,field).count())await page.locator('[data-review-grid] .ag-body-horizontal-scroll-viewport').evaluate((node,end)=>{node.scrollLeft=end?node.scrollWidth:0;},['deposit_paid_hbg','legacy_deposit_paid_jbl','invoice_amount'].includes(field));
    await rowCell(index,field).waitFor();
  }
  async function edit(index,field,value){
    await reach(index,field);
    const cell=rowCell(index,field);await cell.scrollIntoViewIfNeeded();await cell.dblclick();
    const input=cell.locator('input');await input.fill(value);await input.press('Enter');
    await page.getByRole('button',{name:'Save corrections',exact:true}).click();await idle();
  }
  try{
    await page.goto(config.origin+'/portal/s/legacy/');
    await page.locator(`[name=group_id] option[value="${config.group}"]`).waitFor({state:'attached'});await idle();
    await page.getByRole('button',{name:'Eco-conserve',exact:true}).click();await idle();
    await page.locator('[name=group_id]').selectOption(config.group);await page.locator('[name=namespace]').fill('synthetic-review');
    await page.locator('[data-upload-form] [name=file]').setInputFiles(config.workbook);await page.getByRole('button',{name:'Upload and preview mapping',exact:true}).click();
    await page.locator('[data-action=stage]:visible').waitFor();await idle();await page.locator('[data-action=stage]').click();await idle();
    await page.locator('[data-review-grid] .ag-row').first().waitFor();
    assert.equal(await page.locator('.ag-header-cell[col-id="source_row"]').evaluate(node=>node.getBoundingClientRect().width),32);
    assert.equal(await rowCell(1,'national_id').evaluate(node=>node.classList.contains('farmup-cell-invalid')),true);
    await page.getByRole('button',{name:'Cards',exact:true}).click();await idle();
    assert.equal(await page.locator('[data-rows] .legacy-card-blocked').count(),1);
    assert.ok(await page.locator('[data-rows] .legacy-card-warning').count()>=3);
    const match=page.locator('[data-rows] article').nth(1);
    assert.match(await match.innerText(),/22222222 matches JBL-/);
    assert.match(await match.innerText(),/EXISTING HOUSEHOLD/);
    assert.match(await match.innerText(),/254700000002/);
    assert.match(await page.locator('[data-rows] article').nth(2).innerText(),/source row 5: DUPLICATE B/);
    await shot('01-cards-explain-issues');
    await page.getByRole('button',{name:'Table',exact:true}).click();await idle();
    await reach(0,'deposit_paid_hbg');await rowCell(0,'deposit_paid_hbg').scrollIntoViewIfNeeded();
    assert.equal(await rowCell(0,'deposit_paid_hbg').evaluate(node=>node.classList.contains('farmup-cell-invalid')),true);
    await shot('02-invalid-money-highlight');
    await edit(0,'deposit_paid_hbg','5000');
    assert.equal(await rowCell(0,'deposit_paid_hbg').innerText(),'5000');
    assert.equal(await rowCell(0,'deposit_paid_hbg').evaluate(node=>node.classList.contains('farmup-cell-invalid')),false);
    assert.equal(await rowCell(0,'deposit_paid_hbg').evaluate(node=>node.classList.contains('farmup-cell-edited')),true);
    await edit(1,'national_id','44444444');
    await edit(3,'national_id','55555555');
    await edit(4,'primary_phone','712000006');
    await page.locator('[data-action=select_page]').click();await idle();
    await edit(0,'customer_name','CONFIRMED NAME');
    assert.equal(await page.locator('[data-review-grid] .ag-row[row-index="0"] input[type=checkbox]').isChecked(),false);
    const upload=await page.locator('[data-resume]').inputValue();
    await page.reload();await page.locator(`[data-resume] option[value="${upload}"]`).waitFor({state:'attached'});await idle();
    await page.locator('[data-resume]').selectOption(upload);await idle();
    assert.equal(await rowCell(0,'customer_name').innerText(),'CONFIRMED NAME');
    await page.locator('[data-review-grid] .ag-row[row-index="0"] [data-row-open]').click();
    await page.locator('[data-row-dialog][open]').waitFor();
    assert.match(await page.locator('[data-row-dialog]').innerText(),/Original: bad/);
    await shot('03-saved-original-versus-corrected');await page.locator('[data-row-dialog] button[value=done]').click();
    for(const width of [320,390]){
      await page.setViewportSize({width,height:900});await page.getByRole('button',{name:'Cards',exact:true}).click();await idle();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await shot('04-corrected-cards-'+width);
      await page.getByRole('button',{name:'Table',exact:true}).click();await idle();
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(config.artifacts,'observations.json'),JSON.stringify({rowWidth:32,blockedAndWarningCards:true,identityValues:true,sourceDuplicates:true,editedFields:true,originalRetained:true,reapproval:true,reload:true,widths:[320,390,1280],scriptErrors:errors},null,2));
  }catch(error){await shot('failure');console.error('Feedback:',await page.locator('[data-feedback]').innerText());console.error('Grid rows:',await page.locator('[data-review-grid] .ag-row').evaluateAll(rows=>rows.map(row=>({index:row.getAttribute('row-index'),columns:[...row.querySelectorAll('[col-id]')].map(cell=>cell.getAttribute('col-id'))}))));throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
