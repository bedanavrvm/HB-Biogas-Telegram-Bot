/* Durable server checkpoints; only explicit review actions may commit or replace. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let root,active,offset=0,pageTotal=0,current=[],running=false,busy=false,superuser=false,lastNotice='';
  const node = selector => root.querySelector(selector);
  const feedback = text => {node('[data-feedback]').textContent=text;};
  async function call(path='',body,options={}) {
    const response=await window.PortalMiniAppApi.apiFetch('/legacy/uploads/'+path,body===undefined?{}:{method:'POST',body:JSON.stringify({...body,revision:active?.revision}),...options},window.Telegram?.WebApp);
    if(!response.ok||!response.data?.ok)throw new Error(response.data?.legacy_detail||response.data?.error||'Request outcome unknown. Refresh saved progress before retrying.');
    if(response.data.upload)active=response.data.upload;
    return response.data;
  }
  const command=(action,body={})=>call(`${active.id}/${action}/`,body);
  function renderState() {
    if(!active?.state){root.querySelectorAll('[data-action]').forEach(button=>{button.hidden=true;});node('[data-mapping]').hidden=true;return;}
    node('[data-mapping]').hidden=false;
    node('[data-source]').open=active.phase==='uploading';
    feedback(lastNotice || `${active.filename} · ${active.phase} · ${active.total} staged · ${active.committed} imported · ${active.selected} approved${active.frozen?' · Portal owner held for cutover':''}`);
    const processing=active.state.projection;
    node('[data-progress]').max=Math.max(processing?.count||active.total,1);node('[data-progress]').value=processing?.offset||active.committed;
    const available={stage:active.phase==='mapping',cleanup:superuser&&['ready','deleting'].includes(active.phase)&&!active.state.cleanup_complete,commit:active.phase==='ready'&&active.state.cleanup_complete,
      project:active.phase==='ready'&&active.committed===active.total&&active.total>0,restart_projection:['backup','projecting','verifying'].includes(active.phase),cancel_preview:active.frozen&&!active.state.cleanup_started&&active.phase==='ready',discard:!active.frozen&&active.committed===0};
    for(const [name,enabled] of Object.entries(available)){const button=node(`[data-action="${name}"]`);button.hidden=!enabled;button.disabled=busy||!enabled;}
    for(const name of ["refresh","select_page","select_all","unselect_all","previous","next"]){node(`[data-action="${name}"]`).hidden=false;}
    for(const name of ['refresh','select_page','select_all','unselect_all','previous','next'])node(`[data-action="${name}"]`).disabled=busy||(name==='previous'&&offset===0)||(name==='next'&&offset+50>=pageTotal);
    node('[data-filter]').disabled=busy;node('[data-resume]').disabled=busy;
    for(const name of ['select_page','select_all','unselect_all'])node(`[data-action="${name}"]`).hidden=!['ready','committing'].includes(active.phase);
    node('[data-action="pause"]').hidden=!busy;
    node('[data-action="resume"]').hidden=!['staging','deleting','committing','backup','projecting','verifying','replacing','readback'].includes(active.phase);
    node('[data-action="resume"]').disabled=busy;
    const bindings=active.state.bindings||{};node('[data-mapping-rows]').innerHTML=Object.entries(bindings).map(([i,field])=>`<div><strong>${esc(active.state.headers[i])}</strong><p>${esc(field)}</p></div>`).join('');
    node('[data-mapping]').open=active.phase==='mapping';
  }
  async function refresh() {
    if(!active)return;
    const data=await call(`${active.id}/?offset=${offset}&filter=${encodeURIComponent(node('[data-filter]').value)}`);current=data.rows;pageTotal=data.total;
    node('[data-rows]').innerHTML=current.map(r=>`<article class="case360-section"><label class="legacy-row-select"><input type="checkbox" data-select="${r.id}" ${r.approved?'checked':''} ${r.committed?'disabled':''}>Row ${r.source_row} · ${esc(r.name)} ${r.committed?'· Imported':''}</label><p>${esc(r.proposal.state)} · ${esc((r.proposal.issues||[]).join('; '))}</p>${r.proposal.commit_error?`<p role="alert">${esc(r.proposal.commit_error)}</p>`:''}<details><summary>Source facts and history</summary><div class="case360-grid">${Object.entries(r.source_values||{}).filter(([,v])=>v!==''&&v!==null).map(([k,v])=>`<div><strong>${esc(k)}</strong><p>${esc(v)}</p></div>`).join('')}</div></details>${!r.committed?`<details><summary>Link or separate unit${r.identity_collision?' - identity match needs review':' (optional)'}</summary><label>Explicit existing case ID<input data-match="${r.id}" value="${esc(r.reconciliation.existing_case_id||'')}"></label><label>Link / separate-unit explanation<input data-note="${r.id}" value="${esc(r.reconciliation.note||'')}"></label></details>`:''}</article>`).join('');
    node('[data-page]').textContent=`${data.total?offset+1:0}–${offset+current.length} of ${data.total}`;
    node('[data-action="previous"]').disabled=offset===0;node('[data-action="next"]').disabled=offset+50>=data.total;renderState();
  }
  async function confirm(title,text,warning) {
    const dialog=node('[data-confirm]');node('[data-confirm-title]').textContent=title;node('[data-confirm-text]').textContent=text;node('[data-confirm-warning]').textContent=warning;
    return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});
  }
  async function process() {
    running=true;
    while(running&&!document.hidden&&['staging','deleting','committing','backup','projecting','verifying','replacing','readback'].includes(active.phase)) {
      const data=await command('advance');renderState();
      if(data.wait_seconds)await new Promise(resolve=>setTimeout(resolve,Math.ceil(data.wait_seconds*1000)));
      if(data.results?.some(r=>!r.ok)){await refresh();lastNotice=`Some rows were held: ${[...new Set(data.results.filter(r=>!r.ok).map(r=>r.error))].join(' ')}`;feedback(lastNotice);running=false;}
    }
    running=false;await refresh();
  }
  async function run(task) {
    if(busy)return;busy=true;lastNotice='';if(active)renderState();
    try{await task();}catch(error){running=false;try{if(active)await refresh();}catch{}lastNotice=error.message;feedback(lastNotice);}finally{busy=false;renderState();}
  }
  async function selection(rows) {
    if(!rows.length||!['ready','committing'].includes(active.phase))return;
    await command('select',{rows:rows.map(r=>({id:r.id,approved:node(`[data-select="${r.id}"]`).checked,
      existing_case_id:node(`[data-match="${r.id}"]`)?.value||'',note:node(`[data-note="${r.id}"]`)?.value||''}))});
  }
  async function init() {
    root=document.getElementById('legacy-data-workspace');if(!root||root.dataset.ready)return;root.dataset.ready='true';
    const index=await call();superuser=index.superuser;
    node('[name="group_id"]').innerHTML='<option value="">Choose owner</option>'+index.groups.map(g=>`<option value="${g.id}">${esc(g.label)}</option>`).join('');
    node('[data-resume]').innerHTML='<option value="">Choose saved import</option>'+index.uploads.map(u=>`<option value="${u.id}">${esc(u.namespace)} · ${esc(u.phase)}</option>`).join('');
    node('[data-resume]').onchange=()=>run(async()=>{if(!node('[data-resume]').value)return;active={id:node('[data-resume]').value};offset=0;await refresh();});
    node('[data-upload-form]').onsubmit=event=>{event.preventDefault();run(async()=>{
      const file=node('[name="file"]').files[0];if(!file||file.size>20*1024*1024)throw new Error('Select one XLSX up to 20 MiB.');
      feedback('Reading source checksum…');const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).map(v=>v.toString(16).padStart(2,'0')).join('');
      await call('',{group_id:node('[name="group_id"]').value,namespace:node('[name="namespace"]').value,filename:file.name,size:file.size,digest});
      const existing=new Set(active.chunks);let position=0;running=true;
      for(let start=0;start<file.size;start+=512*1024,position++) {
        if(!running||document.hidden){feedback('Upload paused. Re-select the same workbook to resume saved chunks.');return;}
        if(!existing.has(position)) {
          const response=await window.PortalMiniAppApi.apiFetch(`/legacy/uploads/${active.id}/chunk/?position=${position}`,{method:'POST',body:file.slice(start,start+512*1024),headers:{'Content-Type':'application/octet-stream'}},window.Telegram?.WebApp);
          if(!response.ok||!response.data?.ok)throw new Error(response.data?.error||'Chunk response lost. Re-select the same file to resume.');
          active=response.data.upload;
        }
        node('[data-progress]').max=file.size;node('[data-progress]').value=Math.min(start+512*1024,file.size);feedback(`Uploaded ${Math.min(start+512*1024,file.size)} / ${file.size} bytes`);
      }
      running=false;await command('prepare');offset=0;await refresh();
    });};
    node('[data-filter]').onchange=()=>run(async()=>{if(active)await selection(current.filter(r=>!r.committed));offset=0;await refresh();});
    root.addEventListener('click',event=>{
      const action=event.target.closest('[data-action]')?.dataset.action;if(!action)return;
      if(action==='pause'){running=false;feedback('Pausing after the current saved chunk.');return;}
      run(async()=>{
        if(!active)throw new Error('Choose or upload a workbook first.');
        if(action==='refresh')await refresh();
        else if(action==='resume')await process();
        else if(action==='stage'){await command('stage');await process();}
        else if(action==='previous'||action==='next'){await selection(current.filter(r=>!r.committed));offset=Math.max(0,offset+(action==='previous'?-50:50));await refresh();}
        else if(action==='select_page'){current.filter(r=>!r.committed).forEach(r=>{node(`[data-select="${r.id}"]`).checked=true;});await selection(current.filter(r=>!r.committed));await refresh();}
        else if(action==='select_all'||action==='unselect_all'){await command('select',{all:true,approved:action==='select_all'});await refresh();}
        else if(action==='commit'){await selection(current.filter(r=>!r.committed));if(await confirm('Import approved records',`Import the saved selection (${active.selected} approved rows)?`,'Historical gaps remain unknown. Sheet publication stays held.')){await command('commit');await process();}}
        else if(action==='cleanup'){
          running=true;let result;do{result=await command('cleanup_preview');renderState();}while(!result.review.complete&&running&&!document.hidden);running=false;
          if(result.review.complete&&await confirm('Delete Portal test data',`Delete all ${result.review.count} Portal test cases for this owner and the disclosed dependent records?`,'Impact: '+result.review.impact.map(i=>`${i.category}: ${i.count} ${i.model}`).join('; ')+'. Eco-conserve and Master Data Sheets are not deleted. The owner remains held until cutover finishes.')){await command('cleanup_confirm',{token:result.review.token});await process();}
        }
        else if(action==='project'){
          const result=await command('projection_preview');await refresh();
          if(await confirm('Replace Master Data',`${result.preview.tab} · ${result.preview.spreadsheet}: replace all data rows with ${result.preview.rows} imported cases.`,'Pause manual Master Data edits now. Unmatched old rows will be removed. Headers and formatting stay; Eco-conserve is untouched.')){await command('projection_confirm',{manual_edits_paused:true});await process();}
        }
        else if(action==='discard'){if(await confirm('Discard upload','Remove this uncommitted staging version?','Existing cases and other versions remain.')){await command('discard');await refresh();}}
        else if(action==='restart_projection'){await command('restart_projection');await refresh();}
        else if(action==='cancel_preview'){await command('cancel_preview');await refresh();}
      });
    });
    renderState();
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)running=false;});
  window.PortalLegacyImporter={init};
})();
