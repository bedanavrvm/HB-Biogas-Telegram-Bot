/* Bounded historical import. No credentials or customer values enter browser storage. */
(() => {
  'use strict';
  const root=document.getElementById('complaint-legacy'),find=s=>root.querySelector(s),channel=document.body.dataset.channel;
  const group=document.body.dataset.group, native=channel==='browser';
  const prefix=native?`/api/staff/complaints/operations/v1/groups/${encodeURIComponent(group)}/legacy-import/`:'/api/complaints/legacy-import/';
  const telegram=window.parent!==window?window.parent.Telegram?.WebApp:window.Telegram?.WebApp;
  let active=null,rows=[],offset=0,total=0,busy=false,running=false,grid=null,mode='table',settings=null,lastError='';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label=k=>k.replace(/_/g,' ').replace(/^./,c=>c.toUpperCase());
  function feedback(text,error=false){find('[data-feedback]').textContent=text;find('.import-feedback').dataset.error=String(error);}
  async function request(path='',body){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
    try{
      const headers={Accept:'application/json','X-Request-ID':crypto.randomUUID()};
      if(!native)headers['X-Telegram-Init-Data']=telegram?.initData||'';
      if(body){
        headers['Content-Type']='application/json';
        if(native){const session=await fetch('/api/staff/auth/v1/session/',{credentials:'same-origin',signal:controller.signal});const auth=await session.json();if(!session.ok||!auth.is_authenticated)throw new Error('Your session ended. Sign in again to resume.');headers['X-CSRFToken']=auth.csrf_token;}
        body={...body,...(!native?{group_id:group}:{}),...(active?{revision:active.revision}:{})};
      }
      const query=!native?`${path.includes('?')?'&':'?'}group_id=${encodeURIComponent(group)}`:'';
      const response=await fetch(prefix+path+query,{method:body?'POST':'GET',headers,credentials:native?'same-origin':'omit',redirect:'error',referrerPolicy:'no-referrer',cache:'no-store',signal:controller.signal,...(body?{body:JSON.stringify(body)}:{})});
      if(path==='template/') {if(!response.ok)throw new Error('Template could not be loaded. Check your Complaints access.');return response.blob();}
      const data=await response.json();if(!response.ok)throw new Error(data.error||data.message||'The step could not be confirmed. Refresh saved progress.');
      if(data.upload)active=data.upload;
      return data;
    }finally{clearTimeout(timer);}
  }
  const command=(action,body={})=>request(`${active.id}/${action}/`,body);
  async function index(){settings=await request();find('[data-workspace]').textContent=settings.workspace;find('[data-saved]').innerHTML='<option value="">Choose an import</option>'+settings.uploads.map(u=>`<option value="${u.id}">${esc(u.namespace)} · ${u.committed}/${u.total} imported</option>`).join('');if(active)find('[data-saved]').value=active.id;else feedback('Upload a workbook or choose a saved import to continue.');}
  function render(){
    root.querySelectorAll('button,input,select').forEach(n=>{if(!n.closest('dialog'))n.disabled=busy;});find('[data-action=pause]').disabled=false;
    root.querySelectorAll('[data-row-select]').forEach(box=>{const row=rows.find(r=>String(r.id)===box.dataset.rowSelect);box.disabled=busy||!row||!reviewable(row);});
    find('[data-action=pause]').hidden=!busy;
    const phase=active?.phase,processing=['staging','committing','publishing','backing_up','clearing','deleting_tests'].includes(phase);
    const actions={refresh:true,resume:processing,stage:phase==='mapping',cutover:['ready','backing_up','clearing','deleting_tests'].includes(phase)&&!active.cutover_complete,
      commit:phase==='ready'&&active.cutover_complete&&(active?.selected>0||rows.some(r=>r.approved&&!r.committed)),
      publish:phase==='ready'&&active.workspace_awaiting_sync>0&&settings?.projection_enabled,discard:Boolean(active)&&!active.committed&&!processing};
    for(const [name,show] of Object.entries(actions))find(`[data-action=${name}]`).hidden=!show;
    find('[data-review]').hidden=!active||!active.total;find('[data-mapping]').hidden=!active?.state?.bindings;
    if(active){
      find('[data-source]').open=phase==='uploading';
      find('[data-progress]').max=Math.max(active.total,1);find('[data-progress]').value=active.committed;
      feedback(lastError||active.state.sync_error||`${active.filename} · ${phase} · ${active.total} staged · ${active.committed} imported · ${active.selected} approved · ${active.synced}/${active.committed} verified in Sheet · ${active.workspace_awaiting_sync} awaiting sync across workspace`,Boolean(lastError||active.state.sync_error));
      find('[data-mapping]').open=phase==='mapping';find('[data-mapping-list]').innerHTML=Object.entries(active.state.bindings||{}).map(([col,key])=>`<div><strong>${esc(active.state.headers[col])}</strong><p>${esc(label(key))}</p></div>`).join('');
    }
    find('[data-action=previous]').disabled=busy||offset===0;find('[data-action=next]').disabled=busy||offset+50>=total;
    root.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
    grid?.refreshCells({force:true});
  }
  const reviewable=row=>!row.committed&&row.proposal.status!=='blocked'&&active.phase==='ready';
  function details(row){
    const fields=row.proposal.fields, keys=[...new Set([...Object.keys(row.values),...Object.keys(fields)])];
    find('[data-detail-copy]').innerHTML=`<p>Source row ${row.source_row} · ${esc(row.reference||row.proposal.status)}</p><p>${esc([...row.proposal.issues,...row.proposal.warnings,row.proposal.commit_error].filter(Boolean).join('; '))}</p><table><thead><tr><th>Field</th><th>Original</th><th>Proposed</th></tr></thead><tbody>${keys.map(k=>`<tr><th>${esc(label(k))}</th><td>${esc(row.values[k])}</td><td>${esc(fields[k])}</td></tr>`).join('')}</tbody></table>`;
    find('[data-detail]').showModal();
  }
  function renderRows(){
    find('[data-grid]').hidden=mode!=='table';find('[data-cards]').hidden=mode!=='cards';
    if(mode==='cards')find('[data-cards]').innerHTML=rows.map(r=>`<article class="import-row-card"><label><input type="checkbox" data-row-select="${r.id}" ${r.approved?'checked':''} ${busy||!reviewable(r)?'disabled':''}>Row ${r.source_row} · ${esc(r.values.customer_name||'Name not recorded')}</label><p>${esc(r.proposal.fields.status)} · ${esc(r.proposal.fields.date_reported?.slice(0,10))} · ${esc(r.reference||r.proposal.status)}</p><p>${esc([...r.proposal.issues,...r.proposal.warnings,r.proposal.commit_error].filter(Boolean).join('; '))}</p><button type="button" data-row-detail="${r.id}">Compare source values</button></article>`).join('');
    if(mode==='table'&&!grid){
      if(!window.agGrid){mode='cards';feedback('Table assets could not load. Cards remain available.',true);renderRows();return;}
      window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
      const source=(key,name,width)=>({colId:key,headerName:name,width,valueGetter:p=>p.data.values[key]||''});
      grid=window.agGrid.createGrid(find('[data-grid]'),{theme:'legacy',rowHeight:32,headerHeight:32,rowData:[],getRowId:p=>String(p.data.id),suppressMovableColumns:true,
        defaultColDef:{resizable:true,sortable:true,filter:'agTextColumnFilter',width:150},columnDefs:[
          {colId:'approval',headerName:'✓',width:48,pinned:'left',filter:false,sortable:false,cellRenderer:p=>{const box=document.createElement('input');box.type='checkbox';box.checked=p.data.approved;box.disabled=busy||!reviewable(p.data);box.setAttribute('aria-label',`Approve source row ${p.data.source_row}`);box.onchange=()=>{p.data.approved=box.checked;run(async()=>{await saveSelection();renderRows();});};return box;}},
          {field:'source_row',headerName:'Row',width:68,pinned:'left',filter:false,cellRenderer:p=>{const b=document.createElement('button');b.textContent=p.value;b.setAttribute('aria-label',`Compare source row ${p.value}`);b.onclick=()=>details(p.data);return b;}},
          source('customer_name','Customer',190),source('status','Original status',140),{headerName:'Status',width:100,valueGetter:p=>p.data.proposal.fields.status},
          source('date_reported','Original reported date',170),{headerName:'Reported date',width:140,valueGetter:p=>p.data.proposal.fields.date_reported?.slice(0,10)},
          {headerName:'Review',width:100,valueGetter:p=>p.data.committed?'IMPORTED':p.data.proposal.status.toUpperCase()},
          {headerName:'Issues / warnings',width:340,valueGetter:p=>[...p.data.proposal.issues,...p.data.proposal.warnings,p.data.proposal.commit_error].filter(Boolean).join('; ')},
          source('customer_phone','Primary phone',150),source('customer_id','National ID',130),source('complaint_description','Description',300),
          {field:'reference',headerName:'Complaint reference',width:150}],rowClassRules:{'import-row-blocked':p=>p.data.proposal.status==='blocked','import-row-warning':p=>p.data.proposal.status==='warning'}});
    }
    grid?.setGridOption('rowData',rows);
    find('[data-page]').textContent=total?`${offset+1}–${Math.min(offset+50,total)} of ${total}`:'No rows';
  }
  async function refresh(){if(!active)return;const data=await request(`${active.id}/?offset=${offset}&filter=${find('[data-filter]').value}`);rows=data.rows;total=data.total;renderRows();}
  async function saveSelection(){if(active?.phase==='ready'&&rows.length)await command('select',{rows:rows.filter(r=>!r.committed).map(r=>({id:r.id,approved:r.approved}))});}
  async function run(task){if(busy)return;busy=true;lastError='';render();try{await task();}catch(error){running=false;try{await refresh();}catch{}lastError=active?.state?.sync_error||(error.name==='AbortError'?'Step outcome unknown. Refresh saved progress before retrying; saved cases and source bytes are retained.':error.message);feedback(lastError,true);}finally{busy=false;render();}}
  async function process(){
    running=true;
    while(running&&!document.hidden){
      if(['staging','committing','publishing','backing_up','clearing','deleting_tests'].includes(active.phase)){
        await command('advance');await refresh();render();
        if(active.phase==='committing'&&active.workspace_awaiting_sync>0&&settings?.projection_enabled){await command('sync');await refresh();render();}
      }else if(active.phase==='ready'&&active.cutover_complete&&active.workspace_awaiting_sync>0&&settings?.projection_enabled){await command('publish');}
      else break;
    }
    running=false;await index();
  }
  async function confirm(title,copy){const dialog=find('[data-confirm]');find('[data-confirm-title]').textContent=title;find('[data-confirm-copy]').textContent=copy;dialog.showModal();return new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true}));}
  find('[data-saved]').onchange=()=>run(async()=>{const id=find('[data-saved]').value;if(!id)return;await saveSelection();active={id};offset=0;await refresh();});
  find('[data-filter]').onchange=()=>run(async()=>{await saveSelection();offset=0;await refresh();});
  find('[data-upload]').onsubmit=event=>{event.preventDefault();run(async()=>{
    await saveSelection();const file=find('[name=file]').files[0];if(!file||file.size>20*1024*1024)throw new Error('Choose an XLSX up to 20 MiB.');
    const bytes=await file.arrayBuffer(),digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
    await request('',{filename:file.name,size:file.size,digest,namespace:find('[name=namespace]').value,source_sheet:find('[name=source_sheet]').value});
    const received=new Set(active.chunks);running=true;
    for(let start=0,position=0;start<file.size;start+=512*1024,position++){
      if(!running||document.hidden){feedback('Upload paused. Re-select the same workbook to resume.');return;}
      if(!received.has(position)){const part=new Uint8Array(bytes.slice(start,start+512*1024));let binary='';for(let n=0;n<part.length;n+=8192)binary+=String.fromCharCode(...part.subarray(n,n+8192));await command('chunk',{position,content:btoa(binary)});}
      feedback(`Uploading ${Math.min(start+512*1024,file.size)} / ${file.size} bytes`);
    }
    running=false;await command('prepare');offset=0;await refresh();await index();
  });};
  root.addEventListener('change',event=>{const id=event.target.dataset.rowSelect;if(id){const row=rows.find(r=>String(r.id)===id);if(row){row.approved=event.target.checked;run(async()=>{await saveSelection();renderRows();});}}});
  root.addEventListener('click',event=>{
    const detail=event.target.closest('[data-row-detail]')?.dataset.rowDetail;if(detail){details(rows.find(r=>String(r.id)===detail));return;}
    const layout=event.target.closest('[data-mode]')?.dataset.mode;if(layout){run(async()=>{mode=layout;renderRows();});return;}
    const action=event.target.closest('[data-action]')?.dataset.action;if(!action)return;
    if(action==='pause'){running=false;feedback('Pausing after the current saved step…');return;}
    run(async()=>{
      if(action==='refresh'){await saveSelection();await refresh();await index();}
      else if(action==='stage'){await command('stage');await process();}
      else if(action==='resume')await process();
      else if(action==='previous'||action==='next'){await saveSelection();offset=Math.max(0,offset+(action==='next'?50:-50));await refresh();}
      else if(action==='approve_page'){const displayed=[];if(mode==='table'&&grid)grid.forEachNodeAfterFilterAndSort(n=>displayed.push(n.data));else displayed.push(...rows);displayed.filter(reviewable).forEach(r=>r.approved=true);await saveSelection();await refresh();}
      else if(action==='approve_all'||action==='clear'){await saveSelection();await command('select',{all:true,approved:action==='approve_all'});await refresh();}
      else if(action==='cutover'){
        await saveSelection();const result=await command('cutover-preview'),p=result.preview;
        if(await confirm('Replace test Complaints register',`Delete ${p.test_cases} existing test cases and their local history in ${settings.workspace}; retain ${p.retained_imports} already imported complaints and this source workbook. Back up and clear ${p.name} (${p.spreadsheet}) below header row ${p.header_row}, then write saved complaints from row ${p.header_row+1}. Other worksheets and Drive files are retained. Confirm only after pausing manual edits to this worksheet.`)){
          await command('cutover-confirm',{token:p.token,manual_edits_paused:true});await process();
        }
      }
      else if(action==='commit'){await saveSelection();if(await confirm('Import approved historical cases',`Save ${active.selected} approved rows in ${settings.workspace} and automatically sync saved cases to ${settings.sheet_name}? Status and Date Reported come from your cleaned columns. Sync runs in FIFO batches; progress is retained if you close this page.`)){await command('commit');await process();}}
      else if(action==='publish'){await command('publish');await process();}
      else if(action==='discard'&&await confirm('Discard this upload','Remove only this uncommitted source version? Imported case provenance is retained.')){await command('discard');active=null;rows=[];await index();}
    });
  });
  find('[data-template]').onclick=()=>run(async()=>{const blob=await request('template/'),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='Complaints - Legacy Import Template.xlsx';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  const back=find('[data-back]');back.href=native?`/staff/app/complaints/?workspace=${encodeURIComponent(group)}`:`/complaints/?group_id=${encodeURIComponent(group)}`;
  back.onclick=event=>{if(window.frameElement){event.preventDefault();window.frameElement.remove();}};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)running=false;});
  if(!group)feedback('Open Legacy import from the required Complaints workspace.',true);else run(index);
})();
