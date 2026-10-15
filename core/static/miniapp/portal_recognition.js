(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const state = { kind: 'month', period: '', view: 'people', branch: '', product: '',
    page: 1, sequence: 0, payload: null, fetch: null, toast: null, returnFocus: null,
    awaitingPage: 1, awaitingSequence: 0 };

  function periodLabel(data) {
    const key = data.period || '';
    if (data.period_kind === 'year') return key;
    if (data.period_kind === 'quarter') return `${key.slice(5)} ${key.slice(0, 4)}`;
    const [year, month] = key.split('-').map(Number);
    return year && month ? new Intl.DateTimeFormat('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
      .format(new Date(Date.UTC(year, month - 1, 1))) : key;
  }

  function syncMonthDisplay() {
    $('portal-performance-month-display').textContent = periodLabel({
      period: $('portal-performance-period').value, period_kind: 'month',
    }) || 'Select month';
  }

  function overlay(id, open) {
    const node = $(id);
    if (open) state.returnFocus = document.activeElement;
    node.classList.toggle('open', open);
    node.setAttribute('aria-hidden', String(!open));
    document.body.classList.toggle('portal-overlay-open', open);
    window.dispatchEvent(new Event('portal:case-route-change'));
    if (open) node.querySelector('.sheet-close-button')?.focus();
    else (state.returnFocus?.isConnected ? state.returnFocus : $('portal-performance-filter'))?.focus();
    if (!open && id === 'portal-performance-awaiting') state.awaitingSequence += 1;
  }

  function options(id, values, selected, allLabel) {
    const node = $(id);
    node.innerHTML = [{ value: '', label: allLabel }, ...values.map(value => ({ value, label: value }))]
      .map(item => `<option value="${safe(item.value)}">${safe(item.label)}</option>`).join('');
    node.value = selected;
  }

  function controlsVisibility() {
    const kind = $('portal-performance-period-kind').value;
    $('portal-performance-month-wrap').hidden = kind !== 'month';
    $('portal-performance-quarter-wrap').hidden = kind !== 'quarter';
    $('portal-performance-year-wrap').hidden = kind === 'month';
  }

  function syncProductOptions() {
    const branch = $('portal-performance-branch').value;
    const all = state.payload?.filter_options || {};
    const products = branch ? all.products_by_branch?.[branch] || [] : all.products || [];
    options('portal-performance-product', products, $('portal-performance-product').value, 'All products');
  }

  function details(data) {
    const item = data.personal || {};
    const stages = item.milestones || [];
    $('portal-performance-details-content').innerHTML = `<div class="portal-performance-detail-body">
      <div class="portal-performance-detail-summary"><strong>${safe(item.points || 0)}</strong><div><span>Your overall points</span><small>${safe(periodLabel(data))} · ${data.final ? 'Final' : 'Live'}</small></div></div>
      <div class="portal-performance-detail-facts"><span><b>${safe(item.cases || 0)}</b> cases</span><span><b>${safe(item.visits || 0)}</b> visits</span></div>
      <section class="portal-performance-contributions"><div class="portal-performance-contribution-heading"><h3>Milestone contributions</h3><details class="miniapp-chart-help"><summary aria-label="How points work"><i data-lucide="circle-help" aria-hidden="true"></i></summary><div class="miniapp-chart-help-content">Each case earns its JBL visiting officer one point per completed milestone. Credit and final review must be approved. Points count in the period the milestone happened.</div></details></div><dl>${stages.map(stage => `<div class="portal-performance-contribution${stage.count ? ' earned' : ''}"><dt>${safe(stage.label)}</dt><dd>${stage.count ? '+' : ''}${safe(stage.count)}</dd></div>`).join('') || '<p class="meta">No milestones yet.</p>'}</dl></section>
      ${data.captured_at ? `<p class="meta">Final result captured ${safe(new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Africa/Nairobi' }).format(new Date(data.captured_at)))} EAT</p>` : ''}
    </div>`;
    window.lucide?.createIcons();
  }

  function render(data) {
    state.payload = data;
    state.branch = data.branch || '';
    state.product = data.product || '';
    state.view = data.view || state.view;
    state.page = data.page || 1;
    $('portal-performance-period-label').textContent = `${periodLabel(data)} · ${data.final ? 'Final' : 'Live'}`;
    const own = data.personal;
    $('portal-performance-own-metrics').innerHTML = `<div class="portal-performance-own-cell"><strong>${safe(own?.points || 0)}</strong><small>points</small></div><div class="portal-performance-own-cell"><strong>${safe(own?.cases || 0)}</strong><small>cases</small></div><div class="portal-performance-own-cell"><strong>${safe(own?.visits || 0)}</strong><small>visits</small></div>`;
    $('portal-performance-slice').hidden = !state.branch && !state.product;
    $('portal-performance-slice').innerHTML = `<span>Selected work</span><strong>${safe(data.slice?.points || 0)} points</strong><small>${safe(data.slice?.cases || 0)} cases</small>`;
    $('portal-performance-views').hidden = !data.people_visible;
    $('portal-performance-views').querySelectorAll('button').forEach(button =>
      button.setAttribute('aria-pressed', String(button.dataset.performanceView === state.view)));
    $('portal-performance-standing-title').textContent = state.view === 'people' ? 'People' : 'Branches';
    $('portal-performance-comparison').textContent = state.view === 'people' ? 'JBL officers · Case milestone points' : 'Milestone points';
    $('portal-performance-active-filters').hidden = !state.branch && !state.product;
    $('portal-performance-active-filters').innerHTML = [['branch', state.branch], ['product', state.product]]
      .filter(([, value]) => value).map(([key, value]) =>
        `<button type="button" data-performance-clear="${key}" aria-label="Remove ${key} filter">${safe(value)} <span aria-hidden="true">×</span></button>`).join('');
    $('portal-performance-active-filters').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
      state[button.dataset.performanceClear] = ''; state.page = 1; reload();
    }));
    $('portal-performance-list').innerHTML = (data.rows || []).map(item => {
      const movement = item.movement || {};
      const arrow = movement.direction === 'up' ? '↑' : movement.direction === 'down' ? '↓' : '';
      return `<article class="portal-performance-row${item.is_current_user ? ' current-user' : ''}"><span class="portal-performance-rank">${safe(item.rank)}</span><div class="portal-performance-person"><strong>${safe(item.label)}${item.is_current_user ? ' <small class="portal-performance-you">You</small>' : ''}</strong><small>${safe(item.cases)} cases · ${safe(item.visits)} visits</small></div><div class="portal-performance-score"><b class="portal-performance-row-score" aria-label="${safe(item.points)} points">${safe(item.points)}</b><span class="portal-performance-movement ${safe(movement.direction || 'none')}" aria-label="${arrow ? `${movement.direction} ${movement.places} places` : 'No rank change'}">${arrow ? `${arrow}${safe(movement.places)}` : ''}</span></div></article>`;
    }).join('') || `<div class="empty-state"><div class="es-title">No ${state.view} points yet</div><div class="es-sub">Points appear when a JBL officer's case reaches a milestone in this period.</div></div>`;
    $('portal-performance-pages').hidden = data.pages <= 1;
    $('portal-performance-page-label').textContent = `Page ${data.page} of ${data.pages}`;
    $('portal-performance-prev').disabled = data.page <= 1;
    $('portal-performance-next').disabled = data.page >= data.pages;
    const awaiting = data.awaiting_visits;
    $('portal-performance-awaiting-open').hidden = state.view !== 'branches' || !awaiting?.total;
    $('portal-performance-awaiting-open').textContent = `Awaiting visit now · ${awaiting?.total || 0}`;
    details(data);
  }

  function query() {
    return new URLSearchParams({ period: state.period, period_kind: state.kind,
      view: state.view, branch: state.branch, product: state.product, page: String(state.page) });
  }

  async function loadAwaiting(page = 1) {
    const sequence = ++state.awaitingSequence;
    const params = query();
    params.set('awaiting_page', String(page));
    const content = $('portal-performance-awaiting-content');
    content.setAttribute('aria-busy', 'true');
    $('portal-performance-awaiting-pages').hidden = true;
    content.innerHTML = '<p class="meta" role="status">Loading cases…</p>';
    try {
      const { ok, data } = await state.fetch('/performance/?' + params.toString());
      if (sequence !== state.awaitingSequence || !content.isConnected) return;
      if (!ok || !data?.ok) throw new Error(data?.message || data?.error || 'Cases could not be loaded.');
      const pending = data.data?.awaiting_visits || {};
      state.awaitingPage = pending.page || 1;
      content.innerHTML = (pending.rows || []).map(item => `<a class="portal-performance-awaiting-case" data-farmer-id="${safe(item.id)}" href="${safe(item.url)}"><span><strong>${safe(item.name || 'Unnamed customer')}</strong><small>${safe(item.branch)} · ${safe(item.product)}</small></span><i data-lucide="chevron-right" aria-hidden="true"></i></a>`).join('') || '<p class="meta">No cases awaiting a visit.</p>';
      $('portal-performance-awaiting-pages').hidden = (pending.pages || 1) <= 1;
      $('portal-performance-awaiting-page').textContent = `${state.awaitingPage} / ${pending.pages || 1}`;
      $('portal-performance-awaiting-prev').disabled = state.awaitingPage <= 1;
      $('portal-performance-awaiting-next').disabled = state.awaitingPage >= (pending.pages || 1);
      window.lucide?.createIcons();
    } catch (error) {
      if (sequence !== state.awaitingSequence || !content.isConnected) return;
      content.innerHTML = '<p class="meta">Cases could not be loaded.</p><button type="button" class="secondary" id="portal-performance-awaiting-retry">Retry</button>';
      $('portal-performance-awaiting-retry').addEventListener('click', () => loadAwaiting(page));
      state.toast?.(error.message, 'error');
    } finally {
      if (sequence === state.awaitingSequence) content.removeAttribute('aria-busy');
    }
  }

  function reload() { load().catch(error => state.toast?.(error.message, 'error')); }

  function bind() {
    const filter = $('portal-performance-filter');
    if (!filter || filter.dataset.bound) return;
    filter.dataset.bound = 'true';
    $('portal-performance-filters').querySelector('.portal-performance-filter-fields').classList.add('miniapp-report-filter-fields');
    filter.addEventListener('click', () => {
      const parts = state.period.split('-');
      $('portal-performance-period-kind').value = state.kind;
      $('portal-performance-period').value = state.kind === 'month' ? state.period : '';
      $('portal-performance-year').value = parts[0] || new Date().getFullYear();
      $('portal-performance-quarter').value = state.kind === 'quarter' ? (parts[1] || 'Q1').replace('Q', '') : '1';
      controlsVisibility(); syncMonthDisplay();
      const filters = state.payload?.filter_options || {};
      options('portal-performance-branch', filters.branches || [], state.branch, 'All branches');
      syncProductOptions();
      overlay('portal-performance-filters', true);
    });
    $('portal-performance-period-kind').addEventListener('change', controlsVisibility);
    $('portal-performance-period').addEventListener('change', syncMonthDisplay);
    $('portal-performance-branch').addEventListener('change', syncProductOptions);
    $('portal-performance-filter-close').addEventListener('click', () => overlay('portal-performance-filters', false));
    $('portal-performance-details-open').addEventListener('click', () => overlay('portal-performance-details', true));
    $('portal-performance-details-close').addEventListener('click', () => overlay('portal-performance-details', false));
    $('portal-performance-awaiting-open').addEventListener('click', () => {
      overlay('portal-performance-awaiting', true); loadAwaiting();
    });
    $('portal-performance-awaiting-close').addEventListener('click', () => overlay('portal-performance-awaiting', false));
    $('portal-performance-awaiting-content').addEventListener('click', event => {
      const link = event.target.closest('.portal-performance-awaiting-case');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey
          || event.shiftKey || event.altKey || !window.PortalAppShell?.navigateUrl) return;
      event.preventDefault();
      window.PortalAppShell.navigateUrl(link.href);
    });
    ['portal-performance-filters', 'portal-performance-details', 'portal-performance-awaiting'].forEach(id => {
      $(id).addEventListener('click', event => { if (event.target === $(id)) overlay(id, false); });
      $(id).addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); overlay(id, false); } });
    });
    $('portal-performance-clear').addEventListener('click', () => {
      $('portal-performance-branch').value = ''; syncProductOptions(); $('portal-performance-product').value = '';
    });
    $('portal-performance-apply').addEventListener('click', () => {
      const kind = $('portal-performance-period-kind').value;
      const year = $('portal-performance-year').value;
      const period = kind === 'month' ? $('portal-performance-period').value :
        kind === 'quarter' ? `${year}-Q${$('portal-performance-quarter').value}` : year;
      if (!period) { state.toast?.('Choose a period.', 'error'); return; }
      state.kind = kind; state.period = period;
      state.branch = $('portal-performance-branch').value;
      state.product = $('portal-performance-product').value;
      state.page = 1; overlay('portal-performance-filters', false); reload();
    });
    $('portal-performance-views').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
      state.view = button.dataset.performanceView; state.page = 1; reload();
    }));
    [['prev', -1], ['next', 1]].forEach(([name, delta]) => $(`portal-performance-${name}`).addEventListener('click', () => {
      state.page += delta; reload();
    }));
    [['prev', -1], ['next', 1]].forEach(([name, delta]) => $(`portal-performance-awaiting-${name}`).addEventListener('click', () => loadAwaiting(state.awaitingPage + delta)));
  }

  async function load(dependencies) {
    if (dependencies) { state.fetch = dependencies.apiFetch; state.toast = dependencies.showToast; }
    bind();
    if (!state.period) {
      const parts = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: '2-digit', timeZone: 'Africa/Nairobi' }).formatToParts(new Date());
      state.period = `${parts.find(item => item.type === 'year').value}-${parts.find(item => item.type === 'month').value}`;
    }
    const sequence = ++state.sequence;
    const params = query();
    $('portal-performance-list').setAttribute('aria-busy', 'true');
    try {
      const { ok, data } = await state.fetch('/performance/?' + params.toString());
      if (sequence !== state.sequence) return;
      if (!ok || !data?.ok) throw new Error(data?.message || data?.error || 'Performance could not be loaded.');
      render(data.data || {});
    } finally {
      if (sequence === state.sequence) $('portal-performance-list').removeAttribute('aria-busy');
    }
  }

  window.PortalRecognitionUI = { load };
})();
