(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  const state = {catalogue:null, pattern:null, detail:null, revision:null, frames:[], measures:false, sceneSeq:0, patternSeq:0, all:false, busy:false, drafts:new Map()};
  let toastTimer;
  function toast(message, tone='info') {
    $('lab-toast').textContent=message; $('lab-toast').dataset.tone=tone; $('lab-toast').hidden=false;
    clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('lab-toast').hidden=true,9000);
  }
  async function api(path, options={}) {
    const headers={'X-CSRFToken':decodeURIComponent(document.cookie.split('; ').find(value=>value.startsWith('csrftoken='))?.split('=')[1]||''),...(options.headers||{})};
    if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    if(options.body && !(options.body instanceof FormData))headers['Content-Type']='application/json';
    const response=await fetch('/ui-lab/api/'+path,{...options,headers,cache:'no-store'});
    const data=await response.json();
    if(!response.ok || data.ok===false)throw new Error(data.error||'Could not complete the review action. Try again.');
    return data;
  }
  async function blob(path) {
    const headers=tg?.initData?{'X-Telegram-Init-Data':tg.initData}:{};
    const response=await fetch(path,{headers,cache:'no-store'});
    if(!response.ok)throw new Error('Evidence could not be opened. Retry or capture it again.');
    return response.blob();
  }
  function options(node, items) {
    node.replaceChildren(...items.map(item=>new Option(item.label||item,item.id||item)));
  }
  function listPatterns() {
    const query=$('lab-search').value.trim().toLowerCase();let group='';$('pattern-list').replaceChildren();
    const filter=$('review-filter').value;
    for(const item of state.catalogue.patterns.filter(item=>(item.title+' '+item.group).toLowerCase().includes(query)&&(!filter||(item.review_status||'unreviewed')===filter))) {
      if(group!==item.group){group=item.group;const h=document.createElement('h2');h.textContent=group;$('pattern-list').append(h);}
      const button=document.createElement('button');button.type='button';button.textContent=item.title;button.dataset.pattern=item.key;
      button.append(safeText('small',({unreviewed:'Needs review',changes:'Changes requested',approved:'Approved',declined:'Declined',deferred:'Deferred',stale:'Source changed'})[item.review_status||'unreviewed']));
      button.setAttribute('aria-current',String(state.pattern?.key===item.key));button.addEventListener('click',()=>openPattern(item).catch(error=>toast(error.message,'error')));$('pattern-list').append(button);
    }
  }
  async function openPattern(item) {
    if(state.busy)return;
    if(state.pattern){const form=$('decision-form');state.drafts.set(state.pattern.key,Object.fromEntries([...new FormData(form)].map(([key,value])=>[key,value])));}
    const request=++state.patternSeq;
    const detail=await api(`patterns/${item.key}/`);if(request!==state.patternSeq)return;
    state.pattern=item;state.detail=detail;
    const form=$('decision-form');form.reset();delete form.dataset.requestKey;
    for(const [key,value]of Object.entries(state.drafts.get(item.key)||{})){const control=form.elements[key];if(control) {if(control.type==='checkbox')control.checked=value==='on';else control.value=value;}}
    state.revision=state.detail.revisions.find(revision=>revision.current)||null;
    $('pattern-title').textContent=item.title;$('pattern-group').textContent=item.group;
    options($('variant'),state.detail.manifest.variants);listPatterns();await showSpecimen();renderReview();
  }
  function safeText(tag, value) {const node=document.createElement(tag);node.textContent=value;return node;}
  function foundations() {
    const density=$('variant').value;
    const box=document.createElement('div');box.className='specimen';box.dataset.uiDensity=density;box.dataset.measures=String(state.measures);
    box.append(safeText('p','Candidate only — not an approved standard'));
    for(const [label,role] of [['Caption · 16-10-26','caption'],['Synthetic Wanjiku Mwangi-Kamau','title'],['National ID · 00000000','label'],['KES 85,000','number'],['Training address: Plot 12, near the community centre','body']]){
      const item=safeText('p',label);item.style.fontSize=`var(--ui-${role})`;box.append(item);
    }
    for(let i=0;i<3;i++) {
      const card=document.createElement('article');card.className='specimen-card';
      card.append(safeText('strong',i?'Synthetic applicant with a deliberately longer name':'Synthetic Wanjiku Mwangi-Kamau'),safeText('small','00000000 · 0700000000 · Training branch'));
      const row=document.createElement('div');row.className='specimen-row';row.append(safeText('span','KES 85,000'),safeText('span','Active · Within target'));card.append(row);box.append(card);
    }
    const label=safeText('label','Applicant name');const input=document.createElement('input');input.value='Synthetic Wanjiku';label.append(input);box.append(label);
    for(let index=1;index<=6;index++) {const row=document.createElement('div');row.className='spacing-step';const block=document.createElement('i');block.style.width=`var(--ui-space-${index})`;row.append(block,safeText('span',`space-${index} · ${[4,8,12,16,24,32][index-1]}px`));box.append(row);}
    $('specimen-host').replaceChildren(box);$('specimen-host').classList.remove('compare-grid');state.frames=[];
    if(state.all){$('specimen-host').classList.add('compare-grid');for(const other of ['compact','comfortable','spacious'].filter(value=>value!==density)){const copy=box.cloneNode(true);copy.dataset.uiDensity=other;copy.prepend(safeText('h2',other));$('specimen-host').append(copy);}}
    $('pattern-note').textContent='Compare the same content at three densities. Theme switching applies to this candidate, not to live Mini Apps.';
    $('scene-warning').textContent='These token values and the system font are proposals. No decision has been made for you.';
    $('source-info').replaceChildren(safeText('p','Source: isolated Design Lab tokens and specimen. No operational consumer yet.'));
  }
  async function showSpecimen() {
    const sequence=++state.sceneSeq;
    if(state.pattern.key==='foundations'){foundations();return;}
    const variant=$('variant').value;const scene=state.detail.manifest.variants.find(item=>item.id===variant);
    const width=$('scene-width').value==='device'?Math.max(280,$('specimen-host').clientWidth-18):Number($('scene-width').value);
    $('pattern-note').textContent='Current implementation · original source and synthetic I/O. JBL colour proposals do not override this current-app specimen.';
    $('scene-warning').textContent='Loading source specimen. Remote fonts and unmodelled journeys must be checked before approval.';
    const data=await blob(`/ui-lab/api/scenes/${variant}/${scene.scene}/?state=${encodeURIComponent($('scene-state').value)}&role=${encodeURIComponent($('scene-role').value)}`);
    if(sequence!==state.sceneSeq)return;
    const frame=document.createElement('iframe');frame.title=`${scene.label}: ${state.pattern.title}`;frame.setAttribute('sandbox','allow-scripts');frame.style.width=width+'px';
    frame.dataset.expectedSelector=scene.selector;frame.srcdoc=await data.text();if(sequence!==state.sceneSeq)return;$('specimen-host').replaceChildren(frame);state.frames=[frame];
    frame.addEventListener('load',sendTheme);
    $('source-info').replaceChildren(safeText('p',`Expected selector: ${scene.selector}. Missing or hidden elements are coverage gaps.`));
    for(const source of scene.sources){const line=safeText('code',source.path+' · '+source.sha256.slice(0,12));line.className='source-path';$('source-info').append(line);}
    if(state.all){
      $('specimen-host').classList.add('compare-grid');
      for(const alternative of state.detail.manifest.variants.filter(item=>item.id!==variant)){
        const content=await blob(`/ui-lab/api/scenes/${alternative.id}/${alternative.scene}/?state=${encodeURIComponent($('scene-state').value)}&role=${encodeURIComponent($('scene-role').value)}`);
        if(sequence!==state.sceneSeq)return;
        const next=document.createElement('iframe');next.title=alternative.label;next.dataset.expectedSelector=alternative.selector;next.setAttribute('sandbox','allow-scripts');next.style.width=width+'px';next.srcdoc=await content.text();next.addEventListener('load',sendTheme);state.frames.push(next);$('specimen-host').append(next);
      }
    }else $('specimen-host').classList.remove('compare-grid');
  }
  function sendTheme(){for(const frame of state.frames){frame.contentWindow?.postMessage({type:'ui-lab-theme',mode:window.UIStandardTheme.current().resolved},'*');frame.contentWindow?.postMessage({type:'ui-lab-expect',selector:frame.dataset.expectedSelector},'*');}}
  window.addEventListener('message',event=>{
    if(!state.frames.some(frame=>frame.contentWindow===event.source)||event.data?.type!=='ui-scene-observation')return;
    const value=event.data; $('scene-observations').textContent=JSON.stringify(value,null,2);
    const warnings=[...value.gaps];if(value.component && !value.component.visible)warnings.push('The expected component is not visible in this scene. Open it manually or mark this coverage gap.');
    $('scene-warning').textContent=warnings.length?warnings.join(' · '):'Source scene opened. Native Telegram behaviour remains unverified; verify fonts and the expected element before adoption.';
  });
  async function ensureRevision() {
    if(state.revision)return state.revision;
    const result=await api('revisions/',{method:'POST',body:JSON.stringify({pattern:state.pattern.key,fingerprint:state.pattern.fingerprint})});
    state.revision=result.revision;return state.revision;
  }
  const objectUrls=[];
  function releaseImages(){objectUrls.splice(0).forEach(url=>URL.revokeObjectURL(url));}
  function renderReview() {
    releaseImages();const revision=state.revision;
    $('revision-status').textContent=revision?`Saved revision ${revision.fingerprint.slice(0,10)} · ${revision.current?'Current source':'Source changed — historical only'}`:'No saved revision. Your first evidence or decision saves this source snapshot.';
    $('evidence-list').replaceChildren();
    for(const item of revision?.evidence||[]) {
      const figure=document.createElement('figure');const image=document.createElement('img');image.alt=`${item.variant} · ${item.state} · ${item.theme}`;
      figure.append(image,safeText('figcaption',`${item.variant} · ${item.width}px · ${item.theme} · ${item.kind}`));$('evidence-list').append(figure);
      blob(item.url).then(data=>{if(!image.isConnected)return;const url=URL.createObjectURL(data);objectUrls.push(url);image.src=url;}).catch(error=>{figure.append(safeText('p',error.message));});
    }
    $('review-history').replaceChildren();
    for(const item of state.detail.revisions){const entry=document.createElement('article');entry.append(safeText('h3',item.fingerprint.slice(0,10)+(item.current?' · Current':' · Historical')));
      for(const event of item.decisions)entry.append(safeText('p',`${event.decision}: ${event.payload.reason} · ${new Date(event.at).toLocaleString('en-GB',{timeZone:'Africa/Nairobi'})}`));$('review-history').append(entry);}
  }
  async function saving(form, callback) {
    const button=form.querySelector('[type="submit"]');if(button.disabled||state.busy)return;
    state.busy=true;button.disabled=true;
    // Inert prevents changing the comparison mid-save without excluding form
    // controls from FormData (which disabling every field would do).
    document.body.inert=true;form.setAttribute('aria-busy','true');
    try{await callback();}catch(error){toast(error.message,'error');}finally{state.busy=false;button.disabled=false;document.body.inert=false;form.removeAttribute('aria-busy');}
  }
  $('evidence-form').addEventListener('submit',event=>{event.preventDefault();const element=event.currentTarget;saving(element,async()=>{
    const revision=await ensureRevision();const form=new FormData(element);form.set('variant',$('variant').value);form.set('state',$('scene-state').value);
    for(const key of ['synthetic_only','font_verified'])form.set(key,String(element.elements[key].checked));
    const result=await api(`revisions/${revision.id}/evidence/`,{method:'POST',body:form});state.revision=result.revision;
    state.detail.revisions.unshift(result.revision);renderReview();element.reset();toast('Screenshot saved. No design approval has been recorded.');
  });});
  $('decision-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;saving(form,async()=>{
    const revision=await ensureRevision();const values=new FormData(form);const payload={variant:$('variant').value,reason:values.get('reason'),use_when:values.get('use_when'),avoid_when:values.get('avoid_when'),intentional:form.elements.intentional.checked,reviewed:form.elements.reviewed.checked};
    form.dataset.requestKey ||= crypto.randomUUID();
    const result=await api(`revisions/${revision.id}/decisions/`,{method:'POST',body:JSON.stringify({decision:values.get('decision'),payload,request_key:form.dataset.requestKey})});
    state.revision=result.revision;delete form.dataset.requestKey;state.detail.revisions=state.detail.revisions.map(item=>item.id===result.revision.id?result.revision:item);if(!state.detail.revisions.some(item=>item.id===result.revision.id))state.detail.revisions.unshift(result.revision);if(values.get('decision')!=='device')state.pattern.review_status=({adopt:'approved',approve:'approved',changes:'changes',decline:'declined',defer:'deferred'})[values.get('decision')];listPatterns();renderReview();toast('Decision saved. Live Mini Apps are unchanged.');
  });});
  $('decision-form').addEventListener('input',event=>{delete event.currentTarget.dataset.requestKey;});
  $('lab-search').addEventListener('input',listPatterns);
  $('review-filter').addEventListener('change',listPatterns);
  for(const id of ['variant','scene-state','scene-role','scene-width'])$(id).addEventListener('change',()=>showSpecimen().catch(error=>toast(error.message,'error')));
  for(const [id,direction]of [['variant-previous',-1],['variant-next',1]])$(id).addEventListener('click',()=>{const input=$('variant');input.selectedIndex=(input.selectedIndex+direction+input.options.length)%input.options.length;showSpecimen().catch(error=>toast(error.message,'error'));});
  $('compare-all').addEventListener('click',()=>{state.all=!state.all;$('compare-all').setAttribute('aria-pressed',String(state.all));showSpecimen().catch(error=>toast(error.message,'error'));});
  $('toggle-measures').addEventListener('click',()=>{state.measures=!state.measures;$('toggle-measures').setAttribute('aria-pressed',String(state.measures));const specimen=document.querySelector('.specimen');if(specimen)specimen.dataset.measures=String(state.measures);else toast('Source measurements are recorded by the audit capture tool. The spacing overlay applies to candidates only.');});
  $('toggle-grey').addEventListener('click',()=>{const on=$('toggle-grey').getAttribute('aria-pressed')!=='true';$('toggle-grey').setAttribute('aria-pressed',String(on));$('specimen-host').dataset.grey=String(on);});
  for(const id of ['lab-theme','lab-mode'])$(id).addEventListener('change',()=>{window.UIStandardTheme.apply({theme:$('lab-theme').value,mode:$('lab-mode').value});sendTheme();});
  $('diagnostics-open').addEventListener('click',()=>{$('device-values').textContent=JSON.stringify({platform:tg?.platform||'browser',version:tg?.version||null,viewport:tg?.viewportHeight||innerHeight,stableViewport:tg?.viewportStableHeight||null,safeArea:tg?.safeAreaInset||null,contentSafeArea:tg?.contentSafeAreaInset||null,theme:window.UIStandardTheme.current(),features:{back:!!tg?.BackButton,main:!!tg?.MainButton,haptics:!!tg?.HapticFeedback,download:typeof tg?.downloadFile==='function'}},null,2);$('device-dialog').showModal();});
  $('diagnostics-close').addEventListener('click',()=>$('device-dialog').close());
  const cleanups=[];
  function temporary(cleanup){cleanups.push(cleanup);setTimeout(cleanup,10000);}
  document.querySelectorAll('[data-diagnostic]').forEach(button=>button.addEventListener('click',()=>{
    const kind=button.dataset.diagnostic;
    if(!tg)return toast('Open the lab inside Telegram to test this feature.');
    if(kind==='haptic'){if(!tg.HapticFeedback)return toast('Haptics are not available.');tg.HapticFeedback.notificationOccurred('success');return toast('Vibration requested. Record whether you felt it.');}
    if(kind==='download'){if(!tg.downloadFile)return toast('Native download is unavailable on this client.');tg.downloadFile({url:new URL('/static/ui_review/diagnostic.txt',location.origin).href,file_name:'JBL Design Lab download check.txt'},accepted=>toast(accepted?'Download accepted by Telegram; verify the file on your device.':'Download cancelled or not accepted.'));return;}
    if(kind==='closing'){const before=tg.isClosingConfirmationEnabled;tg.enableClosingConfirmation?.();temporary(()=>{if(!before)tg.disableClosingConfirmation?.();});return toast('Close confirmation enabled for 10 seconds. The lab will not close itself.');}
    const native=kind==='back'?tg.BackButton:tg.MainButton;if(!native)return toast('This Telegram control is unavailable.');
    const wasVisible=native.isVisible;const oldText=native.text;const handler=()=>toast(kind==='back'?'BackButton received.':'MainButton received.');
    if(kind==='main')native.setText('Design Lab test');native.onClick(handler);native.show();temporary(()=>{native.offClick(handler);if(oldText)native.setText(oldText);if(!wasVisible)native.hide();});toast('Test control shown for 10 seconds.');
  }));
  $('prepare-release').addEventListener('click',async()=>{const button=$('prepare-release');if(button.disabled)return;button.disabled=true;try{const result=await api('releases/',{method:'POST',body:JSON.stringify({request_key:crypto.randomUUID()})});toast(`Standard v${result.version} prepared. Phase 6 is still on hold.`);await boot();}catch(error){toast(error.message,'error');}finally{button.disabled=false;}});
  window.addEventListener('pagehide',()=>{releaseImages();cleanups.splice(0).forEach(fn=>fn());});
  async function boot(){
    const result=await api('catalogue/');state.catalogue=result;$('lab-access').hidden=true;$('lab-workspace').hidden=false;
    options($('scene-state'),result.states);options($('scene-role'),result.roles);$('scene-role').value='manager';
    const theme=window.UIStandardTheme.current();$('lab-theme').value=theme.theme;$('lab-mode').value=theme.mode;
    $('lab-progress').textContent=`${result.patterns.length} patterns · Review decisions never migrate apps`;
    $('release-list').replaceChildren(...result.releases.map(item=>{const button=document.createElement('button');button.textContent=`Export standard v${item.version}`;button.onclick=async()=>{try{const data=await blob(`/ui-lab/api/releases/${item.id}/export/`);const url=URL.createObjectURL(data);const a=document.createElement('a');a.href=url;a.download=`ui-standard-v${item.version}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}catch(error){toast(error.message,'error');}};return button;}));
    listPatterns();await openPattern(result.patterns.find(item=>item.key===state.pattern?.key)||result.patterns[0]);
  }
  tg?.ready?.();tg?.expand?.();boot().catch(error=>{$('lab-access').textContent=error.message+' Sign in to Django Admin, or reopen from Telegram with your linked Superuser account.';});
})();
