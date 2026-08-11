// Independent Case History loader. Keep this outside portal.js so a failure in
// the general Portal bootstrap can never leave the server-rendered spinner up.
(() => {
  'use strict';

  const TIMEOUT_MS = 22000;
  let sequence = 0;

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = String(value == null ? '' : value);
    return node.innerHTML;
  }

  function currentTarget(farmerId) {
    const root = document.getElementById('portal-screen');
    const content = document.getElementById('case-history-content');
    return root?.dataset.screen === 'case_history'
      && root.dataset.caseFarmerId === String(farmerId)
      && content && document.body.contains(content)
      ? content : null;
  }

  function failureHtml(farmerId, message) {
    return `<div class="batch-warning" role="alert"><strong>Could not load complete case history</strong><p>${escapeHtml(message)}</p><button type="button" class="btn btn-secondary case-history-independent-retry" data-farmer-id="${escapeHtml(farmerId)}">Retry</button></div>`;
  }

  async function load(farmerId) {
    const content = currentTarget(farmerId);
    const api = window.PortalMiniAppApi;
    const renderer = window.PortalMiniAppFarmerSheet?.renderCase360;
    if (!content) return false;
    if (!api?.apiFetch || typeof renderer !== 'function') {
      content.innerHTML = failureHtml(farmerId, 'The Case History module did not start. Reload the Portal and try again.');
      return false;
    }

    const token = `independent:${++sequence}:${farmerId}`;
    content.dataset.caseHistoryIndependentToken = token;
    content.innerHTML = '<div class="empty-state"><div class="spinner-inline"></div><div class="es-sub">Loading complete case history...</div></div>';
    const ownsTarget = () => currentTarget(farmerId) === content
      && content.dataset.caseHistoryIndependentToken === token;
    const watchdog = window.setTimeout(() => {
      if (ownsTarget()) content.innerHTML = failureHtml(farmerId, 'The request exceeded 22 seconds. Tap Retry; it will not remain stuck on this screen.');
    }, TIMEOUT_MS);

    try {
      const result = await api.apiFetch(
        '/farmers/' + encodeURIComponent(farmerId) + '/',
        undefined,
        window.Telegram?.WebApp,
      );
      if (!ownsTarget()) return false;
      if (!result.ok || !result.data?.ok || !result.data.case360) {
        throw new Error(result.data?.error || 'The server could not return this case history.');
      }
      renderer(result.data.case360, content);
      return true;
    } catch (error) {
      if (ownsTarget()) content.innerHTML = failureHtml(farmerId, error.message || 'Check your connection and try again.');
      return false;
    } finally {
      window.clearTimeout(watchdog);
    }
  }

  function loadCurrent() {
    const root = document.getElementById('portal-screen');
    const farmerId = root?.dataset.screen === 'case_history' ? root.dataset.caseFarmerId : '';
    if (farmerId) load(farmerId);
  }

  document.addEventListener('click', event => {
    const retry = event.target.closest('.case-history-independent-retry');
    if (retry) load(retry.dataset.farmerId);
  });
  document.addEventListener('DOMContentLoaded', loadCurrent, { once: true });
  document.addEventListener('htmx:afterSwap', loadCurrent);
  document.addEventListener('htmx:historyRestore', loadCurrent);

  window.PortalCaseHistoryLoader = { load, loadCurrent };
})();
