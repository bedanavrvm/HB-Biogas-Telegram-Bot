(function () {
  'use strict';
  const mounts = new WeakMap();
  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function changesHtml(row) {
    if (!row.comparison_basis) return '';
    const render = change => `<div class="recovery-change"><strong>${escape(change.field)}</strong><span><span class="recovery-before">${escape(change.before === null ? 'Not recorded' : change.before === '' ? '(Blank)' : change.before)}</span> <span aria-label="changes to">→</span> <span class="recovery-after">${escape(change.after === '' ? '(Blank)' : change.after)}</span></span></div>`;
    const changes=(row.changes||[]).filter(change=>change.before!==null).map(render);
    const unknown=(row.changes||[]).filter(change=>change.before===null).map(render);
    return `<div class="recovery-changes"><small>${escape(row.comparison_basis)}</small>${changes.slice(0,3).join('')}${changes.length > 3 ? `<details><summary>${changes.length-3} more changes</summary>${changes.slice(3).join('')}</details>` : ''}${unknown.length?`<details><summary>${unknown.length} saved values without a recorded Sheet comparison</summary>${unknown.join('')}</details>`:''}${!changes.length&&!unknown.length ? '<p>No retained field differences. Retry checks the current saved row.</p>' : ''}</div>`;
  }
  function dialog(title, body, confirmLabel) {
    return new Promise(resolve => {
      const node = document.createElement('dialog');
      node.className = 'recovery-dialog';
      node.innerHTML = `<form method="dialog"><header><h2>${escape(title)}</h2><button value="cancel" aria-label="Close">×</button></header>${body}<footer><button value="cancel">${confirmLabel ? 'Cancel' : 'Close'}</button>${confirmLabel ? `<button value="confirm">${escape(confirmLabel)}</button>` : ''}</footer></form>`;
      document.body.append(node);
      const back = window.Telegram?.WebApp?.BackButton;
      const backWasVisible = back?.isVisible;
      node.addEventListener('close', () => {
        resolve(node.returnValue === 'confirm'); node.remove();
        if (backWasVisible === false) back?.hide?.();
        window.dispatchEvent(new Event('miniapp:recovery-dialog-change'));
      }, {once:true});
      node.showModal();
      back?.show?.();
      window.dispatchEvent(new Event('miniapp:recovery-dialog-change'));
    });
  }
  function mount(host, options) {
    if (!host) return null;
    if (mounts.has(host)) { const current = mounts.get(host); current.refresh(); return current; }
    let page = 1, busy = false, rows = [], sequence = 0, progress = '', stopping = false, wakeWait = null;
    const keys = new Map(), selected = new Map();
    host.classList.add('miniapp-recovery');
    host.innerHTML = '<header><h2>App status</h2><button type="button" data-check aria-label="Check app status" title="Check status">↻</button></header><div data-recovery-content aria-live="polite"></div>';
    if (options.variant === 'portal') host.classList.add('portal-recovery');
    const content = host.querySelector('[data-recovery-content]');
    const notify = (message, kind = 'info') => options.notify?.(message, kind);
    async function refresh() {
      if (busy) return;
      const version = ++sequence;
      host.querySelectorAll('button,input').forEach(node=>{node.disabled=true;});
      host.querySelector('[data-check]').disabled = true;
      content.setAttribute('aria-busy', 'true');
      try {
        const result = await options.load(page);
        if (version !== sequence) return;
        const payload = result?.data?.items ? result.data : result;
        if (!payload || !Array.isArray(payload.items)) throw new Error('App status could not be checked. Try again.');
        rows = payload.items;
        const paging = payload.pagination || {};
        page = Number(paging.page || 1);
        rows.forEach(row => { if (selected.has(row.key)) { if (row.batch_retry) selected.set(row.key,row); else selected.delete(row.key); } });
        content.innerHTML = rows.length ? `<div class="recovery-list">${rows.map((row, index) => `<article class="recovery-row"><div class="recovery-copy"><strong>${row.batch_retry ? `<label class="recovery-select"><input type="checkbox" data-select="${index}" aria-label="Select ${escape(row.title)}" ${selected.has(row.key)?'checked':''}>${escape(row.title)}</label>` : escape(row.title)}</strong><span>${escape(row.detail)}</span><small class="recovery-state">${escape(row.status)}${row.destination?' · '+escape(row.destination):''}</small>${row.waiting_reason?`<small>${escape(row.waiting_reason)}</small>`:''}${changesHtml(row)}</div><div class="recovery-actions">${row.action ? `<button type="button" data-repair="${index}">${escape(row.action.label)}</button>` : ''}<button type="button" data-guide="${index}" aria-label="Help with ${escape(row.title)}" title="What to do">?</button></div></article>`).join('')}</div>` : '<p class="recovery-empty">No updates need attention.</p>';
        if (options.variant === 'portal') {
          const counts = payload.summary || {};
          content.insertAdjacentHTML('afterbegin', `<div class="portal-recovery-summary">${[['waiting','Waiting'],['processing','Processing'],['needs_attention','Needs attention']].map(([key,label]) => `<span><strong>${Number(counts[key] || 0)}</strong>${label}</span>`).join('')}</div><small class="recovery-checked">Checked just now</small>`);
          content.querySelectorAll('.recovery-row').forEach((node, index) => {
            const row = rows[index];
            node.dataset.status = row.status_code || 'needs_attention';
            if (row.comparison_basis) {
              node.querySelector('[data-guide]')?.remove();
              return;
            }
            const details = document.createElement('details');
            details.className = 'recovery-details';
            details.innerHTML = `<summary>What to do</summary><ol>${(row.steps || []).map(step => `<li>${escape(step)}</li>`).join('')}</ol><small>Support reference: ${escape(row.reference)}</small>`;
            node.appendChild(details);
            node.querySelector('[data-guide]')?.remove();
          });
        }
        if (rows.some(row=>row.batch_retry) || selected.size) {
          content.insertAdjacentHTML('afterbegin', `<div class="recovery-batch"><label class="recovery-select"><input type="checkbox" data-select-page aria-label="Select displayed Sheet updates">Select displayed</label><button type="button" data-retry-selected ${selected.size?'':'disabled'}>Retry selected (${selected.size})</button><button type="button" data-stop-retry hidden>Stop retrying</button><small data-batch-progress role="status">${escape(progress)}</small></div>`);
          updateSelection();
        } else if (progress) content.insertAdjacentHTML('afterbegin',`<p data-batch-progress role="status">${escape(progress)}</p>`);
        if (paging.pages > 1) content.insertAdjacentHTML('beforeend', `<nav aria-label="App status pages"><button type="button" data-page="${page-1}" aria-label="Previous status page" ${page === 1 ? 'disabled' : ''}>‹</button><span>${page} / ${escape(paging.pages)} · ${escape(paging.total)} updates</span><button type="button" data-page="${page+1}" aria-label="Next status page" ${page >= paging.pages ? 'disabled' : ''}>›</button></nav>`);
      } catch (error) {
        content.innerHTML = `<p role="alert">${escape(error.message || 'App status could not be checked. Try again.')}</p><button type="button" data-check>Try again</button>`;
      } finally {
        content.removeAttribute('aria-busy');
        host.querySelector('[data-check]').disabled = false;
      }
    }
    function updateSelection() {
      const available = rows.filter(row=>row.batch_retry);
      const checked = available.filter(row=>selected.has(row.key)).length;
      const all = host.querySelector('[data-select-page]');
      if (all) { all.checked=available.length>0&&checked===available.length; all.indeterminate=checked>0&&checked<available.length; all.disabled=!available.length; }
      const button=host.querySelector('[data-retry-selected]');
      if (button) { button.disabled=!selected.size; button.textContent=`Retry selected (${selected.size})`; }
    }
    host.addEventListener('change',event=>{
      if (busy) return;
      const input=event.target;
      if (input.hasAttribute('data-select-page')) {
        rows.filter(row=>row.batch_retry).forEach(row=>input.checked?selected.set(row.key,row):selected.delete(row.key));
        host.querySelectorAll('[data-select]').forEach(node=>{node.checked=selected.has(rows[Number(node.dataset.select)].key);});
      } else if (input.dataset.select!==undefined) {
        const row=rows[Number(input.dataset.select)];
        if (row?.batch_retry) { if(input.checked)selected.set(row.key,row);else selected.delete(row.key); }
      } else return;
      updateSelection();
    });
    async function retry(row) {
      const action=row.action;
      if (!action || !action.endpoint.startsWith(options.prefix) || action.endpoint.includes('..')) throw new Error('This retry is unavailable. Refresh status.');
      if (!keys.has(row.key)) keys.set(row.key,window.MiniAppUtils?.createRequestId?.('recovery')||window.crypto.randomUUID());
      try {
        const result=await options.request(action.endpoint,{...action.payload,client_request_id:keys.get(row.key)});
        const data=result?.data||result;
        if ((result?.ok===false||data?.ok===false)&&!data?.pending_retry) {
          const error=new Error(data?.error||data?.message||'The update could not be retried.');error.status=result.status;throw error;
        }
        keys.delete(row.key);
        row.retry_wait = {reason:data?.deferred_reason, seconds:Number(data?.retry_after_seconds||0), message:data?.waiting_reason||''};
        if (data?.operation_id&&data.operation_id!==row.key&&selected.has(row.key)) {
          selected.delete(row.key);selected.set(data.operation_id,{...row,key:data.operation_id,action:{...action,payload:{...action.payload,operation_id:data.operation_id}}});
        }
        if(data?.case?.sync_status==='failed'||data?.needs_attention||data?.attempt_failed)throw new Error('The Sheet update still needs attention. Its latest failure is shown below.');
        if(data?.publication ? data.publication.operations?.some(operation=>operation.id===data.operation_id&&operation.status==='synced') : data?.case?.sync_status==='success'||data?.status==='succeeded') { selected.delete(row.key);selected.delete(data?.operation_id);return 'synced'; }
        return 'waiting';
      } catch(error) {
        if(error.status>=400&&error.status<500) keys.delete(row.key);
        throw error;
      }
    }
    function showProgress(message) {
      progress=message;const status=host.querySelector('[data-batch-progress]');if(status)status.textContent=progress;
    }
    async function retryWithPacing(row, label) {
      const stop=host.querySelector('[data-stop-retry]');if(stop){stop.hidden=false;stop.disabled=false;}
      while(!stopping) {
        const outcome=await retry(row);
        if(outcome==='synced'||!['pacing','provider_backoff','circuit_cooldown','fifo','active_worker'].includes(row.retry_wait?.reason)||!row.retry_wait.seconds)return outcome;
        if(stopping)return 'waiting';
        const deadline=Date.now()+Math.min(600,Math.max(1,row.retry_wait.seconds))*1000;
        let timer;
        await new Promise(resolve=>{wakeWait=resolve;const tick=()=>{const remaining=Math.ceil((deadline-Date.now())/1000);
          if(stopping||!host.isConnected||remaining<=0){if(!host.isConnected)stopping=true;resolve();return;}
          showProgress(`${label} · Retry in ${remaining}s · ${row.retry_wait.message||'Waiting for the Sheet write interval.'}`);
          timer=window.setTimeout(tick,1000);};tick();});
        window.clearTimeout(timer);wakeWait=null;
      }
      return 'waiting';
    }
    async function retrySelected() {
      if(busy||!selected.size)return;
      busy=true;stopping=false;const batch=[...selected.values()].sort((a,b)=>Number(a.retry_replacement)-Number(b.retry_replacement)||String(a.queued_at||'').localeCompare(String(b.queued_at||''))||a.key.localeCompare(b.key));
      let completed=0,waiting=0,failed=0;
      host.querySelectorAll('button,input').forEach(node=>{node.disabled=true;});
      try {
        for (const [index,row] of batch.entries()) {
          if(stopping)break;
          try { (await retryWithPacing(row,`${completed}/${batch.length} synced`))==='synced'?completed++:waiting++; }
          catch (error) { failed++;if(error.status===401||error.status===403)stopping=true; }
          showProgress(`${index+1}/${batch.length} checked · ${completed} synced · ${waiting} waiting · ${failed} failed`);
        }
        if(stopping)showProgress(`Stopped · ${completed} synced · ${batch.length-completed-failed} waiting · ${failed} failed`);
        notify(progress,failed?'warning':'info');
      } finally {
        busy=false;host.querySelectorAll('button,input').forEach(node=>{node.disabled=false;});
        options.afterRetry?.();await refresh();
      }
    }
    host.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if(button.hasAttribute('data-stop-retry')) { stopping=true;wakeWait?.();showProgress('Stopping after the current request…');return; }
      if (busy) return;
      if (button.hasAttribute('data-retry-selected')) return retrySelected();
      if (button.hasAttribute('data-check')) return refresh();
      if (button.hasAttribute('data-page')) { page = Number(button.dataset.page); return refresh(); }
      const guide = button.dataset.guide;
      if (guide !== undefined) {
        const row = rows[Number(guide)];
        const node = document.createElement('div');
        node.innerHTML = `<ol>${(row.steps || []).map(text => `<li>${escape(text)}</li>`).join('')}</ol><p class="recovery-reference">Support reference: ${escape(row.reference)}</p><button type="button" data-copy>Copy support reference</button>`;
        const promise = dialog('What to do', node.innerHTML);
        document.querySelector('.recovery-dialog [data-copy]')?.addEventListener('click', async () => {
          try { await navigator.clipboard.writeText(row.reference); notify('Support reference copied.'); }
          catch (_) { notify('Select and copy the support reference shown.', 'warning'); }
        });
        return promise;
      }
      if (button.dataset.repair === undefined || busy) return;
      const row = rows[Number(button.dataset.repair)], action = row?.action;
      if (!action || !action.endpoint.startsWith(options.prefix) || action.endpoint.includes('..')) return;
      busy = true;
      try {
        if (!row.batch_retry && !await dialog(action.label, `<p>${escape(action.confirmation)}</p>`, action.label)) return;
        if (row.batch_retry) {
          stopping=false;
          host.querySelectorAll('button,input').forEach(node=>{node.disabled=true;});
          const outcome=await retryWithPacing(row,'Retrying Sheet update');
          showProgress(outcome==='synced'?'1 synced':stopping?'Retry stopped. The update remains queued.':row.retry_wait?.message||'Still queued.');
          notify(outcome==='synced'?'Sheet updated.':stopping?'Retry stopped. The update remains saved and queued.':row.retry_wait?.message||'Still queued: check the waiting reason below.');
          return;
        }
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        if (!keys.has(row.key)) keys.set(row.key, window.MiniAppUtils?.createRequestId?.('recovery')
          || window.crypto?.randomUUID?.() || `recovery-${Date.now()}-${Math.random().toString(16).slice(2)}`);
        const result = await options.request(action.endpoint, {...action.payload, client_request_id: keys.get(row.key)});
        const data = result?.data || result;
        if ((result?.ok === false || data?.ok === false) && !data?.pending_retry) {
          if (result?.status >= 400 && result.status < 500) keys.delete(row.key);
          throw new Error(data?.error || data?.message || 'The update could not be retried.');
        }
        keys.delete(row.key);
        if (data?.case?.sync_status === 'failed' || data?.needs_attention) throw new Error('The update still needs attention. Open its help for the next step.');
        notify(data?.case?.sync_status === 'success' || data?.status === 'succeeded' ? 'Update completed.' : 'Retry requested. Check status for the result.');
      } catch (error) {
        // Retain the key after a timeout/unknown result; a confirmed rejection
        // can use a new attempt after its permissions/configuration are fixed.
        if (error.status >= 400 && error.status < 500) keys.delete(row.key);
        notify(error.message || 'The update could not be retried.', 'error');
      }
      finally { busy = false; button.disabled = false; button.removeAttribute('aria-busy'); const stop=host.querySelector('[data-stop-retry]');if(stop)stop.hidden=true;options.afterRetry?.(); await refresh(); }
    });
    if (options.variant==='portal') window.addEventListener('portal:publication-updated',refresh);
    const api = {refresh}; mounts.set(host, api); refresh(); return api;
  }
  window.MiniAppRecovery = {mount, confirm: (title, message) => dialog(title, `<p>${escape(message)}</p>`, title),
    closeTop: () => { const node = [...document.querySelectorAll('.recovery-dialog[open]')].at(-1); if (!node) return false; node.close(); return true; }};
})();
