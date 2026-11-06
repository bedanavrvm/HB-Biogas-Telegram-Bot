/* Durable server checkpoints; only explicit review actions may commit or replace. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let root,active,offset=0,pageTotal=0,current=[],running=false,busy=false,superuser=false,lastNotice='';
  let reviewMode='table',gridApi=null,gridAssets=null,gridColumns='';
  let selectedSheet='Master Data',uploads=[];
  try{reviewMode=sessionStorage.getItem('portal-legacy-review-mode')==='cards'?'cards':'table';}catch{}
  try{if(sessionStorage.getItem('portal-legacy-source-sheet')==='Eco-conserve')selectedSheet='Eco-conserve';}catch{}
  const node = selector => root.querySelector(selector);
  const feedback = text => {node('[data-feedback]').textContent=text;};
  async function call(path='',body,options={}) {
    const response=await window.PortalMiniAppApi.apiFetch('/legacy/uploads/'+path,body===undefined?{}:{method:'POST',body:JSON.stringify({...body,revision:active?.revision}),...options},window.Telegram?.WebApp);
    if(!response.ok||!response.data?.ok)throw new Error(response.data?.legacy_detail||response.data?.error||'Request outcome unknown. Refresh saved progress before retrying.');
    if(response.data.upload){active=response.data.upload;uploads=uploads.filter(u=>u.id!==active.id);uploads.unshift(active);renderSavedImports();node('[name="group_id"]').value=active.group_id;}
    return response.data;
  }
  const command=(action,body={})=>call(`${active.id}/${action}/`,{...body,source_sheet:active.source_sheet});
  function renderSavedImports(){
    node('[data-resume]').innerHTML='<option value="">Choose saved '+esc(selectedSheet)+' import</option>'+uploads.filter(u=>u.source_sheet===selectedSheet).map(u=>`<option value="${u.id}">${esc(u.namespace)} · ${esc(u.phase)}</option>`).join('');
    if(active)node('[data-resume]').value=active.id;
  }
  async function loadIndex(){
    const owner=node('[name="group_id"]').value;
    const index=await call('?source_sheet='+encodeURIComponent(selectedSheet));superuser=index.superuser;uploads=index.uploads;
    node('[name="group_id"]').innerHTML='<option value="">Choose owner</option>'+index.groups.map(g=>`<option value="${g.id}">${esc(g.label)}</option>`).join('');
    if(index.groups.some(group=>group.id===owner))node('[name="group_id"]').value=owner;
    renderSavedImports();
  }
  const reviewable=row=>!row.committed&&row.proposal.review_status!=='blocked'&&['ready','committing'].includes(active?.phase);
  const editable=row=>!busy&&!row.committed&&active?.phase==='ready';
  const human=value=>({national_id:'National ID',deposit_paid_hbg:'Deposit paid to HB',legacy_deposit_paid_jbl:'Deposit paid to JBL'}[value]||String(value||'').replace(/^legacy:/,'Historical: ').replace(/_/g,' ').replace(/^./,c=>c.toUpperCase()));
  function identityIssues(row){
    if(!row.identity_collision)return [];
    const identity=row.source_values.national_id;
    return [...(row.existing_cases||[]).map(match=>`National ID ${identity} matches ${match.reference}: ${match.name}; primary phone ${match.primary_phone||'not recorded'}${match.partner?' · '+match.partner:''}. This row: ${row.name}; primary phone ${row.source_values.primary_phone||'not recorded'}.`),
      ...(row.duplicate_rows||[]).map(match=>`National ID ${identity} is also on source row ${match.source_row}: ${match.name}.`),
      'Confirm whether these are the same case or separate units. Keep a correct National ID; use the link/separate-unit explanation.'];
  }
  const issueList=row=>[...(row.proposal.issues||[]),row.proposal.commit_error,...identityIssues(row)].filter(Boolean).map(message=>{
    const field=message.split(':',1)[0];
    return Object.hasOwn(row.source_values,field)?`${human(field)} “${row.source_values[field]||'(blank)'}”: ${message.slice(field.length+1).trim()}`:message;
  });
  const issues=row=>issueList(row).join('; ');
  const fieldIssues=(row,field)=>row.field_issues?.[field]||[];
  const fieldEdited=(row,field)=>String(row.source_values[field]??'')!==String(row.original_values?.[field]??row.source_values[field]??'');
  const pendingEdits=()=>current.some(row=>Object.keys(row._edits||{}).length);
  const reviewClass=row=>row.proposal.review_status==='blocked'?'blocked':issues(row)?'warning':'ready';
  function rowCard(row){
    const disabled=busy||!reviewable(row);
    const state=reviewClass(row),notes=issueList(row);
    return `<article class="case360-section legacy-review-card legacy-card-${state}" data-review-row="${row.id}"><label class="legacy-row-select"><input type="checkbox" data-select="${row.id}" ${row.approved?'checked':''} ${disabled?'disabled':''}>Row ${row.source_row} · ${esc(row.name)} ${row.committed?'· Imported':''}</label><p><strong class="legacy-review-label">${state==='blocked'?'Blocked':state==='warning'?'Needs review':'Ready'}</strong> · ${esc(human(row.proposal.state))}</p>${notes.length?`<ul class="legacy-review-issues">${notes.map(note=>`<li>${esc(note)}</li>`).join('')}</ul>`:''}<details><summary>Source facts, corrections and history</summary><div class="case360-grid">${Object.entries(row.source_values||{}).filter(([,v])=>v!==''&&v!==null).map(([k,v])=>`<div class="${fieldIssues(row,k).length?'legacy-field-issue':''} ${fieldEdited(row,k)?'legacy-field-edited':''}"><strong>${esc(human(k))}${fieldIssues(row,k).length?' ⚠':''}</strong><p>${esc(v)}</p>${fieldIssues(row,k).map(message=>`<small>${esc(message)}</small>`).join('')}${fieldEdited(row,k)?`<small>Original: ${esc(row.original_values[k]||'(blank)')}</small>`:''}</div>`).join('')}</div></details>${!row.committed?`<details><summary>Link or separate unit${row.identity_collision?' - same National ID':' (optional)'}</summary><label>Explicit existing case ID<input data-match="${row.id}" value="${esc(row.reconciliation.existing_case_id||'')}" ${disabled?'disabled':''}></label><label>Link / separate-unit explanation<input data-note="${row.id}" value="${esc(row.reconciliation.note||'')}" ${disabled?'disabled':''}></label>${(row.existing_cases||[]).map(match=>`<p>${esc(match.reference)} · ${esc(match.name)}<br>Case ID: <code>${esc(match.id)}</code></p>`).join('')}</details>`:''}</article>`;
  }
  function openRow(id){
    gridApi?.stopEditing();const row=current.find(r=>String(r.id)===id);if(!row||busy)return;
    node('[data-row-detail]').innerHTML=rowCard(row);
    node('[data-row-detail] details').open=true;
    node('[data-row-dialog]').showModal();
  }
  async function loadGrid(){
    if(gridApi)return;
    if(!gridAssets){
      const config=window.PORTAL_CONFIG||{},loader=window.MiniAppAssetLoader;
      gridAssets=Promise.all([...(config.farmupAgGridStyles||[]).map(url=>loader.loadStyle(url)),loader.loadScript(config.farmupAgGridScript,'agGrid')]).catch(error=>{gridAssets=null;throw error;});
    }
    await gridAssets;
    window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
    gridApi=window.agGrid.createGrid(node('[data-review-grid]'),{
      theme:'legacy',rowData:[],columnDefs:[],animateRows:false,ensureDomOrder:true,rowHeight:32,headerHeight:32,
      suppressMovableColumns:true,enableBrowserTooltips:true,alwaysShowHorizontalScroll:true,scrollbarWidth:16,stopEditingWhenCellsLoseFocus:true,
      getRowId:p=>String(p.data.id),defaultColDef:{sortable:true,resizable:true,filter:'agTextColumnFilter',width:150,tooltipValueGetter:p=>String(p.value??'')},
      rowClassRules:{'farmup-grid-row-blocked':p=>p.data.proposal.review_status==='blocked','farmup-grid-row-warning':p=>p.data.proposal.review_status!=='blocked'&&Boolean(issues(p.data))},
      onCellValueChanged:()=>{lastNotice='';gridApi.refreshCells({force:true});renderState();},
    });
    window.PortalMiniAppHelpers?.bindHoldToCopy?.(node('[data-review-grid]'),'.ag-cell:not([col-id="approval"]):not([col-id="source_row"])');
  }
  function columnDefs(keys){
    const textField=(field,width)=>({colId:field,headerName:human(field),width,valueGetter:p=>p.data.source_values?.[field]??'',
      editable:p=>editable(p.data)&&!['source_row','case_id'].includes(field)&&Object.values(active.state.bindings||{}).includes(field),
      valueSetter:p=>{const value=String(p.newValue??'');if(value===String(p.oldValue??''))return false;p.data.source_values[field]=value;p.data._edits={...p.data._edits,[field]:value};if(field==='customer_name')p.data.name=value;return true;},
      cellClassRules:{'farmup-cell-invalid':p=>fieldIssues(p.data,field).length>0,'farmup-cell-edited':p=>fieldEdited(p.data,field)||field in (p.data._edits||{})},
      tooltipValueGetter:p=>[`${human(field)}: ${p.value??''}`,...fieldIssues(p.data,field),...(fieldEdited(p.data,field)?[`Original: ${p.data.original_values[field]||'(blank)'}`]:[]),...(field in (p.data._edits||{})?['Unsaved correction — Save corrections']:[])].join('\n'),
    });
    const reconciliation=(id,title,key,width)=>({colId:id,headerName:title,width,
      editable:p=>!busy&&reviewable(p.data),valueGetter:p=>p.data.reconciliation[key]||'',
      valueSetter:p=>{p.data.reconciliation[key]=String(p.newValue??'');return true;},
    });
    return [
      {field:'source_row',headerName:'Row',width:32,minWidth:32,maxWidth:32,pinned:'left',sortable:false,resizable:false,filter:false,suppressHeaderMenuButton:true,cellRenderer:p=>{
        const button=document.createElement('button');button.type='button';button.className='legacy-row-details';button.textContent=p.value;button.dataset.rowOpen=p.data.id;button.disabled=busy;button.setAttribute('aria-label',`Review row ${p.value}`);return button;
      }},
      {colId:'approval',headerName:'',headerTooltip:'Approve row',width:40,minWidth:40,maxWidth:40,pinned:'left',sortable:false,filter:false,resizable:false,cellRenderer:p=>{
        const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.className='legacy-grid-approval';checkbox.checked=p.data.approved;checkbox.disabled=busy||!reviewable(p.data);checkbox.dataset.select=p.data.id;checkbox.setAttribute('aria-label',`Approve row ${p.data.source_row}`);
        const label=document.createElement('label');label.className='legacy-grid-approve-target';label.append(checkbox);return label;
      }},
      textField('customer_name',190),
      {colId:'review_state',headerName:'Review',width:108,valueGetter:p=>p.data.committed?'Imported':human(p.data.proposal.review_status||'ready'),tooltipValueGetter:p=>issues(p.data),cellRenderer:p=>{
        const badge=document.createElement('span');badge.className='farmup-row-state '+(p.data.proposal.review_status==='blocked'?'needs_correction':issues(p.data)?'warning':'ready');badge.textContent=p.data.identity_collision&&!p.data.committed?'Identity review':p.value;return badge;
      }},
      ...['national_id','primary_phone','secondary_phone','county','sub_county','village'].filter(k=>keys.includes(k)).map(k=>textField(k,145)),
      {colId:'workflow',headerName:'Proposed workflow',width:160,valueGetter:p=>human(p.data.proposal.state)},
      {colId:'issues',headerName:'Review notes',width:300,valueGetter:p=>issues(p.data)},
      reconciliation('match','Existing case ID','existing_case_id',220),reconciliation('note','Link / separate-unit explanation','note',260),
      ...keys.filter(k=>!['source_row','customer_name','national_id','primary_phone','secondary_phone','county','sub_county','village'].includes(k)).map(k=>textField(k,160)),
      {colId:'imported_case_id',headerName:'Imported case ID',width:250,valueGetter:p=>p.data.farmer_id||''},
    ];
  }
  async function renderReview(){
    node('[data-rows]').hidden=reviewMode!=='cards';node('[data-grid-wrap]').hidden=reviewMode!=='table';node('[data-table-hint]').hidden=reviewMode!=='table';
    if(reviewMode==='cards'){node('[data-rows]').innerHTML=current.map(rowCard).join('');return;}
    node('[data-rows]').replaceChildren();
    try{
      await loadGrid();
      const keys=[...new Set([...Object.values(active.state.bindings||{}),...current.flatMap(r=>Object.keys(r.source_values||{}))])];
      const key=active.id+JSON.stringify(keys);
      if(key!==gridColumns){gridApi.setGridOption('columnDefs',columnDefs(keys));gridApi.setFilterModel(null);gridApi.applyColumnState({defaultState:{sort:null}});gridColumns=key;}
      if(!gridApi.__personalLayout)gridApi.__personalLayout=window.MiniAppTableLayouts?.attach('legacy',gridApi,node('[data-review-grid]'));
      gridApi.__personalLayout?.refresh();
      gridApi.setGridOption('rowData',current);
    }catch(error){
      reviewMode='cards';lastNotice=`Table could not load. Cards are available; choose Table to retry. ${error.message}`;await renderReview();
    }
  }
  function renderState() {
    root.querySelectorAll('[data-source-sheet]').forEach(button=>{button.disabled=busy;button.classList.toggle('active',button.dataset.sourceSheet===selectedSheet);button.setAttribute('aria-pressed',String(button.dataset.sourceSheet===selectedSheet));});
    node('[data-source-description]').textContent=`${selectedSheet} import. ${selectedSheet==='Eco-conserve'?'Master Data':'Eco-conserve'} records and sheet are preserved.`;
    node('[data-resume]').disabled=busy;node('[data-filter]').disabled=busy||!active?.state;
    root.querySelectorAll('[data-review-mode]').forEach(button=>{button.disabled=busy||!active?.state;button.classList.toggle('active',button.dataset.reviewMode===reviewMode);button.setAttribute('aria-pressed',String(button.dataset.reviewMode===reviewMode));});
    node('[data-sheet-sync]').hidden=!active?.state;
    if(!active?.state){root.querySelectorAll('[data-action]').forEach(button=>{button.hidden=true;});node('[data-mapping]').hidden=true;node('[data-source]').open=true;node('[data-grid-wrap]').hidden=true;node('[data-rows]').hidden=true;node('[data-table-hint]').hidden=true;return;}
    node('[data-mapping]').hidden=false;
    node('[data-source]').open=active.phase==='uploading';
    const hold=active.frozen?(['backup','projecting','verifying','replacing','readback','deleting'].includes(active.phase)?'Register changes paused until verification':'Verified cases can continue; unverified cases remain held'):'';
    feedback(lastNotice || (pendingEdits()?'Unsaved corrections — use Save corrections to validate and retain your changes.':`${active.source_sheet} · ${active.filename} · ${active.phase} · ${active.total} staged · ${active.committed} imported · ${active.selected} approved${hold?' · '+hold:''}`));
    const processing=active.state.projection;
    node('[data-progress]').max=Math.max(processing?.count||active.total,1);node('[data-progress]').value=processing?.offset||active.committed;
    const sync=active.sheet_sync||{synced:0,pending:active.committed,not_imported:active.total-active.committed,state:'awaiting_import'};
    node('[data-sheet-sync]').dataset.state=sync.state;
    node('[data-imported-count]').textContent=`${active.committed} / ${active.total}`;
    node('[data-synced-count]').textContent=`${sync.synced} / ${active.committed}`;
    node('[data-sync-pending]').textContent=sync.pending;
    node('[data-not-imported]').textContent=sync.not_imported;
    node('[data-sync-progress]').max=Math.max(active.committed,1);node('[data-sync-progress]').value=sync.synced;
    const steps={syncing_rows:active.state.row_sync?.stage==='scan'?'Checking Sheet row identities':'Syncing oldest saved cases first',backup:'Backing up the current Sheet',projecting:'Preparing the Sheet update',verifying:'Checking the prepared update',replacing:'Publishing to the Sheet',readback:'Verifying published rows'};
    node('[data-sync-message]').textContent=sync.state==='needs_attention'?`Sheet sync needs attention. ${sync.error} Saved records remain in the database. Resume processing to retry the saved step.`:
      sync.state==='complete'?`Sheet sync complete: ${sync.synced} imported rows verified on ${active.source_sheet}.`:
      sync.state==='in_progress'?`${busy?steps[active.phase]||'Syncing':'Sheet sync paused'} · ${sync.synced} rows verified. ${busy?'You can pause after the current step.':'Use Resume processing to continue.'}`:
      active.phase==='committing'?`${active.committed} of ${active.total} source rows saved. ${busy?'Importing and syncing in FIFO order.':'Import paused. Use “Resume processing” to continue.'}`:
      sync.pending>0?`${sync.pending} saved cases await Sheet sync, oldest first. Use “Sync imported rows to Sheet” to retry; ${sync.not_imported} unimported source rows stay under review.`:
      `${sync.synced} saved cases verified on the Sheet. ${sync.not_imported} source rows remain: use “Review unimported rows”, approve them, then “Import approved rows”. Each saved batch syncs automatically in FIFO order.`;
    const available={stage:active.phase==='mapping',cleanup:superuser&&['ready','deleting'].includes(active.phase)&&!active.state.cleanup_complete,commit:active.phase==='ready'&&active.state.cleanup_complete,
      project:['ready','committing'].includes(active.phase)&&sync.pending>0,replace:active.phase==='ready'&&active.committed===active.total&&active.total>0,review_pending:active.phase==='ready'&&sync.not_imported>0,restart_projection:['backup','projecting','verifying'].includes(active.phase),cancel_preview:active.frozen&&!active.state.cleanup_started&&active.phase==='ready',discard:!active.frozen&&active.committed===0};
    for(const [name,enabled] of Object.entries(available)){const button=node(`[data-action="${name}"]`);button.hidden=!enabled;button.disabled=busy||!enabled;}
    node('[data-action="project"]').hidden=active.committed===0||active.phase==='complete';
    node('[data-action="save_edits"]').hidden=active.phase!=='ready';node('[data-action="save_edits"]').disabled=busy||!pendingEdits();
    for(const name of ["refresh","select_page","select_all","unselect_all","previous","next"]){node(`[data-action="${name}"]`).hidden=false;}
    for(const name of ['refresh','select_page','select_all','unselect_all','previous','next'])node(`[data-action="${name}"]`).disabled=busy||(name==='previous'&&offset===0)||(name==='next'&&offset+50>=pageTotal);
    node('[data-filter]').disabled=busy;node('[data-resume]').disabled=busy;
    for(const name of ['select_page','select_all','unselect_all'])node(`[data-action="${name}"]`).hidden=!['ready','committing'].includes(active.phase);
    node('[data-action="pause"]').hidden=!busy;
    node('[data-action="resume"]').hidden=!['staging','deleting','committing','syncing_rows','backup','projecting','verifying','replacing','readback'].includes(active.phase);
    node('[data-action="resume"]').disabled=busy;
    const bindings=active.state.bindings||{};node('[data-mapping-rows]').innerHTML=Object.entries(bindings).map(([i,field])=>`<div><strong>${esc(active.state.headers[i])}</strong><p>${esc(field)}</p></div>`).join('');
    node('[data-mapping]').open=active.phase==='mapping';
    gridApi?.refreshCells({force:true,columns:['approval','source_row']});
    const rowsById=new Map(current.map(row=>[String(row.id),row]));
    root.querySelectorAll('[data-select],[data-match],[data-note]').forEach(input=>{
      const row=rowsById.get(input.dataset.select||input.dataset.match||input.dataset.note);input.disabled=busy||!row||!reviewable(row);
    });
  }
  async function refresh() {
    if(!active)return;
    const data=await call(`${active.id}/?offset=${offset}&filter=${encodeURIComponent(node('[data-filter]').value)}`);current=data.rows;pageTotal=data.total;
    await renderReview();
    node('[data-page]').textContent=`${data.total?offset+1:0}–${offset+current.length} of ${data.total}`;
    node('[data-action="previous"]').disabled=offset===0;node('[data-action="next"]').disabled=offset+50>=data.total;renderState();
  }
  async function refreshSync() {
    if(document.hidden||busy||!root?.isConnected||!root.offsetParent||!active?.committed||active.phase==='complete')return;
    const id=active.id,revision=active.revision;
    try{
      const response=await window.PortalMiniAppApi.apiFetch(`/legacy/uploads/${id}/?summary=1`,{},window.Telegram?.WebApp);
      if(!response.ok||!response.data?.ok||busy||active?.id!==id||active.revision!==revision)return;
      active={...response.data.upload,revision};renderState();
    }catch{ /* The saved indicator remains; explicit refresh reports connection errors. */ }
  }
  async function confirm(title,text,warning) {
    const dialog=node('[data-confirm]');node('[data-confirm-title]').textContent=title;node('[data-confirm-text]').textContent=text;node('[data-confirm-warning]').textContent=warning;
    return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});
  }
  async function process() {
    running=true;
    if(['ready','committing'].includes(active.phase)&&active.sheet_sync?.pending>0)await command('sync_rows');
    while(running&&!document.hidden&&['staging','deleting','committing','syncing_rows','backup','projecting','verifying','replacing','readback'].includes(active.phase)) {
      const data=await command('advance');renderState();
      if(data.results?.some(r=>r.ok)&&active.sheet_sync?.pending>0)await command('sync_rows');
      if(data.wait_seconds)await new Promise(resolve=>setTimeout(resolve,Math.ceil(data.wait_seconds*1000)));
      if(data.results?.some(r=>!r.ok)){lastNotice=`Some rows were held: ${[...new Set(data.results.filter(r=>!r.ok).map(r=>r.error))].join(' ')}`;feedback(lastNotice);}
    }
    running=false;await refresh();
  }
  async function saveCorrections(){
    const edited=current.filter(row=>Object.keys(row._edits||{}).length);
    if(!edited.length)return;
    await selection(current.filter(row=>!row.committed));
    for(const row of edited){await command('edit',{id:row.id,changes:row._edits});delete row._edits;}
    await refresh();
  }
  async function run(task,saveEdits=true) {
    if(busy)return;gridApi?.stopEditing();busy=true;lastNotice='';renderState();
    try{if(saveEdits)await saveCorrections();await task();}catch(error){running=false;try{if(active&&!pendingEdits())await refresh();}catch{}lastNotice=error.message;feedback(lastNotice);}finally{busy=false;renderState();}
  }
  async function selection(rows) {
    if(!rows.length||!['ready','committing'].includes(active.phase))return;
    gridApi?.stopEditing();
    await command('select',{rows:rows.map(r=>({id:r.id,approved:r.approved,
      existing_case_id:r.reconciliation.existing_case_id||'',note:r.reconciliation.note||''}))});
  }
  async function init() {
    root=document.getElementById('legacy-data-workspace');if(!root||root.dataset.ready)return;root.dataset.ready='true';
    await run(loadIndex);
    node('[data-resume]').onchange=()=>run(async()=>{if(!node('[data-resume]').value)return;active={id:node('[data-resume]').value};offset=0;await refresh();if(active.sheet_sync?.pending>0&&['ready','committing','syncing_rows'].includes(active.phase))await process();});
    node('[data-upload-form]').onsubmit=event=>{event.preventDefault();run(async()=>{
      const file=node('[name="file"]').files[0];if(!file||file.size>20*1024*1024)throw new Error('Select one XLSX up to 20 MiB.');
      feedback('Reading source checksum…');const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))).map(v=>v.toString(16).padStart(2,'0')).join('');
      await call('',{group_id:node('[name="group_id"]').value,namespace:node('[name="namespace"]').value,filename:file.name,size:file.size,digest,source_sheet:selectedSheet});
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
    root.addEventListener('input',event=>{
      const target=event.target,id=target.dataset.select||target.dataset.match||target.dataset.note;
      const row=current.find(r=>String(r.id)===id);if(!row||busy||!reviewable(row))return;
      if(target.dataset.select)row.approved=target.checked;
      if(target.dataset.match)row.reconciliation.existing_case_id=target.value;
      if(target.dataset.note)row.reconciliation.note=target.value;
    });
    node('[data-row-dialog]').addEventListener('close',()=>{gridApi?.refreshCells({force:true});if(reviewMode==='cards')node('[data-rows]').innerHTML=current.map(rowCard).join('');});
    root.addEventListener('click',event=>{
      const source=event.target.closest('[data-source-sheet]')?.dataset.sourceSheet;
      if(source){run(async()=>{
        if(source===selectedSheet)return;
        if(active)await selection(current.filter(r=>!r.committed));
        selectedSheet=source;active=null;current=[];offset=0;pageTotal=0;
        try{sessionStorage.setItem('portal-legacy-source-sheet',source);}catch{}
        node('[data-rows]').replaceChildren();gridApi?.setGridOption('rowData',[]);node('[data-page]').textContent='';node('[data-progress]').value=0;node('[data-filter]').value='all';
        feedback(`Choose a reviewed ${source} workbook or resume its saved import.`);await loadIndex();
      });return;}
      const mode=event.target.closest('[data-review-mode]')?.dataset.reviewMode;
      if(mode){run(async()=>{reviewMode=mode;try{sessionStorage.setItem('portal-legacy-review-mode',mode);}catch{}await renderReview();});return;}
      const rowId=event.target.closest('[data-row-open]')?.dataset.rowOpen;
      if(rowId){openRow(rowId);return;}
      const action=event.target.closest('[data-action]')?.dataset.action;if(!action)return;
      if(action==='pause'){running=false;feedback('Pausing after the current saved chunk.');return;}
      run(async()=>{
        if(!active)throw new Error('Choose or upload a workbook first.');
        if(action==='refresh'){if(!pendingEdits()||await confirm('Reload saved review','Discard corrections that have not been saved?','Saved corrections and original workbook evidence are retained.'))await refresh();}
        else if(action==='save_edits')lastNotice='Corrections saved and revalidated. Review and approve the changed rows again.';
        else if(action==='resume')await process();
        else if(action==='stage'){await command('stage');await process();}
        else if(action==='previous'||action==='next'){await selection(current.filter(r=>!r.committed));offset=Math.max(0,offset+(action==='previous'?-50:50));await refresh();}
        else if(action==='select_page'){
          const rows=[];if(reviewMode==='table'&&gridApi)gridApi.forEachNodeAfterFilterAndSort(n=>{if(reviewable(n.data))rows.push(n.data);});else rows.push(...current.filter(reviewable));
          rows.forEach(r=>{r.approved=true;});await selection(current.filter(r=>!r.committed));await refresh();
        }
        else if(action==='select_all'||action==='unselect_all'){await selection(current.filter(r=>!r.committed));await command('select',{all:true,approved:action==='select_all'});await refresh();}
        else if(action==='review_pending'){await selection(current.filter(r=>!r.committed));node('[data-filter]').value='pending';offset=0;await refresh();}
        else if(action==='commit'){await selection(current.filter(r=>!r.committed));if(await confirm('Import approved records',`Import the saved selection (${active.selected} approved rows)?`,`Saved cases sync to ${active.source_sheet} automatically in FIFO order. Pause manual edits to the affected Sheet rows. Historical gaps remain unknown.`)){await command('commit');await process();}}
        else if(action==='cleanup'){
          running=true;let result;do{result=await command('cleanup_preview');renderState();}while(!result.review.complete&&running&&!document.hidden);running=false;
          if(result.review.complete&&await confirm('Delete '+active.source_sheet+' test data',`Delete ${result.review.count} ${active.source_sheet} test cases for ${active.group_label} and the disclosed dependent records?`,'Impact: '+result.review.impact.map(i=>`${i.category}: ${i.count} ${i.model}`).join('; ')+'. The other register is preserved. No Sheet rows are deleted in this step. The owner remains held until cutover finishes.')){await command('cleanup_confirm',{token:result.review.token});await process();}
        }
        else if(action==='project'){
          await command('sync_rows');await process();
        }
        else if(action==='replace'){
          const result=await command('projection_preview');await refresh();
          if(await confirm('Replace '+active.source_sheet,`${result.preview.tab} · ${result.preview.spreadsheet}: replace all data rows with ${result.preview.rows} imported cases.`,'Pause manual edits to this register now. Unmatched old rows will be removed. Headers and formatting stay; '+result.preview.preserved_register+' is untouched.')){await command('projection_confirm',{manual_edits_paused:true});await process();}
        }
        else if(action==='discard'){if(await confirm('Discard upload','Remove this uncommitted staging version?','Existing cases and other versions remain.')){await command('discard');await refresh();}}
        else if(action==='restart_projection'){await command('restart_projection');await refresh();}
        else if(action==='cancel_preview'){await command('cancel_preview');await refresh();}
      },action!=='refresh');
    });
    window.setInterval(refreshSync,15000);
    window.addEventListener('beforeunload',event=>{if(pendingEdits()){event.preventDefault();event.returnValue='';}});
    renderState();
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)running=false;else void refreshSync();});
  window.PortalLegacyImporter={init};
})();
