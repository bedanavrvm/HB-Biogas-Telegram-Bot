/* Portal insights: current grants and every chart selection are checked server-side. */
(() => {
  'use strict';
  const root=()=>document.getElementById('portal-reports-root');
  const labels={pipeline:'Pipeline',outcomes:'Outcomes',finance:'Finance'};
  const stages={jbl_visit:'Awaiting visit',credit:'Credit analysis',final_review:'Final review',order:'Ready for order',ordered:'Ordered',deferred:'On hold',rejected:'Rejected',withdrawn:'Withdrawn'};
  const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  function pref(value){try{if(value)localStorage.setItem('portal-report-display',value);return localStorage.getItem('portal-report-display');}catch(_){return null;}}
  const s={preset:'pipeline',result:null,applied:{},intent:{},sequence:0,tg:null,charts:[],observer:null,display:pref()==='list'?'list':'carousel',types:{},index:0,loading:false,exporting:false,error:'',origin:null,page:1,scroll:0,resumeScroll:null,grid:null,searchTimer:null,search:'',gridMetrics:null};
  const icon=name=>({search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',cases:'<path d="M8 6h12M8 12h12M8 18h12M3 6h1M3 12h1M3 18h1"/>',download:'<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>',filter:'<path d="M4 6h16M7 12h10M10 18h4"/>',settings:'<path d="M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6"/>',calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>'}[name]||'');
  const svg=name=>`<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${icon(name)}</svg>`;
  const id=()=>crypto.randomUUID?.() || `report-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  function fmt(v,type){if(v===null||v===undefined||v==='')return '—';if(type==='number')return new Intl.NumberFormat('en-KE',{maximumFractionDigits:2}).format(v);if(type==='date'){const d=new Date(v);return isNaN(d)?esc(v):d.toLocaleDateString('en-GB',{timeZone:'Africa/Nairobi',day:'2-digit',month:'short',year:'numeric'});}return esc(type==='choice'?stages[v]||v:v);}
  function destroy(includeGrid=true){s.charts.forEach(c=>c.destroy());s.charts=[];s.observer?.disconnect();s.observer=null;if(includeGrid){s.grid?.destroy();s.grid=null;}}
  function month(){const p=new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Nairobi',year:'numeric',month:'2-digit'}).formatToParts(new Date());return `${p.find(x=>x.type==='year').value}-${p.find(x=>x.type==='month').value}`;}
  function filterSheet(){
    const f=s.applied,o=s.result.filter_options,mode=f.date_mode || (s.preset==='pipeline'?'all':'month');
    const select=(key,label,values)=>`<label>${label}<select name="${key}"><option value="">All</option>${values.map(v=>`<option value="${esc(v)}"${f[key]===v?' selected':''}>${esc(key==='stage'?stages[v]:v)}</option>`).join('')}</select></label>`;
    return `<dialog id="portal-report-dialog" aria-labelledby="portal-report-filter-title"><form id="portal-report-filters"><header><h2 id="portal-report-filter-title">Filter ${labels[s.preset].toLowerCase()}</h2><button type="button" data-action="close" aria-label="Close filters without applying">×</button></header><div class="portal-report-filter-fields">
    ${select('branch','Branch',o.branches||[])}${select('county','County',o.counties||[])}${select('product','Product',o.products||[])}
    ${s.preset==='pipeline'?select('stage','Stage',['jbl_visit','credit','final_review','order','ordered','deferred','rejected','withdrawn']):''}
    <label class="portal-report-wide">Dates<select name="date_mode">${[['all','Any time'],['month','Month'],['custom','Date range']].map(([v,l])=>`<option value="${v}"${v===mode?' selected':''}>${l}</option>`).join('')}</select></label>
    ${[['month','Month','month',f.month||month()],['from','From','date',f.from||''],['to','To','date',f.to||'']].map(([name,label,type,value])=>`<label data-date="${type==='month'?'month':'custom'}">${label}<span class="portal-native-date"><span data-date-display="${name}"></span>${svg('calendar')}<input type="${type}" name="${name}" aria-label="${label}" value="${esc(value)}"></span></label>`).join('')}
    <label class="portal-report-wide">Group dates by<select name="granularity">${['day','week','month','year'].map(v=>`<option value="${v}"${v===(f.granularity||'month')?' selected':''}>${v[0].toUpperCase()+v.slice(1)}</option>`).join('')}</select></label></div><footer><button type="button" class="btn btn-secondary" data-action="reset">Reset</button><button type="submit" class="btn btn-primary">Apply filters</button></footer></form></dialog>`;
  }
  function chartMarkup(c){
    const presentation=window.MiniAppReportControls.chartPresentation({id:c.id,temporal:c.type==='line'||['activity','received','invoice_trend'].includes(c.id),composition:['visits','credit','final'].includes(c.id),stacked:c.id==='sla',count:c.labels.length});
    const types=c.allowed_types||presentation.allowedTypes;
    if(!types.includes(s.types[c.id]))s.types[c.id]=c.default_type||presentation.defaultType;
    return `<article class="portal-insight-chart" data-chart="${esc(c.id)}"><header><h3>${esc(c.title)}${c.type==='line'?` <small class="portal-chart-interval">${esc(s.applied.granularity||'month')}</small>`:''}</h3><details class="portal-chart-settings"><summary aria-label="${esc(c.title)} options" title="Chart options">${svg('settings')}</summary><div role="group" aria-label="${esc(c.title)} chart type">${types.map(t=>`<button type="button" data-type="${t}" data-key="${esc(c.id)}" aria-pressed="${t===s.types[c.id]}">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}</div>${c.type==='line'?`<div class="portal-chart-period" role="group" aria-label="Time grouping">${['day','week','month','year'].map(g=>`<button type="button" data-granularity="${g}" aria-pressed="${g===(s.applied.granularity||'month')}">${g[0].toUpperCase()+g.slice(1)}</button>`).join('')}</div>`:''}</details><details class="portal-chart-cases"><summary aria-label="View cases" title="View cases">${svg('cases')}</summary><div class="portal-chart-case-options">${c.context?`<p class="portal-chart-context">${esc(c.context)}</p>`:''}${c.sample_counts?`<p class="portal-chart-context">${c.bucket_keys.map((b,i)=>`${esc(c.labels[i])}: ${c.sample_counts[b]||0} samples`).join(' · ')}</p>`:''}<div class="portal-chart-drill"><select data-series aria-label="${esc(c.title)} series">${c.datasets.map(d=>`<option value="${esc(d.key)}">${esc(d.label)}</option>`).join('')}</select><select data-bucket aria-label="${esc(c.title)} cases"><option value="">Choose cases…</option>${c.bucket_keys.map((b,i)=>`<option value="${esc(b)}">${esc(c.labels[i])}</option>`).join('')}</select><button type="button" class="btn btn-secondary" data-action="drill" disabled>Show cases</button></div></div></details></header><div class="portal-chart-canvas"><canvas role="img" aria-label="${esc(c.title)}"></canvas><p class="portal-chart-state" role="status" hidden></p></div>
</article>`;
  }
  function render(){
    const target=root();if(!target)return;destroy();const r=s.result;
    const tabs=`<div class="portal-curated-tabs" role="tablist" aria-label="Report sections">${Object.entries(labels).map(([k,l])=>`<button type="button" role="tab" data-preset="${k}" aria-selected="${k===s.preset}" class="${k===s.preset?'active':''}">${l}</button>`).join('')}</div>`;
    if(!r){target.innerHTML=`${tabs}<div class="empty-state" role="status">${s.error?`${esc(s.error)} <button class="btn btn-secondary" data-action="retry">Try again</button><button class="btn btn-secondary" data-action="reset">Reset filters</button>`:'Loading reports…'}</div>`;return;}
    const f=s.applied,p=r.pagination,selected=r.charts.find(c=>c.id===f.chart_key),selection=selected?.labels[selected.bucket_keys.indexOf(f.bucket_key)]||'';
    const description=[f.branch||'All branches',f.county,f.product,stages[f.stage]].filter(Boolean).map(esc).join(' · ');
    const count=['branch','county','product','stage'].filter(key=>f[key]).length+(f.date_mode&&f.date_mode!=='all'?1:0);
    const period=r.period?`${fmt(r.period.from,'date')} – ${fmt(r.period.to,'date')}`:'Any time';
    target.innerHTML=`<div class="portal-report-heading"><h1>Reports</h1><div class="report-email-actions"><button type="button" class="report-email-icon" data-action="email" aria-label="Email report" title="Email report">${window.MiniAppReportEmailExport?.icon || ''}</button><button class="portal-report-icon" type="button" data-action="export" aria-label="Export report" title="Export report"${s.exporting?' disabled':''}>${svg('download')}</button></div></div>${tabs}<div class="portal-report-controls"><button class="portal-report-filter-bar" type="button" data-action="filters" aria-haspopup="dialog" aria-controls="portal-report-dialog"><span class="portal-filter-action">${svg('filter')}<strong>Filters</strong>${count?`<b>${count}</b>`:''}</span><span class="portal-filter-summary"><strong>${description}</strong><small>${period}</small></span><span aria-hidden="true">›</span></button></div><p class="portal-report-status" role="status">${s.loading?'Updating report…':esc(s.error)}${s.error?' <button type="button" data-action="retry">Try again</button>':''}</p>
    <div class="portal-curated-summary">${Object.entries(r.summary).map(([l,v])=>`<div><strong>${fmt(v,'number')}</strong><span>${esc(l)}</span></div>`).join('')}</div>
    <div class="portal-chart-toolbar"><div role="group" aria-label="Chart display">${['carousel','list'].map(v=>`<button type="button" data-display="${v}" aria-pressed="${s.display===v}">${v[0].toUpperCase()+v.slice(1)}</button>`).join('')}</div><nav aria-label="Chart pages"${s.display==='list'?' hidden':''}><button type="button" data-action="previous" aria-label="Previous chart">‹</button><span id="portal-chart-position" aria-live="polite"></span><button type="button" data-action="next" aria-label="Next chart">›</button></nav></div>
    <section id="portal-insight-charts" class="portal-insight-charts ${s.display}" aria-label="Portal report charts" tabindex="0">${r.charts.map(chartMarkup).join('')}</section>
    ${resultsMarkup(r)}${filterSheet()}`;
    mountGrid(target,r);
    target.querySelectorAll('.portal-insight-chart').forEach(card=>{const c=r.charts.find(item=>item.id===card.dataset.chart);const note=document.createElement('p');card.appendChild(note);window.MiniAppReportControls.setChartHelp(note,c.context||`${c.title}. Select a chart item to see its cases.`);note.remove();});
    const box=target.querySelector('#portal-insight-charts');box.addEventListener('scroll',position,{passive:true});box.addEventListener('keydown',e=>{if(e.target===box&&s.display==='carousel'&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();move(e.key==='ArrowRight'?1:-1);}});
    target.querySelector('dialog').addEventListener('close',()=>{target.querySelector('#portal-report-filters')?.reset();dates();target.querySelector('[data-action="filters"]')?.focus();});if(s.resumeScroll!==null){box.scrollLeft=s.resumeScroll;s.resumeScroll=null;}position();draw();
  }

  function resultsMarkup(r) {
    const f=s.applied,p=r.pagination,selected=r.charts.find(c=>c.id===f.chart_key);
    const selection=selected?.labels[selected.bucket_keys.indexOf(f.bucket_key)]||'';
    return `<section class="portal-curated-results" tabindex="-1" aria-label="Case results"><label class="portal-report-search"><span class="sr-only">Search cases</span>${svg('search')}<input type="search" id="portal-report-search" maxlength="120" placeholder="Search name or case reference" value="${esc(s.search||f.search||'')}"></label><div class="portal-results-selection">${f.chart_key?`<button type="button" class="portal-chart-selection" data-action="clear" aria-label="Clear chart selection">${esc(selected?.title||'Chart selection')} · ${esc(selection)}${selected?.datasets.length>1?` · ${esc(selected.datasets.find(d=>d.key===f.series_key)?.label||f.series_key)}`:''} ×</button>`:''}</div><div class="portal-results-heading"><div><h2>Cases <small>${r.total_rows.toLocaleString()}</small></h2></div><div class="miniapp-table-zoom" data-miniapp-table-zoom="portal-curated"><button type="button" data-miniapp-table-zoom-out aria-label="Zoom table out">−</button><button type="button" data-miniapp-table-zoom-reset>100%</button><button type="button" data-miniapp-table-zoom-in aria-label="Zoom table in">+</button></div></div>
    ${r.total_rows>r.shown_rows_limit?`<p class="portal-chart-context">Charts cover all matching cases. Table and export show up to ${r.shown_rows_limit.toLocaleString()} cases.</p>`:''}
    <div id="portal-report-grid" class="ag-theme-quartz" aria-label="Report cases" hidden></div><div class="portal-report-table-wrap" data-miniapp-table-zoom-target><table class="portal-report-table"><thead><tr>${r.columns.map(c=>`<th>${esc(c.label)}</th>`).join('')}</tr></thead><tbody>${r.rows.map(row=>`<tr>${r.columns.map(c=>`<td>${c.key==='case_id'&&/^[0-9a-f-]{36}$/.test(row.record_id||'')?`<a href="/portal/cases/${esc(row.record_id)}/">${fmt(row[c.key],c.type)}</a>`:fmt(row[c.key],c.type)}</td>`).join('')}</tr>`).join('')||`<tr><td colspan="${r.columns.length}">No cases match these filters.</td></tr>`}</tbody></table></div>
    <div class="pagination"${p.pages<=1?' hidden':''}><button type="button" class="btn btn-secondary" data-page="${p.page-1}"${p.page<=1?' disabled':''}>Previous</button><span>Page ${p.page} of ${p.pages}</span><button type="button" class="btn btn-secondary" data-page="${p.page+1}"${p.page>=p.pages?' disabled':''}>Next</button></div></section>`;
  }
  function resizeGrid() {
    const node=root()?.querySelector('#portal-report-grid');
    if(!node||!s.gridMetrics)return;
    const rows=Math.max(1,Math.min(8,s.result?.rows.length||0));
    node.style.height=`${s.gridMetrics.headerHeight+rows*s.gridMetrics.rowHeight+20}px`;
  }
  function updateResults() {
    const r=s.result,section=root()?.querySelector('.portal-curated-results');
    if(!section)return render();
    const template=document.createElement('template');template.innerHTML=resultsMarkup(r);
    const next=template.content.querySelector('section');
    for(const selector of ['.portal-results-selection','.portal-results-heading h2','.pagination']){
      section.querySelector(selector).replaceWith(next.querySelector(selector));
    }
    // Preserve the table instance, user column widths and horizontal position.
    if(s.grid){s.grid.setGridOption('rowData',r.rows);resizeGrid();}
    else section.querySelector('.portal-report-table-wrap').innerHTML=next.querySelector('.portal-report-table-wrap').innerHTML;
    markSelection();
  }
  function markSelection() {
    const f=s.applied;
    s.charts.forEach(chart=>{
      const spec=s.result.charts.find(c=>c.id===chart.canvas.closest('[data-chart]').dataset.chart);
      if(!spec)return;
      chart.data.datasets.forEach((dataset,i)=>{
        const selected=spec.id===f.chart_key&&spec.datasets[i].key===f.series_key;
        if(chart.config.type==='line')dataset.pointRadius=spec.bucket_keys.map(b=>selected&&b===f.bucket_key?6:2);
        else dataset.borderWidth=spec.bucket_keys.map(b=>selected&&b===f.bucket_key?3:0);
        if(chart.config.type==='doughnut')dataset.borderColor=dataset.backgroundColor;
      });
      chart.update('none');
    });
  }
  function reportStatus(message,error=false) {
    const node=root()?.querySelector('.portal-report-status');
    if(node){node.textContent=message;if(error){const button=document.createElement('button');button.type='button';button.dataset.action='retry';button.textContent='Try again';node.append(' ',button);}}
    root()?.querySelector('.portal-curated-results')?.setAttribute('aria-busy',String(s.loading));
    if(s.grid){if(s.loading)s.grid.showLoadingOverlay();else if(!s.result.rows.length)s.grid.showNoRowsOverlay();else s.grid.hideOverlay();}
  }
  async function mountGrid(target,r){
    const node=target.querySelector('#portal-report-grid');
    try{
      const config=window.PORTAL_CONFIG||{};
      if(!window.agGrid){if(!config.farmupAgGridScript)throw new Error('Table asset unavailable');await Promise.all((config.farmupAgGridStyles||[]).map(url=>window.MiniAppAssetLoader.loadStyle(url)));await window.MiniAppAssetLoader.loadScript(config.farmupAgGridScript,'agGrid');}
      if(root()!==target||s.result!==r||!node.isConnected||target.querySelector('#portal-report-grid')!==node)return;
      window.agGrid.ModuleRegistry.registerModules([window.agGrid.AllCommunityModule]);
      node.hidden=false;
      s.grid=window.agGrid.createGrid(node,{theme:'legacy',rowData:r.rows,animateRows:false,ensureDomOrder:true,rowHeight:36,headerHeight:36,suppressMovableColumns:true,enableBrowserTooltips:true,overlayNoRowsTemplate:'<span>No cases match these filters.</span>',defaultColDef:{resizable:true,sortable:false,minWidth:130},columnDefs:[{headerName:'#',colId:'row_number',width:48,minWidth:48,maxWidth:48,pinned:'left',resizable:false,valueGetter:p=>((s.result.pagination.page-1)*s.result.pagination.page_size)+p.node.rowIndex+1},...r.columns.map(c=>({field:c.key,headerName:c.label,width:c.key==='customer_name'?190:c.type==='date'?130:c.type==='number'?120:150,valueFormatter:p=>{const value=fmt(p.value,c.type);const el=document.createElement('span');el.innerHTML=value;return el.textContent;},tooltipValueGetter:p=>String(p.value??''),...(c.key==='case_id'?{cellRenderer:p=>{if(!/^[0-9a-f-]{36}$/.test(p.data?.record_id||''))return String(p.value??'');const a=document.createElement('a');a.href=`/portal/cases/${p.data.record_id}/`;a.textContent=String(p.value??'');return a;}}:{})}))]});
      target.querySelector('.portal-report-table-wrap').hidden=true;
      window.PortalMiniAppHelpers?.bindHoldToCopy?.(node,'.ag-cell');
      const controls=target.querySelector('[data-miniapp-table-zoom]');
      window.MiniAppAgGridZoom?.bind({gridElement:node,apiProvider:()=>s.grid,outButton:controls.querySelector('[data-miniapp-table-zoom-out]'),inButton:controls.querySelector('[data-miniapp-table-zoom-in]'),resetButton:controls.querySelector('[data-miniapp-table-zoom-reset]'),storageKey:'portal-curated-grid-zoom',onChange:(_level,metrics)=>{s.gridMetrics=metrics;resizeGrid();}});
    }catch(_){node.hidden=true;window.MiniAppComponents?.bindTableZoom?.(target.querySelector('[data-miniapp-table-zoom]'),'portal-curated-table-zoom');window.PortalMiniAppHelpers?.bindHoldToCopy?.(target,'.portal-report-table td');}
  }
  function position(){const box=root()?.querySelector('#portal-insight-charts');if(!box)return;s.index=Math.max(0,Math.min(box.children.length-1,Math.round(box.scrollLeft/(box.clientWidth+12))));box.style.height=s.display==='carousel'&&box.children.length?`${box.children[s.index].offsetHeight}px`:'';root().querySelector('#portal-chart-position').textContent=box.children.length?`${s.index+1} of ${box.children.length}`:'No charts';root().querySelector('[data-action="previous"]').disabled=s.index===0;root().querySelector('[data-action="next"]').disabled=s.index>=box.children.length-1;}
  function move(d){const box=root()?.querySelector('#portal-insight-charts');box?.scrollTo({left:(s.index+d)*(box.clientWidth+12),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}
  async function draw(){
    const target=root(),r=s.result,seq=s.sequence;if(!target||!r)return;
    try{if(!window.Chart)await window.MiniAppAssetLoader.loadScript(window.PORTAL_CONFIG?.chartScript,'Chart');}catch(_){if(root()===target)target.querySelectorAll('.portal-chart-state').forEach(p=>{p.hidden=false;p.textContent='Charts unavailable. Use the table or export below.';});return;}
    if(root()!==target||s.result!==r||seq!==s.sequence)return;
    const style=getComputedStyle(target),text=style.getPropertyValue('--text-primary').trim()||'#344054',grid=style.getPropertyValue('--border-color').trim()||'#e2e8f0',colors=['#2481cc','#168354','#d14343','#9261d5','#d69416'];
    r.charts.forEach(c=>{const card=target.querySelector(`[data-chart="${c.id}"]`),canvas=card.querySelector('canvas'),type=s.types[c.id];
      if(!c.labels.length){canvas.hidden=true;const p=card.querySelector('.portal-chart-state');p.hidden=false;p.textContent=c.unit==='hours'?'Timing unavailable for this period.':'No matching data.';return;}
      const pie=type==='doughnut',stacked=type==='stacked_bar',datasets=c.datasets.map((d,i)=>({label:d.label,data:d.values.map(Number),backgroundColor:pie?c.labels.map((_,j)=>colors[j%colors.length]):colors[i%colors.length],borderColor:pie?c.labels.map((_,j)=>colors[j%colors.length]):colors[i%colors.length],borderWidth:type==='line'?2:0,pointRadius:2,tension:.2}));
      s.charts.push(new window.Chart(canvas,{type:stacked?'bar':type,data:{labels:c.labels.map(l=>l.length>25?l.slice(0,24)+'…':l),datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,indexAxis:['bar','stacked_bar'].includes(type)&&c.type!=='line'?'y':'x',onClick:(_e,elements)=>{if(elements.length){const e=elements[0];drill(c,c.bucket_keys[e.index],c.datasets[e.datasetIndex].key);}},plugins:{legend:{display:pie||datasets.length>1,position:'bottom',labels:{color:text,boxWidth:10}},tooltip:{callbacks:{title:items=>items.length?c.labels[items[0].dataIndex]:'',label:ctx=>`${ctx.dataset.label}: ${fmt(ctx.raw,'number')}${c.unit==='KES'?' KES':c.unit==='hours'?' hours':''}`}}},scales:pie?{}:{x:{stacked,beginAtZero:true,ticks:{color:text,maxRotation:0,maxTicksLimit:6},grid:{color:grid}},y:{stacked,beginAtZero:true,ticks:{color:text,precision:c.unit==='cases'?0:undefined},grid:{color:grid}}}}}));});
    markSelection();
    if(window.ResizeObserver){s.observer=new ResizeObserver(()=>{s.charts.forEach(c=>c.resize());position();});s.observer.observe(target.querySelector('#portal-insight-charts'));}
  }
  const close=()=>root()?.querySelector('dialog')?.close();
  function dates(){const form=root()?.querySelector('#portal-report-filters');if(!form)return;form.querySelectorAll('[data-date]').forEach(l=>{l.hidden=l.dataset.date!==form.elements.date_mode.value;const input=l.querySelector('input');input.required=!l.hidden;input.disabled=l.hidden;if(l.hidden)input.setCustomValidity('');const value=input.value;const display=l.querySelector('[data-date-display]');if(display)display.textContent=value?(input.type==='month'?new Intl.DateTimeFormat('en-GB',{month:'short',year:'numeric',timeZone:'Africa/Nairobi'}).format(new Date(`${value}-01T00:00:00+03:00`)):new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Africa/Nairobi'}).format(new Date(`${value}T00:00:00+03:00`))):'Choose date';});}
  const drill=(c,bucket,series)=>{if(!bucket)return;clearTimeout(s.searchTimer);return load(1,{...s.applied,search:s.search,chart_key:c.id,bucket_key:bucket,series_key:series},{tableOnly:true,reveal:true});};
  async function load(page=1,filters={},options={}) {
    if(!root())return;
    const seq=++s.sequence,preset=s.preset;
    const tableOnly=options.tableOnly&&(filters.search||'')===(s.applied.search||'');
    s.intent={...filters};s.retryOptions=options;s.loading=true;s.error='';
    if(!s.result)render();else reportStatus(tableOnly?'Updating cases…':'Updating report…');
    try{
      const response=await window.PortalMiniAppApi.postJson('/reports/workspace/',{
        preset,filters:{...filters},page,client_request_id:id(),
      },s.tg);
      if(seq!==s.sequence||!root())return;
      if(!response.ok||!response.data?.ok)throw new Error(response.data?.error||'The report could not be loaded.');
      const focused=document.activeElement?.id==='portal-report-search';
      const cursor=document.activeElement?.selectionStart;
      s.result=response.data.result;s.applied={...s.result.applied_filters};
      s.search=s.applied.search||'';s.loading=false;
      if(tableOnly){updateResults();reportStatus(`${s.result.total_rows.toLocaleString()} cases found.`);}
      else render();
      if(options.reveal){
        const section=root().querySelector('.portal-curated-results');
        section.focus({preventScroll:true});
        section.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
      }else if(focused){
        const input=root().querySelector('#portal-report-search');
        input?.focus({preventScroll:true});
        try{input?.setSelectionRange(cursor,cursor);}catch(_){}
      }
    }catch(e){
      if(seq!==s.sequence||!root())return;
      s.error=e.message;s.loading=false;
      if(s.result)reportStatus(s.error,true);else render();
    }
  }
  async function exportXlsx(){if(s.exporting||s.loading)return;const seq=s.sequence,b=root()?.querySelector('[data-action="export"]');const scope=await window.MiniAppReportControls.chooseExcelExport({trigger:b});if(!scope||seq!==s.sequence||!root())return;s.exporting=true;if(b){b.disabled=true;b.setAttribute('aria-label','Preparing export');}
    try{const response=await window.PortalMiniAppApi.postJson('/reports/workspace/export/',{preset:s.preset,filters:scope==='all'?{date_mode:'all'}:{...s.applied},prepare_download:true,client_request_id:id()},s.tg);if(!response.ok||!response.data?.ok)throw new Error(response.data?.error||'The export could not be prepared.');if(seq===s.sequence)window.PortalAppShell?.downloadPortalFile?.({url:response.data.download_url,filename:response.data.filename});}
    catch(e){window.PortalAppShell?.showToast?.(e.message,'error');}finally{s.exporting=false;const button=root()?.querySelector('[data-action="export"]');if(button){button.disabled=false;button.setAttribute('aria-label','Export report');}}}
  function emailReport(){if(s.loading)return;window.MiniAppReportEmailExport?.open({workflow:'jawabu_portal',preset:s.preset,title:labels[s.preset],filters:{...s.applied},telegram:s.tg,
    post:async payload=>{const response=await window.PortalMiniAppApi.postJson('/reports/workspace/email/',payload,s.tg);if(!response.ok||!response.data?.ok)throw new Error(response.data?.error||'Could not email this report.');return response.data;},
    notify:(message,tone)=>window.PortalAppShell?.showToast?.(message,tone)});}
  document.addEventListener('click',e=>{
    if(!root()?.contains(e.target))return;
    const preset=e.target.closest('[data-preset]');if(preset){clearTimeout(s.searchTimer);s.preset=preset.dataset.preset;s.result=null;s.applied={};s.search='';return load();}
    const display=e.target.closest('[data-display]');if(display){s.display=display.dataset.display;pref(s.display);return render();}
    const type=e.target.closest('[data-type]');if(type){s.resumeScroll=root().querySelector('#portal-insight-charts').scrollLeft;s.types[type.dataset.key]=type.dataset.type;return render();}
    const grouping=e.target.closest('[data-granularity]');if(grouping){s.resumeScroll=root().querySelector('#portal-insight-charts').scrollLeft;return load(1,{...s.applied,granularity:grouping.dataset.granularity});}
    const page=e.target.closest('[data-page]');if(page&&!page.disabled)return load(Number(page.dataset.page),s.applied,{tableOnly:true});
    const b=e.target.closest('[data-action]');if(!b)return;const action=b.dataset.action;
    if(action==='filters'){root().querySelector('dialog').showModal();dates();}if(action==='close')close();if(action==='reset'){clearTimeout(s.searchTimer);s.search='';close();load();}if(action==='retry')load(1,s.intent,s.retryOptions||{});if(action==='export')exportXlsx();if(action==='email')emailReport();if(action==='previous'||action==='next')move(action==='next'?1:-1);
    if(action==='clear'){const f={...s.applied};['chart_key','bucket_key','series_key'].forEach(k=>delete f[k]);load(1,f,{tableOnly:true});}
    if(action==='drill'){const card=b.closest('[data-chart]');drill(s.result.charts.find(c=>c.id===card.dataset.chart),card.querySelector('[data-bucket]').value,card.querySelector('[data-series]').value);}
  });
  document.addEventListener('input',e=>{if(e.target.id!=='portal-report-search'||!root()?.contains(e.target))return;clearTimeout(s.searchTimer);s.search=e.target.value;++s.sequence;s.loading=true;s.searchTimer=setTimeout(()=>load(1,{...s.applied,search:s.search}),300);});
  document.addEventListener('change',e=>{if(!root()?.contains(e.target))return;if(e.target.name==='date_mode'||e.target.matches('[data-date] input')){root().querySelector('[name="to"]')?.setCustomValidity('');dates();}if(e.target.matches('[data-bucket]'))e.target.closest('article').querySelector('[data-action="drill"]').disabled=!e.target.value;});
  document.addEventListener('submit',e=>{if(e.target.id!=='portal-report-filters')return;e.preventDefault();clearTimeout(s.searchTimer);const f={...Object.fromEntries(new FormData(e.target)),search:s.search};if(f.date_mode==='all'){delete f.month;delete f.from;delete f.to;}else if(f.date_mode==='month'){delete f.from;delete f.to;}else {delete f.month;if(f.from>f.to){e.target.elements.to.setCustomValidity('Choose an end date on or after the start date.');e.target.elements.to.reportValidity();return;}}close();load(1,f);});
  const theme=()=>{if(root()&&s.result){destroy(false);draw();}};
  window.PortalMiniAppReports={load(options={}){const returning=s.origin===root();clearTimeout(s.searchTimer);s.tg?.offEvent?.('themeChanged',theme);s.tg=options.tg||s.tg;s.tg?.onEvent?.('themeChanged',theme);s.result=null;if(!returning){s.applied={};s.search='';s.page=1;}else s.resumeScroll=s.scroll;return load(returning?s.page:1,returning?s.applied:{});},unmount(){clearTimeout(s.searchTimer);s.origin=root();s.page=s.result?.pagination.page||1;s.scroll=root()?.querySelector('#portal-insight-charts')?.scrollLeft||0;++s.sequence;window.MiniAppReportControls.closeExcelExport();close();destroy();s.tg?.offEvent?.('themeChanged',theme);s.result=null;s.loading=false;},canHandleBack(){return Boolean(document.querySelector('.miniapp-excel-dialog[open]')||root()?.querySelector('dialog')?.open);},handleBack(){if(window.MiniAppReportControls.closeExcelExport())return true;if(!this.canHandleBack())return false;close();return true;}};
})();
