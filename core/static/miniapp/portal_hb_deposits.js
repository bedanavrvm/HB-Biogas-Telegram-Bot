(function () {
  'use strict';
  let deps = {}, detail = null, pending = null, protection = null, loadVersion = 0;
  const el = id => document.getElementById(id);
  const esc = value => deps.escapeHtml(String(value ?? ''));
  const money = value => value === null || value === undefined ? 'Not recorded' : Number.isFinite(Number(value)) ? `KES ${Number(value).toLocaleString('en-KE', {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : `Unrecognized amount: ${String(value)}`;
  function error(message) {
    const target = el('hb-deposit-error');
    if (target) { target.textContent = message; target.hidden = !message; }
  }
  function render(data) {
    detail = data;
    el('hb-deposit-loading').hidden = true;
    el('hb-deposit-content').hidden = false;
    el('hb-deposit-identity').textContent = [data.customer_name, data.case_reference, data.branch].filter(Boolean).join(' · ');
    el('hb-deposit-summary').innerHTML = `<div><span>Outstanding</span><strong>${esc(money(data.shortfall))}</strong></div><div><span>HB deposit date</span><strong>${esc(data.deposit_date ? data.deposit_date.split('-').reverse().join('-') : 'Not recorded')}</strong></div>`;
    el('hb-deposit-status').textContent = data.visit_recorded ? 'Visit recorded · deposit history is read-only.' : data.deposit_hold ? data.reason : 'Deposit cleared for JBL visit.';
    if (!data.can_edit && !data.visit_recorded) el('hb-deposit-status').textContent += ' This record is read-only in HB Deposits.';
    el('hb-deposit-amount').value = data.recorded_amount ?? '';
    el('hb-deposit-reason').value = '';
    if (el('hb-deposit-reason-row')) el('hb-deposit-reason-row').hidden = true;
    ['hb-deposit-amount', 'hb-deposit-reason', 'hb-deposit-save'].forEach(id => { el(id).disabled = !data.can_edit; });
    const activity = data.activity || [];
    el('hb-deposit-activity-count').textContent = `(${activity.length})`;
    el('hb-deposit-activity').innerHTML = activity.length ? activity.map(item => {
      const observed = item.action === 'hb_deposit_import_observed';
      const before = item.old_values?.deposit_paid_hbg;
      const after = observed ? item.new_values?.incoming_farmup_deposit : item.new_values?.deposit_paid_hbg;
      const label = {office_lead_saved_on_deposit_hold: `Office intake saved; ${money(after)}`, hb_deposit_review_reconciled: 'Legacy deposit-only review flag reconciled', hb_deposit_review_reconcile_reversed: 'Legacy review reconciliation reversed', hb_deposit_review_reconciliation_reversed: 'Legacy review reconciliation reversed'}[item.action];
      const change = label || (observed ? `FarmUp reported ${money(after)}; HB retained ${money(before)}` : before !== undefined || after !== undefined ? `${money(before)} → ${money(after)}` : 'FarmUp intake imported / updated');
      return `<article class="hb-history-row"><strong>${esc(change)}</strong><p>${esc(item.actor)} · ${esc(item.occurred_at)}</p>${item.reason ? `<p>${esc(item.reason)}</p>` : ''}</article>`;
    }).join('') : '<p class="meta">No recorded deposit changes yet.</p>';
    protection?.destroy();
    protection = window.MiniAppUtils?.bindFormCloseProtection?.(el('hb-deposit-form'), 'hb-deposit', () => JSON.stringify([el('hb-deposit-amount').value, el('hb-deposit-reason').value]));
  }
  async function load({force = false} = {}) {
    if (!el('hb-deposit-workspace') || (!force && protection?.isDirty())) return;
    const version = ++loadVersion;
    const id = el('portal-screen').dataset.hbActionFarmerId;
    try {
      const result = await deps.portalApi.apiFetch(`/hb-deposits/${encodeURIComponent(id)}/`, {}, deps.tg);
      if (version !== loadVersion || !el('hb-deposit-workspace')) return;
      if (!result.ok || !result.data?.ok) throw new Error(result.data?.error || 'Could not load the deposit.');
      render(result.data.deposit);
    } catch (failure) {
      const target = el('hb-deposit-loading');
      if (target && target.hidden) error(failure.message);
      else if (target) { target.innerHTML = `<p>${esc(failure.message)}</p><button class="btn btn-secondary" type="button" id="hb-deposit-retry">Retry</button>`; el('hb-deposit-retry').onclick = () => load({force: true}); }
    }
  }
  async function save(event) {
    event.preventDefault();
    if (!detail?.can_edit || el('hb-deposit-save').disabled) return;
    error('');
    const payload = {amount: el('hb-deposit-amount').value.trim(), reason: el('hb-deposit-reason').value.trim(), expected_revision: detail.workflow_revision};
    if (!/^\d+(?:\.\d{1,2})?$/.test(payload.amount)) return error('Enter a non-negative amount with at most two decimal places.');
    if (detail.recorded_amount !== null && Number(payload.amount) < Number(detail.recorded_amount) && !payload.reason) return error('Explain why the recorded total is being reduced.');
    const signature = JSON.stringify(payload);
    if (!pending || pending.signature !== signature) pending = {signature, key: window.crypto?.randomUUID?.() || `hb-deposit-${Date.now()}-${Math.random().toString(36).slice(2)}`};
    payload.client_request_id = pending.key;
    const button = el('hb-deposit-save');
    deps.setButtonLoading?.(button, true, 'Saving…'); button.disabled = true;
    try {
      const result = await deps.portalApi.apiFetch(`/hb-deposits/${encodeURIComponent(detail.id)}/update/`, {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': pending.key, 'X-Request-ID': pending.key}, body: JSON.stringify(payload)}, deps.tg);
      if (!result.ok || !result.data?.ok) {
        error(result.data?.error || 'Could not save. Retry safely with the same total.');
        if (result.data?.code === 'workflow_revision_conflict' || result.data?.code === 'deposit_locked') {error(`${result.data.error} Use Reload latest before making another change.`);el('hb-deposit-reload').hidden = false;}
        return;
      }
      protection?.markClean(); pending = null; render(result.data.deposit);
      deps.showToast('HB deposit total saved.', 'success');
    } catch (_) { error('The response was interrupted. Retry the same total to safely confirm the save.'); }
    finally { deps.setButtonLoading?.(button, false); button.disabled = !detail?.can_edit; }
  }
  function init(injected) {
    deps = injected; detail = null; pending = null; protection?.destroy(); protection = null;
    el('hb-deposit-form')?.addEventListener('submit', save);
    el('hb-deposit-amount')?.addEventListener('input', () => {
      if (el('hb-deposit-reason-row')) el('hb-deposit-reason-row').hidden = !(detail?.can_edit && detail.recorded_amount !== null && Number(el('hb-deposit-amount').value) < Number(detail.recorded_amount));
    });
    el('hb-deposit-reload')?.addEventListener('click', () => {
      if (protection?.isDirty() && !window.confirm('Discard unsaved deposit changes and reload the latest total?')) return;
      pending = null; error(''); load({force: true});
    });
  }
  window.PortalMiniAppHbDeposits = {init, load, money};
})();
