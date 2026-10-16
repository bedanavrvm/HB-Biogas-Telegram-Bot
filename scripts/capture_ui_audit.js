/* Capture original source scenes. Output is ignored synthetic evidence, not an approved baseline. */
'use strict';
const fs=require('node:fs');const path=require('node:path');const http=require('node:http');const crypto=require('node:crypto');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const target=path.resolve(root,process.argv[2]||'test-results/ui-audit');
if(!target.startsWith(path.join(root,'test-results')+path.sep))throw new Error('Output must be inside test-results.');
const manifest=JSON.parse(fs.readFileSync(path.join(target,'manifest.json'),'utf8'));
const sourceHashes=new Map(Object.values(manifest.comparisons).flatMap(item=>item.variants.flatMap(variant=>variant.sources)).map(item=>[item.path,item.sha256]));
function checkSources(){for(const [source,expected]of sourceHashes){let content=fs.readFileSync(path.join(root,source));if(['.py','.html','.js','.css','.json','.svg','.txt'].includes(path.extname(source)))content=Buffer.from(content.toString('utf8').replace(/\r\n/g,'\n'));const actual=crypto.createHash('sha256').update(content).digest('hex');if(actual!==expected)throw new Error('Source changed since export: '+source+'. Export again before capture.');}}
checkSources();
const chosenScenes=(process.env.UI_AUDIT_SCENES||'queue,filters,form').split(',');
const chosenStates=(process.env.UI_AUDIT_STATES||'one,empty,many,long,loading,error,denied').split(',');
const widths=(process.env.UI_AUDIT_WIDTHS||'360,390').split(',').map(Number);
const server=http.createServer((req,res)=>{
  const pathname=new URL(req.url,'http://localhost').pathname;
  const asset=manifest.assets[pathname];
  const scene=manifest.scenes.find(item=>pathname==='/'+item.filename);
  const file=asset?path.join(root,asset):scene?path.join(target,scene.filename):null;
  if(!file||!file.startsWith(root+path.sep)){res.writeHead(404).end();return;}
  const mime={'.js':'text/javascript','.css':'text/css','.png':'image/png','.svg':'image/svg+xml','.html':'text/html'}[path.extname(file)]||'application/octet-stream';
  res.setHeader('Content-Type',mime);res.end(fs.readFileSync(file));
});
function html(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base=`http://127.0.0.1:${server.address().port}`;
  const browser=await chromium.launch();const browserVersion=browser.version();const output=[];const cases=[];
  for(const scene of manifest.scenes.filter(item=>chosenScenes.includes(item.scene)&&chosenStates.includes(item.state)))for(const width of widths)for(const theme of ['light','dark'])cases.push({...scene,width,theme});
  let index=0;
  async function worker(){while(index<cases.length){const item=cases[index++];const page=await browser.newPage({viewport:{width:item.width,height:item.width===360?740:844},timezoneId:'Africa/Nairobi',reducedMotion:'reduce'});const errors=[];
    await page.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    await page.clock.setFixedTime(new Date('2026-10-16T06:00:00Z'));
    page.on('pageerror',error=>errors.push(error.message));
    try{
      await page.goto(base+'/'+item.filename,{waitUntil:'domcontentloaded'});
      await page.evaluate(theme=>window.postMessage({type:'ui-lab-theme',mode:theme},'*'),item.theme);
      await page.waitForTimeout(1100);
      const name=`${item.app}-${item.scene}-${item.state}-${item.width}-${item.theme}.png`;
      await page.screenshot({path:path.join(target,name),fullPage:true});
      const observations=await page.evaluate(patterns=>{
        const elements=[...document.querySelectorAll('h1,h2,label,input,select,button,article,.case-card,.case-row,.application-card,.farmer-card')].filter(node=>node.getClientRects().length).slice(0,250);
        const styleFields=['fontFamily','fontSize','fontWeight','lineHeight','paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginBottom','gap','borderRadius','boxShadow','color','backgroundColor'];
        const values={};for(const field of styleFields)values[field]=[...new Set(elements.map(node=>getComputedStyle(node)[field]))].sort();
        const targets=elements.filter(node=>node.matches('button,input,select')).map(node=>{const r=node.getBoundingClientRect();return{id:node.id,width:r.width,height:r.height};});
        const coverage=patterns.map(pattern=>{const nodes=[...document.querySelectorAll(pattern.selectors[window.UI_SCENE.config.app])];return{pattern:pattern.key,matched:nodes.length,visible:nodes.filter(node=>node.getClientRects().length).length};});
        return{values,targets,coverage,overflow:document.documentElement.scrollWidth>innerWidth,telegram:window.UI_SCENE.calls,gaps:[...new Set(window.UI_SCENE.gaps)],
          fontEvidence:{remoteFontsLoaded:[...document.fonts].filter(font=>font.status==='loaded').map(font=>font.family),remoteFontsBlocked:true,nativeVerified:false}};
      },manifest.patterns.filter(pattern=>pattern.scene===item.scene&&manifest.comparisons[pattern.key].variants.some(variant=>variant.id===item.app)));
      const comparisons=Object.entries(manifest.comparisons).filter(([,comparison])=>comparison.variants.some(variant=>variant.id===item.app&&variant.scene===item.scene));
      output.push({...item,source_fingerprints:Object.fromEntries(comparisons.map(([key])=>[key,manifest.patterns.find(pattern=>pattern.key===key).fingerprint])),screenshot:name,sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(target,name))).digest('hex'),errors,...observations});
      process.stdout.write(`Captured ${item.app}/${item.scene}/${item.state} ${item.width} ${item.theme}\n`);
    }catch(error){output.push({...item,error:error.message});}finally{await page.close();}
  }}
  try{await Promise.all([worker(),worker()]);}finally{await browser.close();server.close();}
  output.sort((a,b)=>(a.app+a.scene+a.state+a.width+a.theme).localeCompare(b.app+b.scene+b.state+b.width+b.theme));
  checkSources();
  const report={format:1,commit:manifest.commit,dirty_worktree:manifest.dirty_worktree,browser:'Chromium '+browserVersion,source_verified:true,captures:output,migration_authorized:false};
  fs.writeFileSync(path.join(target,'capture-report.json'),JSON.stringify(report,null,2));
  fs.writeFileSync(path.join(target,'index.html'),'<!doctype html><meta charset="utf-8"><title>Current UI audit — unapproved</title><style>body{font:14px system-ui;margin:16px}section{display:inline-block;vertical-align:top;margin:8px;width:390px;max-width:100%}img{max-width:100%;height:auto}pre{white-space:pre-wrap}</style><h1>Current UI audit — unapproved</h1><p>Synthetic data only. Remote fonts blocked; fallback captures are not final typography approval. Native behaviour unverified.</p>'+output.map(item=>`<section><h2>${html(item.app+' / '+item.scene)}</h2><p>${html(item.state+' · '+item.width+'px · '+item.theme)}</p>${item.screenshot?`<a href="${html(item.screenshot)}"><img src="${html(item.screenshot)}" alt="${html(item.app+' current source')}"></a>`:''}<pre>${html(item.error||[...new Set([...(item.gaps||[]),...(item.errors||[]),...(item.coverage||[]).filter(entry=>!entry.visible).map(entry=>'Not visible: '+entry.pattern)])].join('\n'))}</pre></section>`).join(''));
  console.log(`Saved ${output.length} captures. Source gaps and font limitations are explicit; no approvals or app changes.`);
  if(output.some(item=>item.error||(item.errors||[]).length)){
    console.error('Capture/runtime failures are recorded in capture-report.json. Unmodelled component coverage remains a separate review gap.');
    process.exitCode=1;
  }
})().catch(error=>{server.close();console.error(error.message);process.exitCode=1;});
