(function () {
  'use strict';
  const mounts = new WeakMap();
  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
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
    let page = 1, busy = false, rows = [], sequence = 0;
    const keys = new Map();
    host.classList.add('miniapp-recovery');
    host.innerHTML = '<header><h2>App status</h2><button type="button" data-check aria-label="Check app status" title="Check status">↻</button></header><div data-recovery-content aria-live="polite"></div>';
    if (options.variant === 'portal') host.classList.add('portal-recovery');
    const content = host.querySelector('[data-recovery-content]');
    const notify = (message, kind = 'info') => options.notify?.(message, kind);
    async function refresh() {
      if (busy) return;
      const version = ++sequence;
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
        content.innerHTML = rows.length ? `<div class="recovery-list">${rows.map((row, index) => `<article class="recovery-row"><div class="recovery-copy"><strong>${escape(row.title)}</strong><span>${escape(row.detail)}</span><small class="recovery-state">${escape(row.status)}</small></div><div class="recovery-actions">${row.action ? `<button type="button" data-repair="${index}">${escape(row.action.label)}</button>` : ''}<button type="button" data-guide="${index}" aria-label="Help with ${escape(row.title)}" title="What to do">?</button></div></article>`).join('')}</div>` : '<p class="recovery-empty">No updates need attention.</p>';
        if (options.variant === 'portal') {
          const counts = payload.summary || {};
          content.insertAdjacentHTML('afterbegin', `<p class="recovery-explanation">Your work is saved in Portal. This shows updates to Sheets, files and report delivery.</p><div class="portal-recovery-summary">${[['waiting','Waiting'],['processing','Processing'],['needs_attention','Needs attention']].map(([key,label]) => `<span><strong>${Number(counts[key] || 0)}</strong>${label}</span>`).join('')}</div><small class="recovery-checked">Checked just now</small>`);
          content.querySelectorAll('.recovery-row').forEach((node, index) => {
            const row = rows[index];
            node.dataset.status = row.status_code || 'needs_attention';
            const details = document.createElement('details');
            details.className = 'recovery-details';
            details.innerHTML = `<summary>What to do</summary><ol>${(row.steps || []).map(step => `<li>${escape(step)}</li>`).join('')}</ol><small>Support reference: ${escape(row.reference)}</small>`;
            node.appendChild(details);
            node.querySelector('[data-guide]')?.remove();
          });
        }
        if (paging.pages > 1) content.insertAdjacentHTML('beforeend', `<nav aria-label="App status pages"><button type="button" data-page="${page-1}" aria-label="Previous status page" ${page === 1 ? 'disabled' : ''}>‹</button><span>${page} / ${escape(paging.pages)} · ${escape(paging.total)} updates</span><button type="button" data-page="${page+1}" aria-label="Next status page" ${page >= paging.pages ? 'disabled' : ''}>›</button></nav>`);
      } catch (error) {
        content.innerHTML = `<p role="alert">${escape(error.message || 'App status could not be checked. Try again.')}</p><button type="button" data-check>Try again</button>`;
      } finally {
        content.removeAttribute('aria-busy');
        host.querySelector('[data-check]').disabled = false;
      }
    }
    host.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
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
        if (!await dialog(action.label, `<p>${escape(action.confirmation)}</p>`, action.label)) return;
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
      finally { busy = false; button.disabled = false; button.removeAttribute('aria-busy'); await refresh(); }
    });
    const api = {refresh}; mounts.set(host, api); refresh(); return api;
  }
  window.MiniAppRecovery = {mount, confirm: (title, message) => dialog(title, `<p>${escape(message)}</p>`, title),
    closeTop: () => { const node = [...document.querySelectorAll('.recovery-dialog[open]')].at(-1); if (!node) return false; node.close(); return true; }};
})();
