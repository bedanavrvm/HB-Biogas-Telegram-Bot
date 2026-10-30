(() => {
 'use strict';
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const params=new URLSearchParams(location.search);
 const behaviours={
  '01':['The existing Home, Pipeline, Cases and More hubs remain. Preview navigation links only to local design options.','Typography, action spacing and viewport-safe positioning are the proposed changes.'],
  '02':['Search narrows the local list; no results offers Clear search.','Names wrap; identifiers and the next authorized action stay visible.'],
  '03':['Changing credit outcome reveals reason/comment or iMAB fields. A rejection still requires its reason.','B uses optional task sections and preserves entered values. No extra required step.','Evidence selection stays local; the preview requests no camera or location.'],
  '04':['Open FarmUp demonstrates a handoff, not a stage advance.','Case identity and the required new JBL visit remain explicit.'],
  '05':['Source setup starts collapsed; search and held-row filters operate in memory.','Selection is explicit. Held rows are not committed and warnings are not acknowledged automatically.','FarmUp intake and SysUp customer matching retain separate semantics.'],
  '06':['Equal displayed lead/applicant facts share a summary without merging backend identities. Their roles remain inspectable.','A mismatched national ID remains a hold. Verification needs the existing note and authority.'],
  '07':['Agreement and replacement remain separate. Accepted agreement is not a corrected invoice.','Nonmatching IDs and invoices matched elsewhere cannot be selected.','Closure preserves history and does not approve identity.'],
  '08':['Search and status filtering reduce batch scrolling.','Cash and Loan–Jawabu are explicit. No bulk approval or automatic decision.','B opens focused details; A retains expandable cards.'],
  '09':['Review complete, awaiting scan and completed are separate comparisons with retained totals.','Operations sees the configured-role handoff; completed payment exposes retained signed evidence.','The preview allocates no payment number and attests no scan.'],
  '10':['Preview navigation uses actual retained synthetic page images. Zoom scrolls inside the document.','Reused numbers do not merge independent workspaces.','Official workbook and signed-scan bytes stay unchanged.'],
  '11':['Scope, metrics and case results stay together; the 2,000-case table/export limit stays visible.','Fresh loaded Performance baseline: one officer, nine cases/visits and 20 points.','Period controls can demonstrate an explicitly labelled empty preview period.'],
  '12':['Retry retains file and confirmation. Simulated access restoration is a review control, not an operational grant.','Publication separates saved Django records from queued Google updates.'],
  '13':['Preferences are local; identity and grants remain administrator-owned.','The six recorded recovery items stay distinct. Reviewed retry preserves failed history.']
 };
 const imagePath=(s,v)=>v==='before'?`assets/before/${s.id}.png`:`assets/after/${s.id}-${v}.png`;
 const panel=(s,v,board=false)=>{
  const label=v==='before'?'Before · Actual Portal':v==='a'?'A · Refinement':'B · Redesign';
  const description=v==='before'?'Captured existing implementation':PORTAL_UX.groups.find(g=>g.id===s.group)[v];
  return `<div class="compare-panel" data-panel="${v}"><div class="panel-label">${label}<span>${s.width} × 844</span></div>${board?`<p class="direction-brief">${escape(description)}</p>`:''}<div class="phone-frame"><img loading="${board?'eager':'lazy'}" src="${imagePath(s,v)}" alt="${escape(label+': '+s.title)}" data-zoom></div>${board?'':`<div class="panel-links"><a href="${imagePath(s,v)}" target="_blank" rel="noopener">Full-size image</a>${v!=='before'?`<a href="preview.html?case=${s.id}&variant=${v}" target="_blank" rel="noopener">Interactive preview ↗</a>`:''}</div>`}</div>`;
 };
 const caption=s=>`<div class="comparison-caption"><strong>${escape(s.role)}</strong> · ${escape(s.state)}<br>Same scenario in all three views. After images are proposed layouts, not evidence of a completed workflow.</div>`;
 const boardCase=PORTAL_UX.scenarios.find(s=>s.id===params.get('board'));
 if(boardCase){
  const g=PORTAL_UX.groups.find(g=>g.id===boardCase.group);document.body.className='board-page';
  document.body.innerHTML=`<h1 class="board-title">${g.id} · ${escape(boardCase.title)}</h1><p class="board-subtitle">${escape(g.problem)}</p><section class="${boardCase.width>600?'desktop':''}"><div class="comparisons">${['before','a','b'].map(v=>panel(boardCase,v,true)).join('')}</div>${caption(boardCase)}</section><p class="board-foot">JBL Portal design review · Baseline 29 October 2026 · Source 53b4e8fa · Synthetic only · Proposed A/B options are not approved or deployed.</p>`;
  document.title=boardCase.title+' · Before / A / B';return;
 }
 document.getElementById('group-nav').innerHTML=PORTAL_UX.groups.map(g=>`<a href="#group-${g.id}"><span>${g.id}</span>${escape(g.title)}</a>`).join('');
 const mode=innerWidth<600?'before':'all';
 document.getElementById('recommendations').innerHTML=PORTAL_UX.groups.map(g=>`<section class="recommendation" id="group-${g.id}" data-review-text="${escape((g.title+' '+g.problem).toLowerCase())}"><div class="recommendation-heading"><span class="number">${g.id}</span><div><h2>${escape(g.title)} <span class="priority">${g.priority}</span></h2><p class="problem">${escape(g.problem)}</p></div></div><div class="directions"><div class="direction"><h3>A · Refinement</h3><p>${escape(g.a)}</p></div><div class="direction"><h3>B · Redesign</h3><p>${escape(g.b)}</p></div></div><div class="recommendation-note"><strong>My recommendation: ${g.recommended}.</strong> ${escape(g.reason)}</div>${PORTAL_UX.scenarios.filter(s=>s.group===g.id).map(s=>`<article class="scenario ${s.width>600?'desktop':''}" id="scenario-${s.id}" data-mode="${s.width>600?'before':mode}"><header class="scenario-header"><div><h3>${escape(s.title)}</h3><p>${escape(s.role)} · ${escape(s.state)}</p></div><a href="assets/boards/${s.id}.png" target="_blank" rel="noopener">Comparison board ↗</a></header><div class="compare-controls"><div class="view-modes" aria-label="Choose comparison view">${[['before','Before'],['a','A · Refine'],['b','B · Redesign'],['all','All three']].map(([v,t])=>`<button type="button" data-mode-button="${v}" class="${(s.width>600?'before':mode)===v?'active':''}" aria-pressed="${(s.width>600?'before':mode)===v}">${t}</button>`).join('')}</div><small>Click an image to enlarge</small></div><div class="comparisons">${['before','a','b'].map(v=>panel(s,v)).join('')}</div>${caption(s)}<details class="behaviour"><summary>Interaction and workflow boundaries</summary><ul>${behaviours[g.id].map(b=>`<li>${escape(b)}</li>`).join('')}</ul></details>${['farmup','payment-list','upload-error'].includes(s.id)?`<div class="supplementary"><strong>Responsive views:</strong>${['a','b'].map(v=>`<a href="assets/responsive/${s.id}-${v}-320.png" target="_blank">${v.toUpperCase()} at 320px</a>${s.id!=='upload-error'?`<a href="assets/responsive/${s.id}-${v}-1280.png" target="_blank">${v.toUpperCase()} at 1280px</a>`:''}`).join('')}</div>`:''}${['invoice','payment-done','upload-error'].includes(s.id)?`<div class="supplementary"><strong>Dark theme:</strong><a href="assets/responsive/${s.id}-a-dark.png" target="_blank">A · Dark</a><a href="assets/responsive/${s.id}-b-dark.png" target="_blank">B · Dark</a></div>`:''}</article>`).join('')}</section>`).join('');
 document.addEventListener('click',event=>{
  const modeButton=event.target.closest('[data-mode-button]');
  if(modeButton){const scenario=modeButton.closest('.scenario');scenario.dataset.mode=modeButton.dataset.modeButton;scenario.querySelectorAll('[data-mode-button]').forEach(b=>{b.classList.toggle('active',b===modeButton);b.setAttribute('aria-pressed',String(b===modeButton));});return;}
  const img=event.target.closest('img[data-zoom]');if(img){document.getElementById('large-image').src=img.src;document.getElementById('large-image').alt=img.alt;document.getElementById('image-viewer').showModal();}
 });
 document.getElementById('close-image').addEventListener('click',()=>document.getElementById('image-viewer').close());
 document.getElementById('image-viewer').addEventListener('click',event=>{if(event.target===event.currentTarget)event.currentTarget.close();});
 document.getElementById('review-search').addEventListener('input',event=>{const query=event.target.value.toLowerCase();document.querySelectorAll('[data-review-text]').forEach(n=>n.hidden=!n.dataset.reviewText.includes(query));});
})();
