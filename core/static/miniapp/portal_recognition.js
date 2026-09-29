(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const state = { kind: 'month', period: '', metric: 'outcome', view: 'people',
    role: '', branch: '', product: '', page: 1, sequence: 0, payload: null,
    defaultRole: '', fetch: null, toast: null };

  function periodLabel(data) {
    const key = data.period || '';
    if (data.period_kind === 'year') return key;
    if (data.period_kind === 'quarter') return `${key.slice(5)} ${key.slice(0, 4)}`;
    const [year, month] = key.split('-').map(Number);
    return year && month ? new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
      .format(new Date(Date.UTC(year, month - 1, 1))) : key;
  }

  function overlay(id, open) {
    const node = $(id);
    node.classList.toggle('open', open);
    node.setAttribute('aria-hidden', open ? 'false' : 'true');
    window.dispatchEvent(new Event('portal:case-route-change'));
    if (open) node.querySelector('.sheet-close-button')?.focus();
    else $(id === 'portal-performance-filters' ? 'portal-performance-filter' : 'portal-performance-details-open')?.focus();
  }

  function options(id, values, selected, allLabel) {
    const node = $(id);
    node.innerHTML = [...(allLabel ? [{ value: '', label: allLabel }] : []), ...values]
      .map(item => `<option value="${safe(item.value)}">${safe(item.label)}</option>`).join('');
    node.value = selected;
  }

  function controlsVisibility() {
    const kind = $('portal-performance-period-kind').value;
    $('portal-performance-month-wrap').hidden = kind !== 'month';
    $('portal-performance-quarter-wrap').hidden = kind !== 'quarter';
    $('portal-performance-year-wrap').hidden = kind === 'month';
  }

  function syncScopeControls() {
    const role = $('portal-performance-role').value;
    const data = state.payload?.filter_options?.by_role?.[role] || { branches: [], products: [], products_by_branch: {} };
    const branch = $('portal-performance-branch').value;
    options('portal-performance-branch', data.branches.map(value => ({ value, label: value })), branch, 'All branches');
    const selectedBranch = $('portal-performance-branch').value;
    const products = selectedBranch ? data.products_by_branch[selectedBranch] || [] : data.products;
    const product = $('portal-performance-product').value;
    options('portal-performance-product', products.map(value => ({ value, label: value })), product, 'All products');
  }

  function details(data) {
    const result = data.personal || {};
    const outcome = result.outcome || {};
    const tat = result.tat || {};
    const stages = (outcome.stages || []).map(item =>
      `<div class="portal-performance-detail-row"><span>${safe(item.label)}</span><b>${safe(item.completed)}</b></div>`).join('');
    const context = data.business_context || {};
    const pipeline = context.visits ? `<section><h3>Pipeline context</h3><div class="portal-performance-detail-row"><span>JBL visits</span><b>${safe(context.visits)}</b></div><div class="portal-performance-detail-row"><span>Moved to credit</span><b>${safe(context.to_credit)}</b></div><div class="portal-performance-detail-row"><span>Final approval</span><b>${safe(context.final_approved)}</b></div><div class="portal-performance-detail-row"><span>Payment finalized</span><b>${safe(context.payment_finalized)}</b></div><p class="meta">Current downstream outcomes for cases first visited in this period. These are not staff scores.</p></section>` : '';
    $('portal-performance-details-content').innerHTML = `<div class="portal-performance-detail-body">
      <p class="meta">${safe(periodLabel(data))} · ${data.final ? 'Final' : 'Live'}</p>
      <section><h3>Accepted work</h3><div class="portal-performance-breakdown"><span class="positive"><b>${safe(outcome.accepted || 0)}</b> accepted</span><span class="negative"><b>${safe(outcome.reworked || 0)}</b> reworked</span></div><p class="meta">Valid decisions include justified rejection or deferral. Returned work is not accepted.</p></section>
      <section><h3>TAT</h3><div class="portal-performance-breakdown"><span class="positive"><b>${safe(tat.within || 0)}</b> within</span><span class="caution"><b>${safe(tat.near || 0)}</b> near</span><span class="negative"><b>${safe(tat.over || 0)}</b> over</span></div><p class="meta">${safe(data.personal_missing_target || 0)} action(s) without a target were excluded from TAT.</p></section>
      ${stages ? `<section><h3>Work by stage</h3>${stages}</section>` : ''}
      ${pipeline}
      <p class="meta">Rankings need ${safe(data.minimum_ranked_sample)} counted actions. Scores use a conservative quality estimate. Results are informational, not an HR or pay decision.</p>
    </div>`;
  }

  function render(data) {
    state.payload = data;
    state.role = data.role || '';
    if (!state.defaultRole) state.defaultRole = state.role;
    state.branch = data.branch || '';
    state.product = data.product || '';
    state.view = data.view || state.view;
    state.page = data.page || 1;
    $('portal-performance-period-label').textContent = `${periodLabel(data)} · ${data.final ? 'Final' : 'Live'}`;
    $('portal-performance-own-metrics').innerHTML = ['outcome', 'tat'].map(metric => {
      const item = data.personal?.[metric];
      const note = item?.completed ? `${item.completed} actions${item.ranked ? '' : ' · building sample'}` :
        (metric === 'tat' && data.personal_missing_target ? 'No target set' : 'No counted actions');
      return `<div class="portal-performance-own-cell"><span>${metric === 'tat' ? 'TAT' : 'Accepted work'}</span><strong>${item?.completed ? safe(item.score) : '—'}</strong><small>${safe(note)}</small></div>`;
    }).join('');
    const slice = data.slice;
    $('portal-performance-slice').hidden = state.role === state.defaultRole && !state.branch && !state.product;
    $('portal-performance-slice').innerHTML = `<span>Selected work</span><strong>${slice?.completed ? safe(slice.score) : '—'}</strong><small>${safe(slice?.completed || 0)} counted actions</small>`;
    $('portal-performance-metrics').querySelectorAll('button').forEach(button =>
      button.setAttribute('aria-pressed', String(button.dataset.performanceMetric === state.metric)));
    $('portal-performance-views').hidden = !data.people_visible;
    $('portal-performance-views').querySelectorAll('button').forEach(button =>
      button.setAttribute('aria-pressed', String(button.dataset.performanceView === state.view)));
    const roleLabel = data.roles?.find(item => item.value === state.role)?.label || 'Portal';
    $('portal-performance-standing-title').textContent = `${state.metric === 'tat' ? 'TAT' : 'Accepted work'} · ${state.view === 'people' ? 'People' : 'Branches'}`;
    $('portal-performance-comparison').textContent = `${roleLabel}${state.product ? ` · ${state.product}` : ''}${state.branch ? ` · ${state.branch}` : ''} · ${data.minimum_ranked_sample}+ actions to rank`;
    $('portal-performance-active-filters').hidden = !state.branch && !state.product;
    $('portal-performance-active-filters').innerHTML = [['branch', state.branch], ['product', state.product]]
      .filter(([, value]) => value).map(([key, value]) =>
        `<button type="button" data-performance-clear="${key}" aria-label="Remove ${key} filter">${safe(value)} <span aria-hidden="true">×</span></button>`).join('');
    $('portal-performance-active-filters').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
      state[button.dataset.performanceClear] = '';
      state.page = 1;
      reload();
    }));
    $('portal-performance-list').innerHTML = (data.rows || []).map(item => {
      const movement = item.movement || {};
      const arrow = movement.direction === 'up' ? '↑' : movement.direction === 'down' ? '↓' : '';
      const detail = state.metric === 'tat'
        ? `${item.within} within · ${item.near} near · ${item.over} over`
        : `${item.accepted} accepted · ${item.reworked} reworked`;
      return `<article class="portal-performance-row"><span class="portal-performance-rank">${safe(item.rank)}</span><div class="portal-performance-person"><strong>${safe(item.label)}</strong><small>${safe(detail)}</small></div><b class="portal-performance-row-score">${safe(item.score)}</b><span class="portal-performance-movement ${safe(movement.direction || 'none')}" aria-label="${arrow ? `${movement.direction} ${movement.places} places` : 'No rank change'}">${arrow ? `${arrow}${safe(movement.places)}` : ''}</span></article>`;
    }).join('') || `<div class="empty-state"><div class="es-title">No ranked ${state.view} yet</div><div class="es-sub">${state.metric === 'tat' ? 'Completed actions need a configured target and enough samples.' : 'More completed work is needed to reach the ranking sample.'}</div></div>`;
    $('portal-performance-pages').hidden = data.pages <= 1;
    $('portal-performance-page-label').textContent = `Page ${data.page} of ${data.pages}`;
    $('portal-performance-prev').disabled = data.page <= 1;
    $('portal-performance-next').disabled = data.page >= data.pages;
    details(data);
  }

  function reload() { load().catch(error => state.toast?.(error.message, 'error')); }

  function bind() {
    const filter = $('portal-performance-filter');
    if (!filter || filter.dataset.bound) return;
    filter.dataset.bound = 'true';
    filter.addEventListener('click', () => {
      const data = state.payload || {};
      const parts = state.period.split('-');
      $('portal-performance-period-kind').value = state.kind;
      $('portal-performance-period').value = state.kind === 'month' ? state.period : '';
      $('portal-performance-year').value = parts[0] || new Date().getFullYear();
      $('portal-performance-quarter').value = state.kind === 'quarter' ? (parts[1] || 'Q1').replace('Q', '') : '1';
      controlsVisibility();
      options('portal-performance-role', data.roles || [], state.role, '');
      options('portal-performance-branch', (data.filter_options?.branches || []).map(value => ({ value, label: value })), state.branch, 'All branches');
      options('portal-performance-product', (data.filter_options?.products || []).map(value => ({ value, label: value })), state.product, 'All products');
      overlay('portal-performance-filters', true);
    });
    $('portal-performance-period-kind').addEventListener('change', controlsVisibility);
    $('portal-performance-role').addEventListener('change', syncScopeControls);
    $('portal-performance-branch').addEventListener('change', syncScopeControls);
    $('portal-performance-filter-close').addEventListener('click', () => overlay('portal-performance-filters', false));
    $('portal-performance-details-open').addEventListener('click', () => overlay('portal-performance-details', true));
    $('portal-performance-details-close').addEventListener('click', () => overlay('portal-performance-details', false));
    ['portal-performance-filters', 'portal-performance-details'].forEach(id => {
      $(id).addEventListener('click', event => { if (event.target === $(id)) overlay(id, false); });
      $(id).addEventListener('keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); overlay(id, false); }
      });
    });
    $('portal-performance-clear').addEventListener('click', () => ['branch', 'product'].forEach(key => { $(`portal-performance-${key}`).value = ''; }));
    $('portal-performance-apply').addEventListener('click', () => {
      const kind = $('portal-performance-period-kind').value;
      const year = $('portal-performance-year').value;
      const period = kind === 'month' ? $('portal-performance-period').value :
        kind === 'quarter' ? `${year}-Q${$('portal-performance-quarter').value}` : year;
      if (!period) { state.toast?.('Choose a period.', 'error'); return; }
      state.kind = kind; state.period = period;
      state.role = $('portal-performance-role').value;
      state.branch = $('portal-performance-branch').value;
      state.product = $('portal-performance-product').value;
      state.page = 1;
      overlay('portal-performance-filters', false);
      reload();
    });
    $('portal-performance-metrics').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
      state.metric = button.dataset.performanceMetric; state.page = 1; reload();
    }));
    $('portal-performance-views').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
      state.view = button.dataset.performanceView; state.page = 1; reload();
    }));
    [['prev', -1], ['next', 1]].forEach(([name, delta]) => $(`portal-performance-${name}`).addEventListener('click', () => {
      state.page += delta; reload();
    }));
  }

  async function load(dependencies) {
    if (dependencies) { state.fetch = dependencies.apiFetch; state.toast = dependencies.showToast; }
    bind();
    if (!state.period) {
      const parts = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: '2-digit', timeZone: 'Africa/Nairobi' }).formatToParts(new Date());
      state.period = `${parts.find(item => item.type === 'year').value}-${parts.find(item => item.type === 'month').value}`;
    }
    const sequence = ++state.sequence;
    const query = new URLSearchParams({ period: state.period, period_kind: state.kind,
      metric: state.metric, view: state.view, role: state.role, branch: state.branch,
      product: state.product, page: String(state.page) });
    $('portal-performance-list').setAttribute('aria-busy', 'true');
    try {
      const { ok, data } = await state.fetch('/performance/?' + query.toString());
      if (sequence !== state.sequence) return;
      if (!ok || !data?.ok) throw new Error(data?.message || data?.error || 'Performance could not be loaded.');
      render(data.data || {});
    } finally {
      if (sequence === state.sequence) $('portal-performance-list').removeAttribute('aria-busy');
    }
  }

  window.PortalRecognitionUI = { load };
})();
