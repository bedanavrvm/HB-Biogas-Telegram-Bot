/* Explicit reviewed cutover; no automatic upload, commit or stage confirmation. */
(() => {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key = () => crypto.randomUUID();
  const call = async (path, options) => {
    const result = await window.PortalMiniAppApi.apiFetch('/legacy/' + path, options, window.Telegram?.WebApp);
    if (!result.ok || !result.data?.ok) throw new Error(result.data?.legacy_detail || result.data?.error || 'Request failed. Refresh to check saved progress before retrying.');
    return result.data;
  };
  function confirmation(farmer, form, footer) {
    const legacy = farmer.legacy;
    form.innerHTML = `<section class="batch-warning"><h3>Legacy review</h3><p>Reported decision: ${escape(legacy.reported_outcome || 'Not recorded')}</p><p>Reason: ${escape(legacy.reason || 'Not recorded')}</p><p>${escape(legacy.comment)}</p><p>${escape(legacy.source_sheet)} · source row ${escape(legacy.source_row)}. Missing history remains unknown. Handover confirmation establishes the milestone, not a missing or disputed date.</p></section>`;
    if (!window.PortalAppShell?.hasCapability?.('portal.case.correct') && !document.body.dataset.legacyReviewLocal) {
      // The API independently checks current scoped Operations/IT authority.
      const caps = window.PortalLegacyCapabilities || [];
      if (!caps.includes('portal.case.correct')) { form.insertAdjacentHTML('beforeend', '<p>Operations/IT must confirm the continuation stage.</p>'); return; }
    }
    form.insertAdjacentHTML('beforeend', `<label>Confirmed continuation<select id="legacy-next-state"><option value="">Select after reviewing the evidence</option><option value="jbl_visit">JBL visit</option><option value="credit">Credit analysis</option><option value="final_review">Head of Rural review</option><option value="order">Ready for order</option><option value="ordered">Existing order / HB handover</option><option value="withdrawn">Withdrawn</option>${['rejected','deferred'].flatMap(outcome => ['jbl_visit','credit','final'].map(stage => `<option value="${outcome}:${stage}">${outcome} — ${stage}</option>`)).join('')}</select></label><label>Evidence and explanation<textarea id="legacy-stage-note" required></textarea></label><p id="legacy-confirm-feedback" role="status"></p>`);
    if (legacy.needs_hb_handover) {
      form.querySelector('#legacy-next-state').innerHTML='<option value="ordered">Confirm historical HB handover</option>';
    }
    const button = document.createElement('button'); button.className = 'primary'; button.textContent = 'Confirm legacy continuation'; button.dataset.mainAction = button.textContent;
    let requestKey = '';
    button.onclick = async () => {
      const state = form.querySelector('#legacy-next-state').value, note = form.querySelector('#legacy-stage-note').value.trim();
      const feedback = form.querySelector('#legacy-confirm-feedback');
      if (!state || !note) { feedback.textContent = 'Choose a stage and explain the source evidence.'; return; }
      button.disabled = true;
      try { await call(`rows/${legacy.row_id}/confirm/`, {method:'POST', body:JSON.stringify({state,note,revision:legacy.revision,request_id:requestKey || (requestKey=key())})}); feedback.textContent = 'Saved. Refresh this case to continue in its owning workflow.'; }
      catch (error) { feedback.textContent = error.message; button.disabled = false; }
    };
    footer.append(button);
  }
  async function init() {
    const root = document.getElementById('legacy-import-workspace');
    if (!root || root.dataset.initialized) return;
    root.dataset.initialized = 'true';
    const feedback = root.querySelector('[data-feedback]'), rowsEl = root.querySelector('[data-rows]');
    let batch = '', offset = 0, current = [], busy = false;
    const drafts = new Map();
    function lock(value) {
      busy = value;
      root.querySelectorAll('form input,form select,form button,[data-batches]').forEach(node=>{node.disabled=value;});
      for (const row of current) {
        const checkbox=rowsEl.querySelector(`[data-row="${row.id}"]`); if(checkbox)checkbox.disabled=value||row.committed;
        rowsEl.querySelectorAll(`[data-match="${row.id}"],[data-note="${row.id}"]`).forEach(node=>{node.disabled=value;});
      }
    }
    const show = message => { feedback.textContent = message; };
    async function load() {
      for(const row of current)if(!row.committed)drafts.set(row.id,{checked:rowsEl.querySelector(`[data-row="${row.id}"]`)?.checked,match:rowsEl.querySelector(`[data-match="${row.id}"]`)?.value,note:rowsEl.querySelector(`[data-note="${row.id}"]`)?.value});
      const data = await call(`batches/${batch}/?offset=${offset}`); current = data.rows;
      rowsEl.innerHTML = data.rows.map(row => `<article class="case360-section"><label><input type="checkbox" data-row="${row.id}" ${row.committed?'disabled':''}> ${escape(row.sheet)} row ${row.source_row} · ${escape(row.name)} ${row.committed?'— Saved':''}</label><p>${escape(row.proposal.state)} · ${escape(row.proposal.evidence.join('; ') || 'Stage not established')}</p><p>${escape(row.proposal.issues.join('; '))}</p><details><summary>Reviewed source values</summary><div class="case360-grid">${Object.entries(row.source_values || {}).filter(([,value])=>value && value!=='-').map(([label,value])=>`<div><strong>${escape(label.replace(/_/g,' '))}</strong><p>${escape(value)}</p></div>`).join('')}</div></details>${!row.committed && (row.identity_collision || row.existing_cases.length || row.proposal.fields.case_id) ? `<label>Existing case ID (leave blank for a separately confirmed unit)<input data-match="${row.id}" value="${escape(row.proposal.fields.case_id || '')}"></label><p>${escape(row.existing_cases.map(c=>c.reference+' '+c.id).join('; '))}</p><label>Reconciliation / separate-unit explanation<input data-note="${row.id}"></label>`:''}</article>`).join('');
      root.querySelector('[data-prev]').disabled = offset === 0;
      root.querySelector('[data-next]').disabled = offset + 50 >= data.total;
      for(const row of current){const draft=drafts.get(row.id);if(row.committed){drafts.delete(row.id);continue;}if(!draft)continue;rowsEl.querySelector(`[data-row="${row.id}"]`).checked=!!draft.checked;for(const [attribute,field] of [['match','match'],['note','note']]){const node=rowsEl.querySelector(`[data-${attribute}="${row.id}"]`);if(node&&draft[field]!==undefined)node.value=draft[field];}}
      show(`${data.committed} of ${data.total} saved. Showing ${offset+1}–${offset+data.rows.length}. Review and select rows before committing.`);
    }
    async function index() {
      const data = await call('');
      root.querySelector('[name=group_id]').innerHTML = '<option value="">Choose Portal owner</option>'+data.groups.map(g=>`<option value="${escape(g.id)}">${escape(g.label)}</option>`).join('');
      root.querySelector('[data-batches]').innerHTML = '<option value="">Resume a staged workbook</option>'+data.batches.map(b=>`<option value="${b.id}">${escape(b.namespace)}</option>`).join('');
    }
    root.querySelector('form').onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      const body=new FormData(event.currentTarget); lock(true); show('Staging reviewed values…');
      try { const data = await call('stage/', {method:'POST',body}); batch=data.id; offset=0; current=[]; drafts.clear(); await load(); }
      catch(error) { show(error.message); } finally { lock(false); }
    };
    root.querySelector('[data-batches]').onchange = async event => { if(busy || !event.target.value)return; batch=event.target.value; offset=0; try{await load();}catch(error){show(error.message);} };
    for(const [attr,delta] of [['prev',-50],['next',50]])root.querySelector(`[data-${attr}]`).onclick=async()=>{if(busy||!batch)return;offset=Math.max(0,offset+delta);try{await load();}catch(error){show(error.message);}};
    root.querySelector('[data-select]').onclick=()=>rowsEl.querySelectorAll('input[data-row]:not(:disabled)').forEach(c=>{c.checked=true;});
    root.querySelector('[data-refresh]').onclick=async()=>{if(busy||!batch)return;try{await load();}catch(error){show(error.message);}};
    root.querySelector('[data-commit]').onclick=async()=>{
      if(busy||!batch)return;
      const selected = current.filter(r=>rowsEl.querySelector(`[data-row="${r.id}"]`)?.checked);
      if(!selected.length){show('Select reviewed rows first.');return;}
      if(!window.confirm(`Import ${selected.length} reviewed legacy records? This saves to Django; Sheet publication stays held.`))return;
      lock(true);
      try{
        const data=await call(`batches/${batch}/`,{method:'POST',body:JSON.stringify({request_id:key(),rows:selected.map(r=>({id:r.id,revision:r.revision,existing_case_id:rowsEl.querySelector(`[data-match="${r.id}"]`)?.value || '',note:rowsEl.querySelector(`[data-note="${r.id}"]`)?.value || ''}))})});
        await load(); const errors=data.results.filter(r=>!r.ok); show(`${data.results.length-errors.length} saved; ${errors.length} held. ${[...new Set(errors.map(r=>r.error))].slice(0,3).join(' ')}`);
      }catch(error){show(error.message);}finally{lock(false);}
    };
    try { await index(); } catch(error) { show(error.message); }
  }
  window.PortalLegacy = {init, confirmation};
  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('portal:screen-changed', init);
})();
